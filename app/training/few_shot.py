"""
Few-shot example retrieval — uses sentence embeddings to find the best
historical analyses to inject as in-context examples for new prompts.

This is the "training without fine-tuning" approach:
  - High-quality past analyses (with confirmed good outcomes) are embedded.
  - For each new request, we find K most similar past examples by symbol/timeframe/regime.
  - Those are injected as few-shot exemplars into the system prompt.

Backed by ChromaDB (embedded mode — no separate server needed).
Falls back gracefully if embeddings library unavailable.
"""

import logging
import json
from typing import Optional, List
from pathlib import Path

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.few_shot_example import FewShotExample
from app.models.analysis import Analysis

logger = logging.getLogger(__name__)

CHROMA_PATH = Path("./data/chroma_db")
COLLECTION_NAME = "few_shot_examples_v1"
EMBED_MODEL = "all-MiniLM-L6-v2"  # 22MB, fast, good baseline


# ─── Lazy loaders (heavy libs imported only when needed) ───

_chroma_client = None
_collection = None
_embedder = None


def _get_embedder():
    """Lazy-import sentence-transformers."""
    global _embedder
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer(EMBED_MODEL)
            logger.info("Loaded embedding model: %s", EMBED_MODEL)
        except ImportError:
            logger.warning("sentence-transformers not installed — few-shot retrieval disabled")
            return None
    return _embedder


def _get_chroma():
    """Lazy-init ChromaDB embedded client."""
    global _chroma_client, _collection
    if _collection is not None:
        return _collection
    try:
        import chromadb
        CHROMA_PATH.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        _collection = _chroma_client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Gold Nightmare few-shot exemplars"},
        )
        logger.info("ChromaDB ready (%d existing items)", _collection.count())
        return _collection
    except ImportError:
        logger.warning("chromadb not installed — few-shot retrieval disabled")
        return None


def _build_search_text(symbol: str, timeframe: str, market_regime: Optional[str], context: Optional[str]) -> str:
    """Build the text used to search for similar examples."""
    parts = [f"symbol:{symbol}", f"tf:{timeframe}"]
    if market_regime:
        parts.append(f"regime:{market_regime}")
    if context:
        parts.append(f"context:{context[:300]}")
    return " | ".join(parts)


def _summarize_for_embedding(result_json: dict) -> str:
    """Turn an analysis result into a compact text summary for embedding."""
    meta = result_json.get("chart_meta", {})
    bias = result_json.get("session_bias", {})
    pd = result_json.get("premium_discount", {})
    setups = result_json.get("setups", [])
    parts = [
        f"sym:{meta.get('symbol','?')}",
        f"tf:{meta.get('timeframe','?')}",
        f"trend:{meta.get('trend_direction','?')}",
        f"bias:{bias.get('primary_bias','?')}",
        f"zone:{pd.get('current_zone','?')}",
        f"setups:{len(setups)}",
    ]
    if setups:
        s0 = setups[0]
        parts.append(f"primary_dir:{s0.get('direction','?')}")
        parts.append(f"primary_rr:{s0.get('risk_reward','?')}")
    return " ".join(parts)


# ─── Public API ───

async def add_to_index(db: AsyncSession, example: FewShotExample, force_re_embed: bool = False) -> bool:
    """Compute embedding for an example and insert into ChromaDB."""
    embedder = _get_embedder()
    collection = _get_chroma()
    if not embedder or not collection:
        return False

    if not force_re_embed and example.embedding_id:
        return True  # already indexed

    text_for_embedding = _build_search_text(
        example.symbol, example.timeframe, example.market_regime, example.summary_text
    )
    embedding = embedder.encode(text_for_embedding).tolist()

    # Upsert
    metadata = {
        "symbol": example.symbol,
        "timeframe": example.timeframe,
        "market_regime": example.market_regime or "unknown",
        "quality_score": float(example.quality_score),
        "realized_rr": float(example.realized_rr) if example.realized_rr is not None else 0.0,
    }
    collection.upsert(
        ids=[example.id],
        embeddings=[embedding],
        metadatas=[metadata],
        documents=[example.summary_text[:1000]],
    )
    example.embedding_id = example.id
    example.embedding_model = EMBED_MODEL
    await db.flush()
    return True


async def find_similar_examples(
    symbol: str,
    timeframe: str,
    market_regime: Optional[str] = None,
    context: Optional[str] = None,
    k: int = 3,
) -> List[dict]:
    """
    Find K most similar few-shot examples for a new request.
    Returns lightweight dicts ready to inject into prompts.
    """
    embedder = _get_embedder()
    collection = _get_chroma()
    if not embedder or not collection:
        return []
    if collection.count() == 0:
        return []

    query_text = _build_search_text(symbol, timeframe, market_regime, context)
    query_emb = embedder.encode(query_text).tolist()

    # Filter by symbol+timeframe match preferred
    where = {"symbol": symbol}
    try:
        results = collection.query(
            query_embeddings=[query_emb],
            n_results=min(k, collection.count()),
            where=where,
        )
    except Exception:
        results = collection.query(query_embeddings=[query_emb], n_results=min(k, collection.count()))

    out = []
    docs = (results.get("documents") or [[]])[0]
    metas = (results.get("metadatas") or [[]])[0]
    ids = (results.get("ids") or [[]])[0]
    for doc, meta, eid in zip(docs, metas, ids):
        out.append({
            "id": eid,
            "summary": doc,
            "metadata": meta,
        })
    return out


async def promote_analysis_to_example(
    db: AsyncSession,
    analysis: Analysis,
    market_regime: Optional[str] = None,
    realized_rr: Optional[float] = None,
    quality_score: float = 5.0,
) -> FewShotExample:
    """
    Create a FewShotExample from an existing analysis and add it to the vector store.
    """
    summary = _summarize_for_embedding(analysis.result_json or {})
    example = FewShotExample(
        source_analysis_id=analysis.id,
        symbol=analysis.symbol,
        timeframe=analysis.timeframe,
        market_regime=market_regime,
        summary_text=summary,
        full_result_json=analysis.result_json,
        quality_score=quality_score,
        realized_rr=realized_rr,
        is_active=True,
    )
    db.add(example)
    await db.flush()
    await add_to_index(db, example)
    return example


def format_examples_for_prompt(examples: List[dict]) -> str:
    """
    Format retrieved examples as text to inject into the system prompt.
    """
    if not examples:
        return ""
    lines = ["\n# REFERENCE EXAMPLES (use these patterns from historical successful analyses):"]
    for i, ex in enumerate(examples[:3], 1):
        m = ex.get("metadata", {})
        lines.append(
            f"\n[Example {i} | {m.get('symbol','')} {m.get('timeframe','')} | "
            f"regime: {m.get('market_regime','?')} | realized R:R: {m.get('realized_rr',0):.2f}]"
        )
        lines.append(ex.get("summary", "")[:500])
    lines.append("\n# Use these as anchors for analyzing the current chart but do not copy them blindly.")
    return "\n".join(lines)


def get_index_stats() -> dict:
    """Return current state of the vector store."""
    collection = _get_chroma()
    if not collection:
        return {"available": False, "count": 0}
    return {
        "available": True,
        "count": collection.count(),
        "model": EMBED_MODEL,
        "path": str(CHROMA_PATH),
    }
