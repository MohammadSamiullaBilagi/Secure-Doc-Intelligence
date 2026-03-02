import os
import shutil
import logging
from pathlib import Path
from config import settings
from Database.database import SessionLocal
from repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)

class CleanupService:
    @staticmethod
    def sweep_stale_sessions():
        """Idempotent background job to wipe disk and DB for expired sessions."""
        logger.info("Starting hourly TTL session sweep...")
        db = SessionLocal()
        repo = SessionRepository(db)
        
        try:
            expired_sessions = repo.get_expired_sessions(settings.session_ttl_hours)
            
            for session in expired_sessions:
                session_dir = Path(settings.user_sessions_dir) / session.session_hash
                
                # Disk Cleanup
                if session_dir.exists():
                    try:
                        shutil.rmtree(session_dir)
                        logger.info(f"Wiped disk data for session: {session.session_hash}")
                    except Exception as e:
                        logger.error(f"Failed to delete directory {session_dir}: {e}")
                        continue # Skip DB update if disk wipe fails
                
                # DB Cleanup
                repo.mark_deleted(session.session_hash)
                
            logger.info(f"Sweep complete. Cleared {len(expired_sessions)} sessions.")
        finally:
            db.close()