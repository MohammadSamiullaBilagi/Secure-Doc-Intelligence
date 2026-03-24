import os
import shutil
import logging
from pathlib import Path
from config import settings
from Database.database import SessionLocal
from repositories.session_repository import SessionRepository
from services.storage import get_storage

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
            storage = get_storage()

            for session in expired_sessions:
                # Storage cleanup (handles both local and S3)
                try:
                    storage.delete_prefix(session.session_hash)
                    logger.info(f"Wiped storage data for session: {session.session_hash}")
                except Exception as e:
                    logger.error(f"Failed to delete storage for {session.session_hash}: {e}")
                    continue  # Skip DB update if storage wipe fails

                # DB Cleanup
                repo.mark_deleted(session.session_hash)
                
            logger.info(f"Sweep complete. Cleared {len(expired_sessions)} sessions.")
        finally:
            db.close()