"""FewShotExample — curated high-quality analyses for in-context learning."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Float, ForeignKey, DateTime, Boolean, Integer, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class FewShotExample(Base):
    __tablename__ = "few_shot_examples"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    source_analysis_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("analyses.id", ondelete="SET NULL"), index=True, nullable=True,
    )

    symbol: Mapped[str] = mapped_column(String(20), default="XAUUSD", nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    market_regime: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)

    summary_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    full_result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    quality_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    realized_rr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    embedding_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    source_analysis = relationship("Analysis", lazy="joined")

    __table_args__ = (
        Index("ix_fewshot_active_score", "is_active", "quality_score"),
        Index("ix_fewshot_tf_regime", "timeframe", "market_regime"),
    )
