"""Service for recording audit trail events (DPDPA compliance)."""

import uuid
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.audit_log import AuditLog


async def log_audit_event(
    db: AsyncSession,
    user_id: uuid.UUID,
    action: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Create an audit log record. Caller controls the transaction (commit)."""
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        ip_address=ip_address,
        user_agent=user_agent,
        details=details,
    )
    db.add(entry)


def extract_request_meta(request: Request) -> tuple:
    """Extract IP address and User-Agent from a FastAPI Request."""
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return ip, ua
