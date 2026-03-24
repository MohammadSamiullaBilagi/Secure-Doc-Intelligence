import uuid
from typing import Optional
from datetime import date, datetime

from sqlalchemy import String, Integer, Boolean, Date, DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base, TimestampMixin


class TaxDeadline(Base, TimestampMixin):
    """A tax filing deadline (system-seeded or user-created)."""
    __tablename__ = "tax_deadlines"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False)  # GST, Income Tax, TDS, Advance Tax
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    reminders: Mapped[list["UserReminder"]] = relationship(
        "UserReminder", back_populates="deadline", cascade="all, delete-orphan"
    )


class UserReminder(Base, TimestampMixin):
    """A user's reminder subscription for a specific tax deadline."""
    __tablename__ = "user_reminders"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    deadline_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tax_deadlines.id", ondelete="CASCADE")
    )
    remind_days_before: Mapped[int] = mapped_column(Integer, default=3)
    channel: Mapped[str] = mapped_column(String(50), default="email")  # email | whatsapp
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
    deadline: Mapped["TaxDeadline"] = relationship("TaxDeadline", back_populates="reminders")
