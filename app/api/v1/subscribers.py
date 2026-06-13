"""Subscriber management and app session endpoints."""

from datetime import date, datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_owner
from app.config import settings
from app.core.security import create_subscriber_token
from app.db.base import get_db
from app.models.analysis_credit import AnalysisCredit
from app.models.analysis_quota import AnalysisQuota
from app.models.subscriber import Subscriber

router = APIRouter(prefix="/subscribers", tags=["subscribers"])


def normalize_username(username: str) -> str:
    username = (username or "").strip().lower()
    if username.startswith("@"):
        username = username[1:]
    if not username:
        raise HTTPException(400, "Telegram username is required")
    return username


class SubscriberCreate(BaseModel):
    telegram_username: str = Field(..., min_length=2, max_length=64)
    notes: Optional[str] = None


class SubscriberUpdate(BaseModel):
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    reset_device: bool = False


class SubscriberCreditRequest(BaseModel):
    telegram_username: str = Field(..., min_length=2, max_length=64)
    total_limit: int = Field(..., ge=1, le=100000)
    reset_used: bool = True


class SubscriberCreditOut(BaseModel):
    telegram_username: str
    total_limit: int
    used_count: int
    remaining: int
    is_active: bool


class SubscriberSessionRequest(BaseModel):
    telegram_username: str = Field(..., min_length=2, max_length=64)
    device_id: str = Field(..., min_length=8, max_length=128)


class SubscriberSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    telegram_username: str


class SubscriberOut(BaseModel):
    id: str
    telegram_username: str
    device_id: Optional[str]
    is_active: bool
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    last_seen_at: Optional[datetime]

    model_config = {"from_attributes": True}


@router.post("/session", response_model=SubscriberSessionResponse)
async def create_subscriber_session(
    body: SubscriberSessionRequest,
    response: Response,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    username = normalize_username(body.telegram_username)
    device_id = body.device_id.strip()

    sub = await db.scalar(select(Subscriber).where(Subscriber.telegram_username == username))
    if not sub or not sub.is_active:
        raise HTTPException(403, "Subscriber is not active")

    if sub.device_id and sub.device_id != device_id:
        raise HTTPException(403, "Subscriber is already linked to another device")

    if not sub.device_id:
        sub.device_id = device_id
    sub.last_seen_at = datetime.utcnow()
    await db.flush()

    token = create_subscriber_token(username=username, device_id=device_id)
    is_secure = request.url.scheme == "https" or settings.APP_ENV == "production"
    response.set_cookie(
        key="gn_session",
        value=token,
        httponly=True,
        secure=is_secure,
        samesite="lax",
        max_age=settings.JWT_EXPIRE_MINUTES * 60,
        path="/",
    )
    return SubscriberSessionResponse(
        access_token=token,
        expires_in_minutes=settings.JWT_EXPIRE_MINUTES,
        telegram_username=username,
    )


@router.get("", response_model=list[SubscriberOut])
async def list_subscribers(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Subscriber).order_by(Subscriber.created_at.desc()))
    return list(result.scalars().all())


@router.get("/usage/daily")
async def list_daily_usage(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
    day: Optional[date] = Query(default=None),
):
    if day is None:
        day = date.today()

    subs = list((await db.execute(
        select(Subscriber).order_by(Subscriber.telegram_username.asc())
    )).scalars().all())

    quotas = list((await db.execute(
        select(AnalysisQuota).where(AnalysisQuota.quota_date == day)
    )).scalars().all())

    credits = list((await db.execute(select(AnalysisCredit))).scalars().all())

    quota_by_user = {str(q.telegram_username): int(q.used_count or 0) for q in quotas}
    credit_by_user = {str(c.telegram_username): c for c in credits}

    items = []
    for sub in subs:
        username = str(sub.telegram_username)
        used_today = int(quota_by_user.get(username, 0) or 0)
        credit = credit_by_user.get(username)

        total_limit = int(credit.total_limit) if credit else None
        total_used = int(credit.used_count or 0) if credit else 0
        total_remaining = max(total_limit - total_used, 0) if total_limit is not None else None
        daily_limit = total_limit if total_limit is not None else 5

        items.append({
            "telegram_username": username,
            "is_active": bool(sub.is_active),
            "used_today": used_today,
            "daily_limit": int(daily_limit),
            "remaining_today": max(int(daily_limit) - used_today, 0),
            "total_limit": total_limit,
            "total_used": total_used,
            "total_remaining": total_remaining,
            "device_linked": bool(sub.device_id),
            "last_seen_at": sub.last_seen_at.isoformat() if sub.last_seen_at else None,
        })

    return items


@router.post("/credits", response_model=SubscriberCreditOut)
async def set_subscriber_credits(
    body: SubscriberCreditRequest,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    username = normalize_username(body.telegram_username)

    sub = await db.scalar(select(Subscriber).where(Subscriber.telegram_username == username))
    if sub:
        sub.is_active = True
    else:
        sub = Subscriber(telegram_username=username, notes="credit package", is_active=True)
        db.add(sub)
        await db.flush()

    credit = await db.scalar(select(AnalysisCredit).where(AnalysisCredit.telegram_username == username))
    if credit:
        credit.total_limit = body.total_limit
        if body.reset_used:
            credit.used_count = 0
        credit.updated_at = datetime.utcnow()
    else:
        credit = AnalysisCredit(
            telegram_username=username,
            total_limit=body.total_limit,
            used_count=0,
        )
        db.add(credit)

    await db.flush()
    return SubscriberCreditOut(
        telegram_username=username,
        total_limit=credit.total_limit,
        used_count=credit.used_count,
        remaining=max(credit.total_limit - credit.used_count, 0),
        is_active=sub.is_active,
    )


@router.post("", response_model=SubscriberOut, status_code=201)
async def add_subscriber(
    body: SubscriberCreate,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    username = normalize_username(body.telegram_username)
    existing = await db.scalar(select(Subscriber).where(Subscriber.telegram_username == username))
    if existing:
        existing.is_active = True
        existing.notes = body.notes or existing.notes
        await db.flush()
        return existing

    sub = Subscriber(telegram_username=username, notes=body.notes, is_active=True)
    db.add(sub)
    await db.flush()
    return sub


@router.patch("/{subscriber_id}", response_model=SubscriberOut)
async def update_subscriber(
    subscriber_id: str,
    body: SubscriberUpdate,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub = await db.get(Subscriber, subscriber_id)
    if not sub:
        raise HTTPException(404, "Subscriber not found")

    if body.is_active is not None:
        sub.is_active = body.is_active
    if body.notes is not None:
        sub.notes = body.notes
    if body.reset_device:
        sub.device_id = None
    await db.flush()
    return sub


@router.delete("/{subscriber_id}", status_code=204)
async def delete_subscriber(
    subscriber_id: str,
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub = await db.get(Subscriber, subscriber_id)
    if not sub:
        raise HTTPException(404, "Subscriber not found")
    await db.delete(sub)
    return None
