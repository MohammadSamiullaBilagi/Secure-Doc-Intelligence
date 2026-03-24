import uuid
from typing import Optional, List
from datetime import datetime

from sqlalchemy import String, Text, ForeignKey, JSON, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base, TimestampMixin


class NoticeJob(Base, TimestampMixin):
    """Tracks a notice reply processing job."""
    __tablename__ = "notice_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    notice_type: Mapped[str] = mapped_column(String(50), nullable=False)
    notice_document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    supporting_documents: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True, default=list)
    status: Mapped[str] = mapped_column(String(50), default="uploaded")
    langgraph_thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    extracted_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    draft_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    final_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="notice_jobs")
    client: Mapped[Optional["Client"]] = relationship("Client")
