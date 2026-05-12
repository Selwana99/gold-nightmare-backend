from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _uuid() -> str:
    return str(uuid4())


class AnalysisCredit(Base):
    __tablename__ = "analysis_credits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    telegram_username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    total_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
