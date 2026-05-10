"""Daily analysis quota tracking per subscriber."""

from datetime import date, datetime
from uuid import uuid4

from sqlalchemy import Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid4())


class AnalysisQuota(Base):
    """Tracks how many analyses a subscriber used on a specific day."""

    __tablename__ = "analysis_quotas"
    __table_args__ = (
        UniqueConstraint("telegram_username", "quota_date", name="uq_analysis_quota_user_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    telegram_username: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    quota_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
