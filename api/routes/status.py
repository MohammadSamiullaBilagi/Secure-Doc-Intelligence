import asyncio
import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from api.dependencies import get_current_user
from db.database import get_db
from db.models.core import User, AuditJob
from db.models.notices import NoticeJob

from uuid import UUID

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/status", tags=["status"])


# In-memory status store keyed by thread_id
# In production, use Redis. For MVP, this works within a single process.
_audit_status: dict[str, dict] = {}


def update_audit_status(thread_id: str, stage: str, message: str, progress: int = 0):
    """Called from watcher/orchestrator to update the status of an audit."""
    _audit_status[thread_id] = {
        "stage": stage,
        "message": message,
        "progress": progress,
    }


def get_audit_status(thread_id: str) -> dict:
    """Get current status or return a default."""
    return _audit_status.get(thread_id, {
        "stage": "queued",
        "message": "Waiting to start...",
        "progress": 0,
    })


async def _resolve_thread_id(thread_id: str, current_user, db: AsyncSession) -> str | None:
    """Resolve a thread_id to the actual langgraph_thread_id.

    The frontend may send either the langgraph_thread_id directly or a job UUID
    (notice_job_id / audit_job_id). This helper checks all lookup paths and
    returns the canonical thread_id used in _audit_status, or None if not found.
    """
    # 1. Check AuditJob by langgraph_thread_id
    result = await db.execute(
        select(AuditJob).where(
            AuditJob.user_id == current_user.id,
            AuditJob.langgraph_thread_id == thread_id,
        )
    )
    if result.scalar_one_or_none():
        return thread_id

    # 2. Check NoticeJob by langgraph_thread_id
    result = await db.execute(
        select(NoticeJob).where(
            NoticeJob.user_id == current_user.id,
            NoticeJob.langgraph_thread_id == thread_id,
        )
    )
    if result.scalar_one_or_none():
        return thread_id

    # 3. Try interpreting thread_id as a job UUID (frontend sends notice_job_id)
    try:
        job_uuid = UUID(thread_id)
    except ValueError:
        return None

    # Check NoticeJob by id
    result = await db.execute(
        select(NoticeJob).where(
            NoticeJob.user_id == current_user.id,
            NoticeJob.id == job_uuid,
        )
    )
    notice_job = result.scalar_one_or_none()
    if notice_job and notice_job.langgraph_thread_id:
        return notice_job.langgraph_thread_id

    # Check AuditJob by id
    result = await db.execute(
        select(AuditJob).where(
            AuditJob.user_id == current_user.id,
            AuditJob.id == job_uuid,
        )
    )
    audit_job = result.scalar_one_or_none()
    if audit_job and audit_job.langgraph_thread_id:
        return audit_job.langgraph_thread_id

    return None


@router.get("/stream/{thread_id}")
async def stream_audit_status(
    thread_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint that streams real-time audit progress to the frontend.

    The frontend connects to this and receives live updates like:
    - "Extracting text from document..."
    - "Researcher: Checking GST compliance rules..."
    - "Auditor: Evaluating 7 checks..."
    - "Generating risk report..."
    - "Awaiting your review..."
    """
    # Resolve thread_id: frontend may send notice job UUID instead of langgraph_thread_id
    resolved_thread_id = await _resolve_thread_id(thread_id, current_user, db)
    if resolved_thread_id is None:
        async def error_gen():
            yield {"event": "error", "data": json.dumps({"message": "Audit not found"})}
        return EventSourceResponse(error_gen())
    thread_id = resolved_thread_id

    async def event_generator():
        """Poll the status dict and yield SSE events."""
        last_stage = None
        last_progress = -1
        timeout_count = 0
        max_timeout = 300  # 5 minutes max

        while timeout_count < max_timeout:
            status = get_audit_status(thread_id)
            
            # Emit when stage OR progress changes (not just stage)
            if status["stage"] != last_stage or status["progress"] != last_progress:
                last_stage = status["stage"]
                last_progress = status["progress"]
                yield {
                    "event": "status",
                    "data": json.dumps(status),
                }
                
                # If completed or awaiting review, send final event and stop
                if status["stage"] in ("completed", "awaiting_review", "error"):
                    yield {
                        "event": "done",
                        "data": json.dumps(status),
                    }
                    break

            await asyncio.sleep(1)
            timeout_count += 1

        # Send timeout if we exceeded max wait
        if timeout_count >= max_timeout:
            yield {
                "event": "timeout",
                "data": json.dumps({"message": "Status stream timed out"}),
            }

    return EventSourceResponse(event_generator())


@router.get("/{thread_id}")
async def get_status(
    thread_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Simple polling endpoint — returns current audit status once."""
    resolved_thread_id = await _resolve_thread_id(thread_id, current_user, db)
    if resolved_thread_id is None:
        from fastapi import HTTPException
        raise HTTPException(403, "Not authorized to view this audit status")
    return get_audit_status(resolved_thread_id)
