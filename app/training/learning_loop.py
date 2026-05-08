"""
Learning Loop — closes the feedback cycle.

Pipeline:
  1. Pull all closed outcomes (tp_full or sl_hit).
  2. Extract feature vector from each (direction, zone, bias, rr_band, vol_regime, etc).
  3. Group by feature signatures, compute win rate per group.
  4. Promote winning patterns (win_rate > 0.65, n >= 5) → injected in prompts.
  5. Demote losing patterns (win_rate < 0.35, n >= 5) → block in validator.
  6. Save to learned_insights table.

Runs:
  - Manually via API endpoint.
  - Weekly via scheduler.

Output is consumed by:
  - prompts.py (winning insights → "STRATEGIES THAT WORK FOR YOU")
  - validator.py (losing patterns → block matching setups)
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import Analysis
from app.models.analysis_outcome import AnalysisOutcome
from app.models.learned_insight import LearnedInsight

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  Feature extraction
# ═══════════════════════════════════════════════════════════════════

def _rr_band(rr_str: Optional[str]) -> str:
    if not rr_str:
        return "unknown"
    try:
        parts = rr_str.replace("→", ":").split(":")
        nums = [float(p.strip()) for p in parts if p.strip().replace(".", "").isdigit()]
        rr = nums[1] / nums[0] if len(nums) >= 2 and nums[0] else 0
    except Exception:
        return "unknown"
    if rr <= 0: return "unknown"
    if rr < 1.5: return "low"
    if rr < 2.5: return "mid"
    return "high"


def _extract_features(analysis: Analysis, setup_index: int) -> Optional[dict]:
    """Pull a feature signature from an analysis + setup index."""
    setups = (analysis.result_json or {}).get("setups", [])
    if setup_index >= len(setups):
        return None
    setup = setups[setup_index]

    result = analysis.result_json or {}
    bias = (result.get("session_bias") or {}).get("primary_bias")
    zone = (result.get("premium_discount") or {}).get("current_zone")

    return {
        "direction": setup.get("direction"),
        "zone": zone,
        "htf_bias": bias,
        "rr_band": _rr_band(setup.get("risk_reward")),
        "timeframe": analysis.timeframe,
        "is_mtf": analysis.is_mtf,
    }


def _signature_key(features: dict, dims: List[str]) -> Tuple:
    """Project a feature dict onto a subset of dimensions to create a group key."""
    return tuple((d, features.get(d)) for d in dims)


# ═══════════════════════════════════════════════════════════════════
#  Pattern mining
# ═══════════════════════════════════════════════════════════════════

# Try multiple feature combinations. Each tuple defines a "view" we cluster on.
DIM_COMBINATIONS = [
    ["direction", "zone"],
    ["direction", "htf_bias"],
    ["direction", "zone", "htf_bias"],
    ["direction", "rr_band"],
    ["direction", "timeframe"],
    ["direction", "zone", "rr_band"],
    ["direction", "htf_bias", "rr_band"],
]


async def mine_patterns(
    db: AsyncSession,
    min_samples: int = 5,
    win_threshold: float = 0.65,
    loss_threshold: float = 0.35,
) -> dict:
    """
    Mine winning + losing patterns. Replaces existing insights.
    """
    rows = (await db.execute(
        select(AnalysisOutcome, Analysis)
        .join(Analysis, AnalysisOutcome.analysis_id == Analysis.id)
        .where(and_(
            AnalysisOutcome.is_active.is_(False),
            AnalysisOutcome.status.in_(["tp_full", "sl_hit"]),
        ))
    )).all()

    if not rows:
        return {"mined": False, "reason": "no closed outcomes yet", "samples": 0}

    # Build flat list of (features, won, realized_rr) tuples
    points = []
    for outcome, analysis in rows:
        feats = _extract_features(analysis, outcome.setup_index)
        if not feats:
            continue
        won = outcome.status == "tp_full"
        rr = float(outcome.realized_rr) if outcome.realized_rr is not None else 0.0
        points.append((feats, won, rr))

    if len(points) < min_samples:
        return {"mined": False, "reason": f"only {len(points)} samples (need {min_samples})", "samples": len(points)}

    # Cluster on each dimension combination
    clusters: Dict[Tuple, List] = defaultdict(list)
    for feats, won, rr in points:
        for dims in DIM_COMBINATIONS:
            key = _signature_key(feats, dims)
            clusters[key].append((won, rr, feats))

    # Compute stats per cluster, dedupe overlaps by keeping the most specific significant pattern
    candidate_insights: List[LearnedInsight] = []
    seen_signatures = set()

    # Sort clusters by specificity (more dims = more specific) so specific wins ties
    sorted_clusters = sorted(clusters.items(), key=lambda kv: -len(kv[0]))

    for key, items in sorted_clusters:
        n = len(items)
        if n < min_samples:
            continue

        wins = sum(1 for w, _, _ in items if w)
        losses = n - wins
        wr = wins / n
        win_rrs = [rr for w, rr, _ in items if w and rr is not None]
        loss_rrs = [rr for w, rr, _ in items if not w and rr is not None]
        avg_win_R = sum(win_rrs) / len(win_rrs) if win_rrs else 0.0
        avg_loss_R = sum(loss_rrs) / len(loss_rrs) if loss_rrs else -1.0
        expectancy = wr * avg_win_R + (1 - wr) * avg_loss_R
        avg_rr = sum(rr for _, rr, _ in items if rr is not None) / n if n > 0 else 0

        # Confidence — basic Wilson-ish: more samples & extreme rate = more confident
        confidence = min(1.0, (n / 20) * (abs(wr - 0.5) * 2))

        # Pull feature dict from first item (all in cluster share these dims)
        features = {k: v for k, v in dict(key).items() if v is not None}

        # Skip if not winning and not losing
        if loss_threshold < wr < win_threshold:
            continue

        # Skip if a more-specific pattern already covers a superset of these features
        sig = frozenset(features.items())
        skip = False
        for existing_sig in seen_signatures:
            if sig.issubset(existing_sig):  # less specific than something already saved
                skip = True
                break
        if skip:
            continue
        seen_signatures.add(sig)

        kind = "winning_pattern" if wr >= win_threshold else "losing_pattern"
        summary = _build_summary(kind, features, n, wr, avg_rr, expectancy)

        candidate_insights.append(LearnedInsight(
            kind=kind,
            features=features,
            sample_size=n, wins=wins, losses=losses,
            win_rate=round(wr, 4),
            avg_realized_rr=round(avg_rr, 4),
            expectancy=round(expectancy, 4),
            confidence=round(confidence, 4),
            summary_ar=summary,
            is_active=True,
            last_refreshed_at=datetime.utcnow(),
        ))

    # Replace old insights
    await db.execute(delete(LearnedInsight))
    for ins in candidate_insights:
        db.add(ins)
    await db.flush()

    winning = [i for i in candidate_insights if i.kind == "winning_pattern"]
    losing = [i for i in candidate_insights if i.kind == "losing_pattern"]

    logger.info(
        "Mined %d insights (%d winning, %d losing) from %d outcomes",
        len(candidate_insights), len(winning), len(losing), len(points),
    )

    return {
        "mined": True,
        "samples": len(points),
        "total_insights": len(candidate_insights),
        "winning_count": len(winning),
        "losing_count": len(losing),
    }


def _build_summary(kind: str, features: dict, n: int, wr: float, avg_rr: float, expectancy: float) -> str:
    """Build a human-readable Arabic summary."""
    feature_strs = []
    if features.get("direction"):
        feature_strs.append(features["direction"].upper())
    if features.get("zone"):
        feature_strs.append(f"في {features['zone']}")
    if features.get("htf_bias"):
        feature_strs.append(f"مع HTF bias {features['htf_bias']}")
    if features.get("rr_band"):
        feature_strs.append(f"R:R {features['rr_band']}")
    if features.get("timeframe"):
        feature_strs.append(f"على {features['timeframe']}")

    feat_text = " · ".join(feature_strs) if feature_strs else "general"
    if kind == "winning_pattern":
        return (
            f"✅ نمط رابح: {feat_text} → "
            f"win rate {wr*100:.0f}% على {n} حالة، "
            f"متوسط R:R {avg_rr:.2f}, expectancy {expectancy:+.2f}R"
        )
    else:
        return (
            f"❌ نمط فاشل: {feat_text} → "
            f"win rate {wr*100:.0f}% على {n} حالة، "
            f"expectancy {expectancy:+.2f}R — تجنّبه"
        )


# ═══════════════════════════════════════════════════════════════════
#  Consumers — used by analysis_service
# ═══════════════════════════════════════════════════════════════════

async def get_active_winning_patterns(db: AsyncSession, limit: int = 5) -> List[LearnedInsight]:
    rows = (await db.execute(
        select(LearnedInsight)
        .where(and_(
            LearnedInsight.kind == "winning_pattern",
            LearnedInsight.is_active.is_(True),
        ))
        .order_by(LearnedInsight.expectancy.desc())
        .limit(limit)
    )).scalars().all()
    return list(rows)


async def get_active_losing_patterns(db: AsyncSession, limit: int = 10) -> List[dict]:
    rows = (await db.execute(
        select(LearnedInsight)
        .where(and_(
            LearnedInsight.kind == "losing_pattern",
            LearnedInsight.is_active.is_(True),
        ))
        .order_by(LearnedInsight.confidence.desc())
        .limit(limit)
    )).scalars().all()
    return [
        {
            "features": r.features,
            "win_rate": r.win_rate,
            "sample_size": r.sample_size,
            "expectancy": r.expectancy,
        }
        for r in rows
    ]


async def increment_prompt_use_counts(db: AsyncSession, insight_ids: List[str]) -> None:
    """Bump usage counter when an insight is injected into a prompt."""
    if not insight_ids:
        return
    from sqlalchemy import update
    await db.execute(
        update(LearnedInsight)
        .where(LearnedInsight.id.in_(insight_ids))
        .values(use_count_in_prompts=LearnedInsight.use_count_in_prompts + 1)
    )


async def format_winning_insights_for_prompt(db: AsyncSession, limit: int = 5) -> Tuple[Optional[str], List[str]]:
    """Return prompt-ready text + list of used insight IDs (for usage tracking)."""
    insights = await get_active_winning_patterns(db, limit=limit)
    if not insights:
        return None, []
    lines = ["", "# 🧠 LEARNED PATTERNS THAT WORK (mined from your historical closed trades)"]
    for ins in insights:
        lines.append(f"- {ins.summary_ar}")
    lines.append("# Use these as STRONG priors. Setups matching these patterns deserve higher conviction.")
    return "\n".join(lines), [ins.id for ins in insights]


async def get_insights_summary(db: AsyncSession) -> dict:
    """For the training dashboard — overview of what's been learned."""
    from sqlalchemy import func
    total = (await db.execute(select(func.count(LearnedInsight.id)))).scalar_one()
    winning = (await db.execute(
        select(func.count(LearnedInsight.id))
        .where(LearnedInsight.kind == "winning_pattern")
    )).scalar_one()
    losing = (await db.execute(
        select(func.count(LearnedInsight.id))
        .where(LearnedInsight.kind == "losing_pattern")
    )).scalar_one()
    last = (await db.execute(
        select(LearnedInsight.last_refreshed_at)
        .order_by(LearnedInsight.last_refreshed_at.desc())
        .limit(1)
    )).scalar_one_or_none()

    top_winning = (await db.execute(
        select(LearnedInsight)
        .where(and_(LearnedInsight.kind == "winning_pattern", LearnedInsight.is_active.is_(True)))
        .order_by(LearnedInsight.expectancy.desc())
        .limit(5)
    )).scalars().all()
    top_losing = (await db.execute(
        select(LearnedInsight)
        .where(and_(LearnedInsight.kind == "losing_pattern", LearnedInsight.is_active.is_(True)))
        .order_by(LearnedInsight.confidence.desc())
        .limit(5)
    )).scalars().all()

    return {
        "total": total, "winning": winning, "losing": losing,
        "last_refreshed_at": last.isoformat() if last else None,
        "top_winning": [
            {
                "summary": w.summary_ar, "features": w.features,
                "win_rate": w.win_rate, "expectancy": w.expectancy,
                "samples": w.sample_size,
            } for w in top_winning
        ],
        "top_losing": [
            {
                "summary": l.summary_ar, "features": l.features,
                "win_rate": l.win_rate, "expectancy": l.expectancy,
                "samples": l.sample_size,
            } for l in top_losing
        ],
    }
