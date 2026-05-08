"""AnalysisOutcome — tracks setup execution against live price."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Float, Integer, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class AnalysisOutcome(Base):
    __tablename__ = "analysis_outcomes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    setup_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    setup_label: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)

    # Snapshot
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    tp_levels: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    expected_rr: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    chart_price_at_creation: Mapped[float] = mapped_column(Float, nullable=False)

    # Live
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    entry_filled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entry_filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    final_close_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_rr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    realized_pnl_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    tp1_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tp2_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tp3_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tp4_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sl_hit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    max_favorable_excursion: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max_adverse_excursion: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_checked_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    check_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    analysis = relationship("Analysis", lazy="joined")

    __table_args__ = (Index("ix_outcomes_status_active", "status", "is_active"),)
