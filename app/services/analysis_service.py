"""
Analysis service — orchestrates the full pipeline.

For each new analysis:
  1. Fetch real OHLC → OHLC engine → "OBJECTIVE PRE-ANALYSIS" text
  2. Pull active winning patterns → "LEARNED PATTERNS" text
  3. Lookup similar few-shot examples → "REFERENCE EXAMPLES" text
  4. Build enriched user_context (concatenation of above + user input)
  5. Call Claude
  6. Run validator (using OHLC + losing patterns) → drop bad setups
  7. Score remaining setups with ML classifier
  8. Persist analysis + auto-create outcome trackers
"""

import logging
from typing import Optional, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.analyzer import analyze_single_chart, analyze_mtf, AnalyzerError
from app.models.analysis import Analysis
from app.models.audit_log import AuditLog
from app.services.price_service import get_current_gold_price

logger = logging.getLogger(__name__)


async def _build_pre_analysis_block(symbol: str, timeframe: str) -> tuple[Optional[str], Optional[dict]]:
    try:
        from app.training.ohlc_engine import analyze_ohlc, format_for_prompt, to_dict
        ohlc = await analyze_ohlc(symbol=symbol, timeframe=timeframe, limit=300)
        if not ohlc:
            return None, None
        return format_for_prompt(ohlc), to_dict(ohlc)
    except Exception as e:
        logger.debug("OHLC engine skipped: %s", e)
        return None, None


async def _build_learned_insights_block(db: AsyncSession) -> tuple[Optional[str], List[str]]:
    try:
        from app.training.learning_loop import format_winning_insights_for_prompt
        return await format_winning_insights_for_prompt(db, limit=5)
    except Exception as e:
        logger.debug("Learned insights skipped: %s", e)
        return None, []


async def _build_few_shot_block(symbol: str, timeframe: str, user_context: Optional[str]) -> Optional[str]:
    if not settings.ENABLE_FEW_SHOT_LEARNING:
        return None
    try:
        from app.training.few_shot import find_similar_examples, format_examples_for_prompt
        examples = await find_similar_examples(
            symbol=symbol, timeframe=timeframe,
            context=user_context, k=3,
        )
        if examples:
            return format_examples_for_prompt(examples)
    except Exception as e:
        logger.debug("Few-shot skipped: %s", e)
    return None


async def _get_losing_patterns(db: AsyncSession) -> List[dict]:
    try:
        from app.training.learning_loop import get_active_losing_patterns
        return await get_active_losing_patterns(db, limit=10)
    except Exception:
        return []


