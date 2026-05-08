"""Analysis model — single-user, no user_id field."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Float, Integer, Boolean, DateTime, JSON, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Chart info
    symbol: Mapped[str] = mapped_column(String(20), default="XAUUSD", nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    is_mtf: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    chart_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    primary_bias: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    trend_direction: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)

    # Source
    source: Mapped[str] = mapped_column(String(20), default="web", nullable=False)
    user_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Result
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    image_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    image_hashes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # AI metadata
    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Status
    status: Mapped[str] = mapped_column(String(20), default="completed", nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )

    __table_args__ = (
        Index("ix_analyses_created_status", "created_at", "status"),
    )

    def __repr__(self) -> str:
        return f"<Analysis {self.id} {self.symbol}/{self.timeframe}>"
