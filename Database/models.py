from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class SessionTrack(Base):
    __tablename__ = "sessions"
    
    session_hash = Column(String, primary_key=True, index=True)
    last_accessed = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    status = Column(String, default="active") # active, expired, deleted