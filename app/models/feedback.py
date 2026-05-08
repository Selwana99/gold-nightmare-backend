"""Owner feedback on an analysis — used for training quality signal."""

from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import String, Integer, ForeignKey, DateTime, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base


class Feedback(Base):
    __tablename__ = "feedbacks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )

    accuracy_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    usefulness_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    bias_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    levels_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    setup_followed: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    setup_profitable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    comments: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_quality_example: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    analysis = relationship("Analysis", lazy="joined")
