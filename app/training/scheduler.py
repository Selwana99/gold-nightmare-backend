"""
Background scheduler — runs periodic training/maintenance jobs:
  - Outcome tracker (every 5 min)
  - Stats aggregation (every 30 min)
  - Daily cleanup (once per day)
  - Auto-train classifier weekly

Uses APScheduler (AsyncIO mode) — runs in same process as the FastAPI app.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class TrainingScheduler:
    """Wraps APScheduler with async support for our jobs."""

    def __init__(self):
        self.scheduler = None
        self.jobs_registered = []

    def start(self):
        try:
            from apscheduler.schedulers.asyncio import AsyncIOScheduler
            from apscheduler.triggers.interval import IntervalTrigger
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            logger.warning("APScheduler not installed — background jobs disabled")
            return

        self.scheduler = AsyncIOScheduler(timezone="UTC")

        # ─── Job 1: Outcome tracking (every 5 minutes) ───
        self.scheduler.add_job(
            self._safe_run_outcome_tracker,
            trigger=IntervalTrigger(minutes=5),
            id="outcome_tracker",
            name="Outcome tracker",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        # ─── Job 2: Auto-promote successful analyses to few-shot bank (hourly) ───
        self.scheduler.add_job(
            self._safe_run_auto_promote,
            trigger=IntervalTrigger(hours=1),
            id="auto_promote",
            name="Auto-promote quality examples",
            replace_existing=True,
            max_instances=1,
        )

        # ─── Job 3: Re-train ML classifier (daily at 03:00 UTC) ───
        self.scheduler.add_job(
            self._safe_run_classifier_training,
            trigger=CronTrigger(hour=3, minute=0),
            id="classifier_train",
            name="Daily classifier training",
            replace_existing=True,
            max_instances=1,
        )

        # ─── Job 4: Daily DB maintenance (04:00 UTC) ───
        self.scheduler.add_job(
            self._safe_run_maintenance,
            trigger=CronTrigger(hour=4, minute=0),
            id="db_maintenance",
            name="Daily DB maintenance",
            replace_existing=True,
            max_instances=1,
        )

        # ─── Job 5: Weekly pattern mining (Sunday 02:00 UTC) ───
        self.scheduler.add_job(
            self._safe_run_pattern_mining,
            trigger=CronTrigger(day_of_week="sun", hour=2, minute=0),
            id="pattern_mining",
            name="Weekly pattern mining",
            replace_existing=True,
            max_instances=1,
        )

        self.scheduler.start()
        logger.info("Training scheduler started with %d jobs", len(self.scheduler.get_jobs()))

    def stop(self):
        if self.scheduler:
            self.scheduler.shutdown(wait=False)
            logger.info("Training scheduler stopped")

    # ─── Job implementations (with error isolation) ───

    async def _safe_run_outcome_tracker(self):
        try:
            from app.training.outcome_tracker import check_all_active_outcomes
            result = await check_all_active_outcomes()
            logger.info("Outcome tracker: %s", result)
        except Exception:
            logger.exception("Outcome tracker job failed")

    async def _safe_run_auto_promote(self):
        try:
            from sqlalchemy import select, and_
            from app.db.base import AsyncSessionLocal
            from app.models.analysis_outcome import AnalysisOutcome
            from app.models.analysis import Analysis
            from app.models.few_shot_example import FewShotExample
            from app.training.few_shot import promote_analysis_to_example

            async with AsyncSessionLocal() as db:
                # Find recent successful outcomes not yet promoted
                result = await db.execute(
                    select(AnalysisOutcome, Analysis)
                    .join(Analysis, AnalysisOutcome.analysis_id == Analysis.id)
                    .where(and_(
                        AnalysisOutcome.status == "tp_full",
                        AnalysisOutcome.realized_rr >= 1.5,
                    ))
                    .limit(10)
                )
                rows = result.all()

                promoted_count = 0
                for outcome, analysis in rows:
                    # Check if already promoted
                    exists = await db.execute(
                        select(FewShotExample).where(FewShotExample.source_analysis_id == analysis.id)
                    )
                    if exists.scalar_one_or_none():
                        continue
                    await promote_analysis_to_example(
                        db, analysis,
                        realized_rr=outcome.realized_rr,
                        quality_score=min(10.0, 5.0 + outcome.realized_rr),
                    )
                    promoted_count += 1

                await db.commit()
                if promoted_count > 0:
                    logger.info("Auto-promoted %d analyses to few-shot bank", promoted_count)
        except Exception:
            logger.exception("Auto-promote job failed")

    async def _safe_run_classifier_training(self):
        try:
            from app.db.base import AsyncSessionLocal
            from app.training.pattern_classifier import train_classifier

            async with AsyncSessionLocal() as db:
                result = await train_classifier(db)
                logger.info("Daily classifier training: %s", result)
        except Exception:
            logger.exception("Classifier training job failed")


    async def _safe_run_pattern_mining(self):
        try:
            from app.db.base import AsyncSessionLocal
            from app.training.learning_loop import mine_patterns
            async with AsyncSessionLocal() as db:
                result = await mine_patterns(db)
                logger.info("Weekly pattern mining: %s", result)
        except Exception:
            logger.exception("Pattern mining job failed")

    async def _safe_run_maintenance(self):
        try:
            from sqlalchemy import select, delete, text
            from datetime import datetime, timedelta
            from app.db.base import AsyncSessionLocal
            from app.models.audit_log import AuditLog

            async with AsyncSessionLocal() as db:
                # Prune audit logs older than 90 days
                threshold = datetime.utcnow() - timedelta(days=90)
                result = await db.execute(
                    delete(AuditLog).where(AuditLog.created_at < threshold)
                )
                pruned = result.rowcount or 0
                await db.commit()
                logger.info("DB maintenance: pruned %d old audit logs", pruned)
        except Exception:
            logger.exception("DB maintenance job failed")


# Singleton
_scheduler: Optional[TrainingScheduler] = None


def get_scheduler() -> TrainingScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = TrainingScheduler()
    return _scheduler
