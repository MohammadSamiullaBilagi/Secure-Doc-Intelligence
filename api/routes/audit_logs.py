"""Audit log viewer routes — admin and user-facing."""

import logging
from datetime import datetime
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user, require_admin
from db.database import get_db
from db.models.core import User
from db.models.audit_log import AuditLog
from schemas.audit_log_schema import AuditLogResponse, AuditLogListResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audit-logs", tags=["Audit Logs"])


def _format_log(log: AuditLog, email: str = None) -> AuditLogResponse:
    return AuditLogResponse(
        id=str(log.id),
        user_id=str(log.user_id),
        user_email=email,
        action=log.action,
        resource_type=log.resource_type,
        resource_id=log.resource_id,
        ip_address=log.ip_address,
        details=log.details,
        created_at=log.created_at.isoformat() if log.created_at else "",
    )


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    current_user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: Optional[str] = Query(default=None),
    action: Optional[str] = Query(default=None),
    from_date: Optional[str] = Query(default=None),
    to_date: Optional[str] = Query(default=None),
):
    """Admin-only: paginated audit log viewer with filters."""
    query = select(AuditLog, User.email).join(User, AuditLog.user_id == User.id)
    count_query = select(func.count(AuditLog.id))

    if user_id:
        query = query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)
    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if from_date:
        try:
            dt = datetime.fromisoformat(from_date)
            query = query.where(AuditLog.created_at >= dt)
            count_query = count_query.where(AuditLog.created_at >= dt)
        except ValueError:
            pass
    if to_date:
        try:
            dt = datetime.fromisoformat(to_date)
            query = query.where(AuditLog.created_at <= dt)
            count_query = count_query.where(AuditLog.created_at <= dt)
        except ValueError:
            pass

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.all()

    logs = [_format_log(row[0], email=row[1]) for row in rows]
    return AuditLogListResponse(total=total, logs=logs)


@router.get("/me", response_model=AuditLogListResponse)
async def my_audit_logs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    action: Optional[str] = Query(default=None),
):
    """User's own audit logs."""
    query = select(AuditLog).where(AuditLog.user_id == current_user.id)
    count_query = select(func.count(AuditLog.id)).where(AuditLog.user_id == current_user.id)

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit)
    result = await db.execute(query)
    logs_list = result.scalars().all()

    logs = [_format_log(log, email=current_user.email) for log in logs_list]
    return AuditLogListResponse(total=total, logs=logs)
