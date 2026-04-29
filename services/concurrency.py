"""Process-wide concurrency primitives for long-running operations.

Centralizes the audit thread pool and semaphore so any module (watcher,
routes, scripts) can reach them without depending on FastAPI's app.state.
"""
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# Dedicated executor for compliance audits — keeps long Gemini calls off the
# default thread pool so login/bcrypt/ingestion threads cannot be starved.
AUDIT_EXECUTOR: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="audit"
)

# Bounds in-flight audits across the whole process. Protects Gemini rate
# limits and the SQLite/Postgres checkpointer from thundering-herd traffic.
AUDIT_SEMAPHORE: asyncio.Semaphore = asyncio.Semaphore(4)

# Per-user ingestion lock map: serializes ChromaDB writes for the SAME user
# while leaving different users free to ingest in parallel.
_INGESTION_LOCKS: dict[str, asyncio.Lock] = {}
_INGESTION_MAP_LOCK: asyncio.Lock = asyncio.Lock()


async def get_ingestion_lock(user_id: str) -> asyncio.Lock:
    """Return (creating if needed) the asyncio.Lock for a user's ingestion."""
    async with _INGESTION_MAP_LOCK:
        lock = _INGESTION_LOCKS.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _INGESTION_LOCKS[user_id] = lock
        return lock
