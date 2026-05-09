"""Subscriber management endpoints."""

from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_owner
from app.db.base import get_db
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


@router.get("", response_model=list[SubscriberOut])
async def list_subscribers(
    _: Annotated[str, Depends(require_owner)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(select(Subscriber).order_by(Subscriber.created_at.desc()))
    return list(result.scalars().all())


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