async def perform_analysis(
    db: AsyncSession,
    images_bytes: List[bytes],
    extra_context: Optional[str] = None,
    model_override: Optional[str] = None,
    source: str = "web",
    actor: str = "owner",
    timeframe_hint: str = "H1",
) -> Analysis:
    """Run the full pipeline."""
    if not images_bytes:
        raise AnalyzerError("لم يتم رفع صور")
    if len(images_bytes) > settings.MAX_IMAGES_PER_ANALYSIS:
        raise AnalyzerError(f"عدد الصور الأقصى هو {settings.MAX_IMAGES_PER_ANALYSIS}")

    is_mtf = len(images_bytes) > 1
    market_price = await get_current_gold_price()

    # ─── Build enriched context (OHLC + insights + few-shot + user) ───
    pre_analysis_text, ohlc_dict = await _build_pre_analysis_block("XAUUSD", timeframe_hint)
    insights_text, insight_ids_used = await _build_learned_insights_block(db)
    fs_text = await _build_few_shot_block(
        symbol="XAUUSD", timeframe="MTF" if is_mtf else timeframe_hint, user_context=extra_context,
    )

    enriched_parts = []
    if pre_analysis_text:
        enriched_parts.append(pre_analysis_text)
    if insights_text:
        enriched_parts.append(insights_text)
    if fs_text:
        enriched_parts.append(fs_text)
    if extra_context:
        enriched_parts.append(f"\n# USER CONTEXT\n{extra_context}")
    enriched_context = "\n\n".join(enriched_parts) if enriched_parts else None

    # ─── Call Claude ───
    chosen_model = model_override or settings.CLAUDE_MODEL
    if is_mtf:
        result = analyze_mtf(images_bytes, enriched_context, chosen_model)
    else:
        result = analyze_single_chart(images_bytes[0], enriched_context, chosen_model)

    meta = result.pop("_meta", {})
    chart_meta = result.get("chart_meta", {})
    session_bias = result.get("session_bias", {})

    # ─── Validate setups (drop ones with critical issues) ───
    losing_patterns = await _get_losing_patterns(db)
    try:
        from app.training.validator import validate_analysis_result
        result = validate_analysis_result(
            result,
            ohlc_analysis=ohlc_dict,
            losing_patterns=losing_patterns,
            min_rr=1.0,
        )
    except Exception as e:
        logger.warning("Validator failed: %s", e)

    # ─── Persist ───
    analysis = Analysis(
        symbol=chart_meta.get("symbol", "XAUUSD"),
        timeframe=chart_meta.get("timeframe", timeframe_hint),
        is_mtf=is_mtf,
        chart_price=chart_meta.get("current_price"),
        market_price=market_price,
        primary_bias=session_bias.get("primary_bias"),
        trend_direction=chart_meta.get("trend_direction"),
        source=source,
        user_context=extra_context,
        result_json=result,
        image_count=meta.get("image_count", len(images_bytes)),
        image_hashes=meta.get("image_hashes"),
        model_used=meta.get("model", chosen_model),
        input_tokens=meta.get("input_tokens", 0),
        output_tokens=meta.get("output_tokens", 0),
        cost_usd=meta.get("cost_usd"),
        duration_ms=meta.get("duration_ms", 0),
        status="completed",
    )
    db.add(analysis)
    await db.flush()

    # Track which insights were used
    if insight_ids_used:
        try:
            from app.training.learning_loop import increment_prompt_use_counts
            await increment_prompt_use_counts(db, insight_ids_used)
        except Exception:
            pass

    # Auto-create outcomes (only for kept setups)
    try:
        from app.training.outcome_tracker import create_outcomes_from_analysis
        await create_outcomes_from_analysis(db, analysis)
    except Exception as e:
        logger.warning("Failed to auto-create outcomes: %s", e)

    # ML scoring
    if settings.ENABLE_ML_CLASSIFIER:
        try:
            from app.training.pattern_classifier import predict_setup_quality
            for setup in result.get("setups", []):
                score = predict_setup_quality(analysis, setup)
                if score is not None:
                    setup["ml_quality_score"] = round(float(score), 3)
            analysis.result_json = result
        except Exception as e:
            logger.debug("ML scoring skipped: %s", e)

    # Audit
    val_summary = result.get("validation_summary", {})
    db.add(AuditLog(
        actor=actor, action="analysis_created",
        target_type="analysis", target_id=analysis.id,
        metadata_json={
            "symbol": analysis.symbol, "timeframe": analysis.timeframe,
            "is_mtf": is_mtf, "model": analysis.model_used,
            "tokens": analysis.input_tokens + analysis.output_tokens,
            "cost_usd": analysis.cost_usd, "source": source,
            "ohlc_used": bool(pre_analysis_text),
            "insights_used": len(insight_ids_used),
            "few_shot_used": bool(fs_text),
            "setups_kept": val_summary.get("kept", 0),
            "setups_rejected": val_summary.get("rejected", 0),
        },
    ))

    await db.flush()
    logger.info(
        "Analysis %s · cost=$%.4f · ohlc=%s insights=%d fs=%s · kept=%d rejected=%d",
        analysis.id, analysis.cost_usd or 0,
        bool(pre_analysis_text), len(insight_ids_used), bool(fs_text),
        val_summary.get("kept", 0), val_summary.get("rejected", 0),
    )
    return analysis


async def list_analyses(db: AsyncSession, page: int = 1, page_size: int = 20) -> tuple[list, int]:
    query = (
        select(Analysis).order_by(Analysis.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )
    items = (await db.execute(query)).scalars().all()
    total = (await db.execute(select(func.count(Analysis.id)))).scalar_one()
    return list(items), total


async def get_analysis(db: AsyncSession, analysis_id: str) -> Optional[Analysis]:
    return (await db.execute(
        select(Analysis).where(Analysis.id == analysis_id)
    )).scalar_one_or_none()


async def delete_analysis(db: AsyncSession, analysis_id: str) -> bool:
    analysis = await get_analysis(db, analysis_id)
    if not analysis:
        return False
    await db.delete(analysis)
    db.add(AuditLog(actor="owner", action="analysis_deleted",
                    target_type="analysis", target_id=analysis_id))
    await db.flush()
    return True
