"""Account management routes — Data Export, Data Deletion (DPDPA Right to Erasure)."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.rate_limit import limiter
from db.database import get_db
from db.models.core import User, AuditJob, Blueprint
from db.models.chat import ChatMessage
from db.models.clients import Client
from db.models.notices import NoticeJob
from db.models.feedback import Feedback
from schemas.legal import DataDeletionRequest, DataDeletionResponse
from services.audit_log_service import log_audit_event, extract_request_meta
from services.data_deletion_service import delete_user_data

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/account", tags=["Account"])


@router.delete("/data", response_model=DataDeletionResponse)
@limiter.limit("3/hour")
async def delete_all_data(
    request: Request,
    body: DataDeletionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Right to Erasure — permanently deletes all user's personal data.

    Preserves: User account (marked as deleted), Subscription, CreditTransactions, AuditLogs.
    """
    if not body.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must set confirm=true to proceed with data deletion.",
        )

    if current_user.data_deleted_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Data has already been deleted for this account.",
        )

    # Log the deletion event BEFORE deleting (audit logs are preserved)
    ip, ua = extract_request_meta(request)
    await log_audit_event(
        db, current_user.id, "data_delete",
        ip_address=ip, user_agent=ua,
        details={"triggered_by": "user_request"},
    )
    await db.commit()

    summary = await delete_user_data(current_user.id, db)
    logger.info(f"Data deletion completed for {current_user.email}")

    return DataDeletionResponse(
        message="All personal data has been permanently deleted. Your account and billing history are preserved.",
        summary=summary,
    )


@router.get("/data-export")
@limiter.limit("5/hour")
async def export_user_data(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Right to Access — exports all user's personal data as JSON."""
    # Collect user profile
    profile = {
        "id": str(current_user.id),
        "email": current_user.email,
        "is_active": current_user.is_active,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        "consent_version": current_user.consent_version,
        "consent_accepted_at": (
            current_user.consent_accepted_at.isoformat()
            if current_user.consent_accepted_at else None
        ),
    }

    # Collect preferences
    prefs = current_user.preferences
    preferences = None
    if prefs:
        preferences = {
            "preferred_email": prefs.preferred_email,
            "whatsapp_number": prefs.whatsapp_number,
            "firm_name": prefs.firm_name,
            "ca_name": prefs.ca_name,
            "icai_membership_number": prefs.icai_membership_number,
            "firm_address": prefs.firm_address,
            "firm_phone": prefs.firm_phone,
            "firm_email": prefs.firm_email,
        }

    # Collect chat messages
    chat_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.user_id == current_user.id)
        .order_by(ChatMessage.created_at)
    )
    chat_messages = [
        {
            "session_id": msg.session_id,
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat(),
        }
        for msg in chat_result.scalars().all()
    ]

    # Collect audit jobs
    audit_result = await db.execute(
        select(AuditJob).where(AuditJob.user_id == current_user.id)
    )
    audit_jobs = [
        {
            "id": str(job.id),
            "document_name": job.document_name,
            "status": job.status,
            "blueprint_name": job.blueprint_name,
            "compliance_score": job.compliance_score,
            "created_at": job.created_at.isoformat() if job.created_at else None,
        }
        for job in audit_result.scalars().all()
    ]

    # Collect clients
    client_result = await db.execute(
        select(Client).where(Client.ca_user_id == current_user.id)
    )
    clients = [
        {
            "id": str(c.id),
            "name": c.name,
            "gstin": c.gstin,
            "email": c.email,
            "phone": c.phone,
        }
        for c in client_result.scalars().all()
    ]

    # Collect notice jobs
    notice_result = await db.execute(
        select(NoticeJob).where(NoticeJob.user_id == current_user.id)
    )
    notices = [
        {
            "id": str(n.id),
            "notice_type": n.notice_type,
            "status": n.status,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notice_result.scalars().all()
    ]

    # Collect feedback
    feedback_result = await db.execute(
        select(Feedback).where(Feedback.user_id == current_user.id)
    )
    feedbacks = [
        {
            "category": f.category,
            "subject": f.subject,
            "message": f.message,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }
        for f in feedback_result.scalars().all()
    ]

    # Log the export event
    ip, ua = extract_request_meta(request)
    await log_audit_event(
        db, current_user.id, "data_export",
        ip_address=ip, user_agent=ua,
    )
    await db.commit()

    return {
        "export_date": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "profile": profile,
        "preferences": preferences,
        "chat_messages": chat_messages,
        "audit_jobs": audit_jobs,
        "clients": clients,
        "notice_jobs": notices,
        "feedback": feedbacks,
    }
