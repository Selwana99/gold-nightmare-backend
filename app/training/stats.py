"""Aggregate training statistics — for the admin dashboard."""

import logging
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_outcome import AnalysisOutcome
from app.models.feedback import Feedback
from app.models.few_shot_example import FewShotExample
from app.models.analysis import Analysis
from app.training.pattern_classifier import get_classifier_info
from app.training.few_shot import get_index_stats

logger = logging.getLogger(__name__)


async def gather_training_stats(db: AsyncSession) -> dict:
    """Big aggregation query for the training dashboard."""

    # Outcomes
    total_outcomes = (await db.execute(select(func.count(AnalysisOutcome.id)))).scalar_one()
    active_outcomes = (await db.execute(
        select(func.count(AnalysisOutcome.id)).where(AnalysisOutcome.is_active.is_(True))
    )).scalar_one()
    closed_outcomes = total_outcomes - active_outcomes

    # Win rate (only closed)
    wins = (await db.execute(
        select(func.count(AnalysisOutcome.id)).where(AnalysisOutcome.status == "tp_full")
    )).scalar_one()
    losses = (await db.execute(
        select(func.count(AnalysisOutcome.id)).where(AnalysisOutcome.status == "sl_hit")
    )).scalar_one()
    win_rate = wins / (wins + losses) if (wins + losses) > 0 else None

    # Avg realized R:R
    avg_rr = (await db.execute(
        select(func.avg(AnalysisOutcome.realized_rr))
        .where(and_(
            AnalysisOutcome.is_active.is_(False),
            AnalysisOutcome.realized_rr.isnot(None),
        ))
    )).scalar_one()

    # By status
    status_rows = (await db.execute(
        select(AnalysisOutcome.status, func.count(AnalysisOutcome.id))
        .group_by(AnalysisOutcome.status)
    )).all()
    by_status = {s: c for s, c in status_rows}

    # By direction
    dir_rows = (await db.execute(
        select(AnalysisOutcome.direction, func.count(AnalysisOutcome.id))
        .where(AnalysisOutcome.is_active.is_(False))
        .group_by(AnalysisOutcome.direction)
    )).all()
    by_direction = {d: c for d, c in dir_rows}

    # By timeframe (joined with analysis)
    tf_rows = (await db.execute(
        select(Analysis.timeframe, func.count(AnalysisOutcome.id))
        .join(AnalysisOutcome, AnalysisOutcome.analysis_id == Analysis.id)
        .where(AnalysisOutcome.is_active.is_(False))
        .group_by(Analysis.timeframe)
    )).all()
    by_timeframe = {tf: c for tf, c in tf_rows}

    # Feedback
    feedback_count = (await db.execute(select(func.count(Feedback.id)))).scalar_one()
    avg_acc = (await db.execute(
        select(func.avg(Feedback.accuracy_rating))
        .where(Feedback.accuracy_rating.isnot(None))
    )).scalar_one()
    avg_use = (await db.execute(
        select(func.avg(Feedback.usefulness_rating))
        .where(Feedback.usefulness_rating.isnot(None))
    )).scalar_one()

    # Few-shot
    fs_active = (await db.execute(
        select(func.count(FewShotExample.id)).where(FewShotExample.is_active.is_(True))
    )).scalar_one()
    fs_total_uses = (await db.execute(
        select(func.coalesce(func.sum(FewShotExample.use_count), 0))
    )).scalar_one()

    # Classifier
    clf = get_classifier_info()

    return {
        "total_outcomes": total_outcomes,
        "outcomes_active": active_outcomes,
        "outcomes_closed": closed_outcomes,
        "wins": wins,
        "losses": losses,
        "overall_win_rate": float(win_rate) if win_rate else None,
        "avg_realized_rr": float(avg_rr) if avg_rr else None,

        "feedback_count": feedback_count,
        "avg_accuracy_rating": float(avg_acc) if avg_acc else None,
        "avg_usefulness_rating": float(avg_use) if avg_use else None,

        "by_timeframe": by_timeframe,
        "by_direction": by_direction,
        "by_status": by_status,

        "few_shot_count_active": fs_active,
        "few_shot_total_uses": int(fs_total_uses or 0),

        "classifier_trained": clf.get("trained", False),
        "classifier_accuracy": clf.get("test_accuracy"),
        "classifier_trained_at": clf.get("trained_at"),
        "classifier_samples": clf.get("samples", 0),

        "vector_store": get_index_stats(),
    }
