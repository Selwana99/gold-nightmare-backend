"""Training endpoints — single-user; all require owner auth."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_owner
from app.config import settings
from app.db.base import get_db
from app.models.analysis import Analysis
from app.models.analysis_outcome import AnalysisOutcome
from app.models.feedback import Feedback
from app.models.few_shot_example import FewShotExample
from app.models.backtest_run import BacktestRun
from app.models.audit_log import AuditLog
from app.schemas.training import (
    FeedbackCreate, FeedbackPublic,
    OutcomePublic,
    BacktestCreate, BacktestPublic,
    FewShotPublic, FewShotPromote,
    TrainingStats,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/training", tags=["training"])


# ═══════════════════════════════════════════════════════════════
#  Feedback (owner provides feedback to train the system)
# ═══════════════════════════════════════════════════════════════

@router.post("/feedback/{analysis_id}", response_model=FeedbackPublic, status_code=201)
async def submit_feedback(
    analysis_id: str,
    body: FeedbackCreate,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    a = (await db.execute(select(Analysis).where(Analysis.id == analysis_id))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "التحليل غير موجود")

    # Upsert
    existing = (await db.execute(
        select(Feedback).where(Feedback.analysis_id == analysis_id)
    )).scalar_one_or_none()

    if existing:
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(existing, k, v)
        feedback = existing
    else:
        feedback = Feedback(analysis_id=analysis_id, **body.model_dump(exclude_none=True))
        db.add(feedback)

    db.add(AuditLog(
        actor="owner", action="feedback_submitted",
        target_type="analysis", target_id=analysis_id,
        metadata_json=body.model_dump(exclude_none=True),
    ))
    await db.flush()
    return FeedbackPublic.model_validate(feedback)


# ═══════════════════════════════════════════════════════════════
#  Outcomes
# ═══════════════════════════════════════════════════════════════

@router.get("/outcomes/{analysis_id}", response_model=list[OutcomePublic])
async def outcomes_for_analysis(
    analysis_id: str,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    rows = (await db.execute(
        select(AnalysisOutcome)
        .where(AnalysisOutcome.analysis_id == analysis_id)
        .order_by(AnalysisOutcome.setup_index)
    )).scalars().all()
    return [OutcomePublic.model_validate(r) for r in rows]


@router.post("/outcomes/check_now")
async def trigger_outcome_check(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Manually trigger an outcome-tracker pass."""
    from app.training.outcome_tracker import check_all_active_outcomes
    result = await check_all_active_outcomes(db)
    db.add(AuditLog(actor="owner", action="outcome_tracker_manual", metadata_json=result))
    return result


# ═══════════════════════════════════════════════════════════════
#  Stats / Dashboard
# ═══════════════════════════════════════════════════════════════

