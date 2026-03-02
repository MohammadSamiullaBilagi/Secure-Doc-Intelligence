from datetime import datetime, timezone, timedelta
from typing import List
from sqlalchemy.orm import Session
from Database.models import SessionTrack

class SessionRepository:
    def __init__(self, db_session: Session):
        self.db = db_session

    def heartbeat(self, session_hash: str) -> SessionTrack:
        """Creates or updates the last_accessed timestamp for a session."""
        session_obj = self.db.query(SessionTrack).filter(SessionTrack.session_hash == session_hash).first()
        
        if not session_obj:
            session_obj = SessionTrack(session_hash=session_hash)
            self.db.add(session_obj)
        else:
            session_obj.last_accessed = datetime.now(timezone.utc)
            
        self.db.commit()
        self.db.refresh(session_obj)
        return session_obj

    def get_expired_sessions(self, ttl_hours: int) -> List[SessionTrack]:
        """Retrieves sessions inactive longer than the TTL."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
        return self.db.query(SessionTrack).filter(
            SessionTrack.last_accessed < cutoff_time,
            SessionTrack.status == "active"
        ).all()
        
    def mark_deleted(self, session_hash: str):
        self.db.query(SessionTrack).filter(SessionTrack.session_hash == session_hash).update({"status": "deleted"})
        self.db.commit()