from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Progress(Base):
    __tablename__ = "progress"
    __table_args__ = (
        CheckConstraint("interval >= 1", name="ck_progress_interval"),
        CheckConstraint("ease_factor >= 1.3", name="ck_progress_ease_factor"),
        CheckConstraint("repetition >= 0", name="ck_progress_repetition"),
    )

    card_id: Mapped[int] = mapped_column(
        ForeignKey("cards.id", ondelete="CASCADE"), primary_key=True
    )
    q: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default=1)
    interval: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    ease_factor: Mapped[float] = mapped_column(Float, nullable=False, default=2.5)
    repetition: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_review: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    card = relationship("Card", back_populates="progress")