@router.get("/stats", response_model=TrainingStats)
async def get_training_stats(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.training.stats import gather_training_stats
    return TrainingStats(**(await gather_training_stats(db)))


# ═══════════════════════════════════════════════════════════════
#  Few-shot
# ═══════════════════════════════════════════════════════════════

@router.get("/few_shot", response_model=list[FewShotPublic])
async def list_few_shot(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    only_active: bool = False,
    limit: int = Query(50, ge=1, le=500),
):
    query = select(FewShotExample).order_by(FewShotExample.quality_score.desc()).limit(limit)
    if only_active:
        query = query.where(FewShotExample.is_active.is_(True))
    rows = (await db.execute(query)).scalars().all()
    return [FewShotPublic.model_validate(r) for r in rows]


@router.post("/few_shot/promote", response_model=FewShotPublic)
async def promote_to_few_shot(
    body: FewShotPromote,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    a = (await db.execute(select(Analysis).where(Analysis.id == body.analysis_id))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "التحليل غير موجود")
    from app.training.few_shot import promote_analysis_to_example
    example = await promote_analysis_to_example(
        db, a, market_regime=body.market_regime,
        realized_rr=body.realized_rr, quality_score=body.quality_score,
    )
    db.add(AuditLog(actor="owner", action="few_shot_promoted",
                    target_type="analysis", target_id=a.id,
                    metadata_json={"quality_score": body.quality_score}))
    return FewShotPublic.model_validate(example)


@router.delete("/few_shot/{example_id}", status_code=204)
async def delete_few_shot(
    example_id: str,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ex = (await db.execute(
        select(FewShotExample).where(FewShotExample.id == example_id)
    )).scalar_one_or_none()
    if not ex:
        raise HTTPException(404, "Example not found")
    ex.is_active = False
    db.add(AuditLog(actor="owner", action="few_shot_deleted",
                    target_type="few_shot_example", target_id=example_id))


# ═══════════════════════════════════════════════════════════════
#  ML Classifier
# ═══════════════════════════════════════════════════════════════

@router.post("/classifier/train")
async def train_classifier_endpoint(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    from app.training.pattern_classifier import train_classifier
    result = await train_classifier(db)
    db.add(AuditLog(actor="owner", action="classifier_trained", metadata_json=result))
    return result


@router.get("/classifier/info")
async def classifier_info(_: Annotated[str, Depends(require_owner)]):
    from app.training.pattern_classifier import get_classifier_info
    return get_classifier_info()


# ═══════════════════════════════════════════════════════════════
#  Backtest
# ═══════════════════════════════════════════════════════════════

@router.post("/backtest/run", response_model=BacktestPublic, status_code=201)
async def start_backtest(
    body: BacktestCreate,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    background: BackgroundTasks,
):
    run = BacktestRun(
        name=body.name, symbol=body.symbol, timeframe=body.timeframe,
        start_date=body.start_date, end_date=body.end_date,
        model_used=body.model_used or settings.CLAUDE_MODEL,
        notes=body.notes, status="pending",
    )
    db.add(run)
    await db.flush()
    run_id = run.id
    sample = body.sample_size

    db.add(AuditLog(
        actor="owner", action="backtest_started",
        target_type="backtest", target_id=run_id,
        metadata_json=body.model_dump(),
    ))

    async def _run():
        from app.db.base import AsyncSessionLocal
        from app.training.backtest import run_backtest as do_run
        async with AsyncSessionLocal() as session:
            run_obj = (await session.execute(
                select(BacktestRun).where(BacktestRun.id == run_id)
            )).scalar_one()
            try:
                await do_run(session, run_obj, sample_size=sample)
            except Exception:
                logger.exception("Backtest %s failed", run_id)

    background.add_task(_run)
    return BacktestPublic.model_validate(run)


@router.get("/backtest", response_model=list[BacktestPublic])
async def list_backtests(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
):
    rows = (await db.execute(
        select(BacktestRun).order_by(BacktestRun.started_at.desc()).limit(limit)
    )).scalars().all()
    return [BacktestPublic.model_validate(r) for r in rows]


@router.get("/backtest/{run_id}")
async def get_backtest(
    run_id: str,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    run = (await db.execute(
        select(BacktestRun).where(BacktestRun.id == run_id)
    )).scalar_one_or_none()
    if not run:
        raise HTTPException(404, "Backtest not found")
    return {
        **BacktestPublic.model_validate(run).model_dump(),
        "detailed_results": run.detailed_results,
        "notes": run.notes,
    }


# ═══════════════════════════════════════════════════════════════
#  Dataset export
# ═══════════════════════════════════════════════════════════════

@router.post("/dataset/export_quality")
async def export_quality_dataset(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    min_rr: float = Query(1.5, ge=0.5),
    min_rating: int = Query(4, ge=1, le=5),
):
    from app.training.dataset_builder import export_quality_examples
    out_path = f"./data/exports/quality_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl"
    result = await export_quality_examples(db, out_path, min_rr, min_rating)
    db.add(AuditLog(actor="owner", action="dataset_exported", metadata_json=result))
    return result


@router.post("/dataset/export_training")
async def export_training_dataset(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(1000, ge=1, le=10000),
):
    from app.training.dataset_builder import export_training_jsonl
    out_path = f"./data/exports/training_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.jsonl"
    result = await export_training_jsonl(db, out_path, limit)
    db.add(AuditLog(actor="owner", action="dataset_exported", metadata_json=result))
    return result


@router.get("/dataset/download/{filename}")
async def download_export(
    filename: str,
    _: Annotated[str, Depends(require_owner)],
):
    safe = "".join(c for c in filename if c.isalnum() or c in "._-")
    path = Path("./data/exports") / safe
    if not path.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(path, filename=safe, media_type="application/x-jsonlines")


# ═══════════════════════════════════════════════════════════════
#  Learning Loop — pattern mining
# ═══════════════════════════════════════════════════════════════

@router.post("/insights/refresh")
async def refresh_insights(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    min_samples: int = Query(5, ge=2, le=100),
    win_threshold: float = Query(0.65, ge=0.5, le=1.0),
    loss_threshold: float = Query(0.35, ge=0.0, le=0.5),
):
    """Re-mine winning + losing patterns from closed outcomes."""
    from app.training.learning_loop import mine_patterns
    result = await mine_patterns(
        db, min_samples=min_samples,
        win_threshold=win_threshold, loss_threshold=loss_threshold,
    )
    db.add(AuditLog(actor="owner", action="insights_refreshed", metadata_json=result))
    return result


@router.get("/insights")
async def get_insights(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Summary of currently active learned patterns."""
    from app.training.learning_loop import get_insights_summary
    return await get_insights_summary(db)


# ═══════════════════════════════════════════════════════════════
#  OHLC Engine — programmatic pre-analysis
# ═══════════════════════════════════════════════════════════════

@router.get("/ohlc/snapshot")
async def ohlc_snapshot(
    _: Annotated[str, Depends(require_owner)],
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("H1"),
    limit: int = Query(300, ge=50, le=1000),
):
    """Run the OHLC engine on demand and return its raw output."""
    from app.training.ohlc_engine import analyze_ohlc, format_for_prompt, to_dict
    result = await analyze_ohlc(symbol=symbol, timeframe=timeframe, limit=limit)
    if not result:
        raise HTTPException(503, "OHLC engine unavailable (TWELVEDATA_KEY not set or fetch failed)")
    return {
        "raw": to_dict(result),
        "formatted_prompt": format_for_prompt(result),
    }


# ═══════════════════════════════════════════════════════════════
#  Validator — re-run on existing analysis
# ═══════════════════════════════════════════════════════════════

@router.post("/validator/recheck/{analysis_id}")
async def recheck_analysis(
    analysis_id: str,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Re-run validator on a stored analysis (does not modify the DB record)."""
    a = (await db.execute(select(Analysis).where(Analysis.id == analysis_id))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "التحليل غير موجود")

    from app.training.validator import validate_analysis_result
    from app.training.learning_loop import get_active_losing_patterns
    losing = await get_active_losing_patterns(db, limit=10)
    # We don't have OHLC for past analyses unless we re-fetch — skip for recheck
    rechecked = validate_analysis_result(
        dict(a.result_json or {}),
        ohlc_analysis=None,
        losing_patterns=losing,
        min_rr=1.0,
    )
    return rechecked.get("validation_summary", {})
