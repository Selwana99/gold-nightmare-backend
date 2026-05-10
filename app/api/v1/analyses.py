"""Analyses endpoints."""

import logging
from typing import Annotated, Optional, List
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_owner, require_app_access
from app.config import settings
from app.core.analyzer import AnalyzerError
from app.db.base import get_db
from app.models.analysis import Analysis
from app.models.analysis_quota import AnalysisQuota
from app.models.share_link import ShareLink
from app.schemas.analysis import (
    AnalysisResponse, AnalysisListResponse, AnalysisListItem, ShareLinkPublic,
)
from app.services.analysis_service import (
    perform_analysis, list_analyses, get_analysis, delete_analysis,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analyses", tags=["analyses"])
DAILY_SUBSCRIBER_ANALYSIS_LIMIT = 5


async def _check_subscriber_quota(db: AsyncSession, access_payload: dict) -> AnalysisQuota | None:
    if access_payload.get("role") != "subscriber":
        return None

    username = access_payload.get("telegram_username")
    if not username:
        raise HTTPException(401, "Invalid subscriber session")

    today = date.today()
    quota = await db.scalar(
        select(AnalysisQuota).where(
            AnalysisQuota.telegram_username == username,
            AnalysisQuota.quota_date == today,
        )
    )

    if quota is None:
        quota = AnalysisQuota(
            telegram_username=username,
            quota_date=today,
            used_count=0,
        )
        db.add(quota)
        await db.flush()

    if quota.used_count >= DAILY_SUBSCRIBER_ANALYSIS_LIMIT:
        raise HTTPException(
            429,
            f"Daily analysis limit reached ({DAILY_SUBSCRIBER_ANALYSIS_LIMIT}/day)",
        )

    return quota


@router.post("", response_model=AnalysisResponse, status_code=201)
async def create_analysis(
    access: Annotated[dict, Depends(require_app_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
    images: List[UploadFile] = File(..., description="1-4 chart images"),
    extra_context: Optional[str] = Form(None, max_length=1000),
    model_override: Optional[str] = Form(None),
):
    quota = await _check_subscriber_quota(db, access)

    if not images:
        raise HTTPException(400, "No images uploaded")
    if len(images) > settings.MAX_IMAGES_PER_ANALYSIS:
        raise HTTPException(400, f"Max images: {settings.MAX_IMAGES_PER_ANALYSIS}")

    images_bytes = []
    max_bytes = settings.MAX_UPLOAD_MB * 1024 * 1024
    for img in images:
        content = await img.read()
        if len(content) > max_bytes:
            raise HTTPException(413, f"Image too large (>{settings.MAX_UPLOAD_MB}MB)")
        if not content:
            raise HTTPException(400, "Empty file")
        images_bytes.append(content)

    try:
        analysis = await perform_analysis(
            db, images_bytes, extra_context, model_override, source="web",
        )
    except AnalyzerError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception("Analysis failed")
        raise HTTPException(500, f"Internal error: {e}")

    if quota is not None:
        quota.used_count += 1
        quota.updated_at = datetime.utcnow()
        await db.flush()

    return AnalysisResponse.model_validate(analysis)


@router.get("", response_model=AnalysisListResponse)
async def list_my_analyses(
    _: Annotated[dict, Depends(require_app_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = await list_analyses(db, page, page_size)
    list_items = []
    for a in items:
        setup_count = len((a.result_json or {}).get("setups", []))
        list_items.append(AnalysisListItem(
            id=a.id, symbol=a.symbol, timeframe=a.timeframe,
            is_mtf=a.is_mtf, chart_price=a.chart_price,
            primary_bias=a.primary_bias, trend_direction=a.trend_direction,
            setup_count=setup_count, cost_usd=a.cost_usd, created_at=a.created_at,
        ))
    return AnalysisListResponse(
        items=list_items, total=total, page=page, page_size=page_size,
    )


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_one(
    analysis_id: str,
    _: Annotated[dict, Depends(require_app_access)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    a = await get_analysis(db, analysis_id)
    if not a:
        raise HTTPException(404, "Analysis not found")
    return AnalysisResponse.model_validate(a)


@router.delete("/{analysis_id}", status_code=204)
async def delete_one(
    analysis_id: str,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    ok = await delete_analysis(db, analysis_id)
    if not ok:
        raise HTTPException(404, "Analysis not found")
    return None


@router.post("/{analysis_id}/share", response_model=ShareLinkPublic)
async def create_share_link(
    analysis_id: str,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    expires_in_days: int = Query(30, ge=0, le=365, description="0 = never expires"),
):
    if not settings.ENABLE_SHARE_LINKS:
        raise HTTPException(403, "Share links are disabled")
    a = await get_analysis(db, analysis_id)
    if not a:
        raise HTTPException(404, "Analysis not found")

    expires_at = datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None

    link = ShareLink(analysis_id=analysis_id, expires_at=expires_at)
    db.add(link)
    await db.flush()
    public_url = f"{settings.BASE_URL.rstrip('/')}/share/{link.token}"
    return ShareLinkPublic(
        token=link.token, public_url=public_url, is_active=link.is_active,
        view_count=link.view_count, expires_at=link.expires_at, created_at=link.created_at,
    )


@router.get("/{analysis_id}/pdf")
async def download_pdf(
    analysis_id: str,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not settings.ENABLE_PDF_EXPORT:
        raise HTTPException(403, "PDF export is disabled")
    a = await get_analysis(db, analysis_id)
    if not a:
        raise HTTPException(404, "Analysis not found")

    try:
        from app.services.pdf_service import build_pdf
        pdf_bytes = build_pdf(a)
    except RuntimeError as e:
        raise HTTPException(500, str(e))
    except Exception as e:
        logger.exception("PDF generation failed")
        raise HTTPException(500, f"PDF generation error: {e}")

    import io
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="analysis_{analysis_id[:8]}.pdf"'},
    )
