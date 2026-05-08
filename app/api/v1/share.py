"""Public share endpoints — read-only access to shared analyses by token."""

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import get_db
from app.models.share_link import ShareLink

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/share", tags=["share"])


@router.get("/{token}/data")
async def get_shared_analysis(
    token: str,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Public — return analysis JSON by share token."""
    if not settings.ENABLE_SHARE_LINKS:
        raise HTTPException(403, "Share links are disabled")

    link = (await db.execute(
        select(ShareLink).where(ShareLink.token == token)
    )).scalar_one_or_none()

    if not link or not link.is_valid:
        raise HTTPException(404, "Share link not found or expired")

    link.view_count += 1
    link.last_accessed_at = datetime.utcnow()
    await db.flush()

    a = link.analysis
    return {
        "id": a.id,
        "symbol": a.symbol,
        "timeframe": a.timeframe,
        "is_mtf": a.is_mtf,
        "chart_price": a.chart_price,
        "primary_bias": a.primary_bias,
        "result_json": a.result_json,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "view_count": link.view_count,
    }
