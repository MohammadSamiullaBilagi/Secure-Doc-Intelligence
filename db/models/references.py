import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Text, DateTime, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from db.database import Base, TimestampMixin


class ReferenceCache(Base, TimestampMixin):
    """Cached ground truth references for compliance checks."""
    __tablename__ = "reference_cache"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    check_id: Mapped[str] = mapped_column(String(50), index=True, unique=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=True)
    extracted_rules: Mapped[str] = mapped_column(Text, nullable=True)
    ttl_days: Mapped[int] = mapped_column(Integer, default=30)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
