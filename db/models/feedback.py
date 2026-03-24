import uuid
from typing import Optional

from sqlalchemy import String, Text, Uuid, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base, TimestampMixin


class Feedback(Base, TimestampMixin):
    """User feedback — feature requests, bug reports, and general feedback."""
    __tablename__ = "feedbacks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # "feature_request", "bug_report", "general"
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    page: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )  # which page the feedback was submitted from

    # Relationships
    user: Mapped["User"] = relationship("User")
