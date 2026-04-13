"""Audit log model for DPDPA compliance — tracks who did what, when."""

import enum
import uuid
from typing import Optional

from sqlalchemy import String, ForeignKey, Index, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from db.database import Base, TimestampMixin
from db.models.core import Uuid


class AuditAction(str, enum.Enum):
    LOGIN = "login"
    DOCUMENT_UPLOAD = "document_upload"
    DOCUMENT_DELETE = "document_delete"
    AUDIT_RUN = "audit_run"
    NOTICE_UPLOAD = "notice_upload"
    DATA_EXPORT = "data_export"
    DATA_DELETE = "data_delete"
    PROFILE_UPDATE = "profile_update"
    CONSENT_UPDATE = "consent_update"
    PASSWORD_CHANGE = "password_change"


class AuditLog(Base, TimestampMixin):
    """Immutable audit trail for DPDPA compliance and enterprise security."""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    user: Mapped["User"] = relationship("User")
