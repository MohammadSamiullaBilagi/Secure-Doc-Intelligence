import uuid
from typing import Optional, List
from datetime import datetime

from sqlalchemy import String, ForeignKey, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base, TimestampMixin


class Client(Base, TimestampMixin):
    """A client managed by a CA (Chartered Accountant) user."""
    __tablename__ = "clients"
    __table_args__ = (
        UniqueConstraint("ca_user_id", "name", name="uq_client_ca_user_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    ca_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    gstin: Mapped[Optional[str]] = mapped_column(String(15), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # Relationships
    ca_user: Mapped["User"] = relationship("User", back_populates="clients")
    documents: Mapped[List["ClientDocument"]] = relationship(
        "ClientDocument", back_populates="client", cascade="all, delete-orphan"
    )


class ClientDocument(Base, TimestampMixin):
    """Links a client to a specific audit job / uploaded document."""
    __tablename__ = "client_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="CASCADE")
    )
    audit_job_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("audit_jobs.id", ondelete="CASCADE")
    )
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)

    # Relationships
    client: Mapped["Client"] = relationship("Client", back_populates="documents")
    audit_job: Mapped["AuditJob"] = relationship("AuditJob")
