"""Owner dashboard — overall account stats."""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_owner
from app.db.base import get_db
from app.models.analysis import Analysis
from app.schemas.training import DashboardStats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def dashboard_stats(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    total = (await db.execute(select(func.count(Analysis.id)))).scalar_one()
    total_cost = (await db.execute(
        select(func.coalesce(func.sum(Analysis.cost_usd), 0))
    )).scalar_one()

    now = datetime.utcnow()
    month_start = datetime(now.year, now.month, 1)

    month_count = (await db.execute(
        select(func.count(Analysis.id)).where(Analysis.created_at >= month_start)
    )).scalar_one()
    month_cost = (await db.execute(
        select(func.coalesce(func.sum(Analysis.cost_usd), 0))
        .where(Analysis.created_at >= month_start)
    )).scalar_one()

    by_tf = dict((await db.execute(
        select(Analysis.timeframe, func.count(Analysis.id))
        .group_by(Analysis.timeframe)
    )).all())

    by_bias = dict((await db.execute(
        select(Analysis.primary_bias, func.count(Analysis.id))
        .where(Analysis.primary_bias.isnot(None))
        .group_by(Analysis.primary_bias)
    )).all())

    last = (await db.execute(
        select(Analysis.created_at).order_by(Analysis.created_at.desc()).limit(1)
    )).scalar_one_or_none()

    return DashboardStats(
        total_analyses=total,
        total_cost_usd=float(total_cost or 0),
        analyses_this_month=month_count,
        cost_this_month=float(month_cost or 0),
        by_timeframe=by_tf,
        by_bias=by_bias,
        last_analysis_at=last,
    )
