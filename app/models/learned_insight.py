"""LearnedInsight — patterns mined from closed outcomes."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Float, Integer, Boolean, DateTime, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class LearnedInsight(Base):
    __tablename__ = "learned_insights"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    # Classification
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # winning_pattern | losing_pattern | rule | observation

    # The feature signature that defines this pattern
    # e.g. {"direction": "buy", "zone": "discount", "htf_bias": "bullish", "rr_band": "mid"}
    features: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Outcome stats
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    win_rate: Mapped[float] = mapped_column(Float, nullable=False)
    avg_realized_rr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    expectancy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # expectancy = (win_rate * avg_win_R) - ((1-win_rate) * avg_loss_R)

    # Confidence (statistical significance proxy)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Human-readable Arabic summary
    summary_ar: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Lifecycle
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_count_in_prompts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    use_count_in_validator: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )
    last_refreshed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_insights_kind_active", "kind", "is_active"),
    )
