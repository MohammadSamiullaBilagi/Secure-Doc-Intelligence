import logging
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

logger = logging.getLogger(__name__)

from api.dependencies import get_current_user
from db.database import get_db
from db.models.core import User, AuditJob, UserPreference
from db.models.clients import Client
from multi_agent import ComplianceOrchestrator
from services.approval_service import ApprovalService
from services.audit_log_service import log_audit_event, extract_request_meta
from services.email_service import EmailService
from api.routes.documents import get_session_paths

router = APIRouter(prefix="/api/v1/audits", tags=["audits"])

class PendingAuditResponse(BaseModel):
    thread_id: str
    document_name: str
    risk_report: str
    requires_action: bool
    email_draft: Optional[str] = None
    email_draft_html: Optional[str] = None
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    blueprint_name: Optional[str] = None
    compliance_score: Optional[float] = None
    open_violations: int = 0
    total_financial_exposure: float = 0.0
    
class ApprovalRequest(BaseModel):
    edited_draft: str

@router.get("/pending", response_model=List[PendingAuditResponse])
async def fetch_pending_tasks(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
):
    """Scans the user's vector data for LangGraph workflows paused right before Dispatch."""
    data_dir, db_dir = get_session_paths(str(current_user.id))
    
    if not db_dir.exists() or not any(db_dir.iterdir()):
        return []

    # Get trackable jobs
    query = select(AuditJob).where(
        AuditJob.user_id == current_user.id,
        AuditJob.status == "pending"
    )
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    orchestrator = ComplianceOrchestrator(db_dir=str(db_dir))
    approval_svc = ApprovalService(orchestrator)
    
    pending_responses = []
    seen_thread_ids = set()  # Deduplicate by thread_id
    
    for job in jobs:
        # thread_id was generated during upload and saved in DB
        if not job.langgraph_thread_id:
            continue
        
        # Skip duplicates — same thread_id means same audit
        if job.langgraph_thread_id in seen_thread_ids:
            continue
            
        pending_state = approval_svc.get_pending_approval(job.langgraph_thread_id)
        
        if pending_state:
            seen_thread_ids.add(job.langgraph_thread_id)
            remediation = pending_state.get("remediation_draft", {})
            requires_action = remediation.get("requires_action", False)

            # Resolve client name if linked
            client_name = None
            if job.client_id:
                client_result = await db.execute(
                    select(Client.name).where(Client.id == job.client_id)
                )
                client_name = client_result.scalar_one_or_none()

            raw_draft = remediation.get("email_body", "") if requires_action else None
            pending_responses.append(
                PendingAuditResponse(
                    thread_id=job.langgraph_thread_id,
                    document_name=job.document_name,
                    risk_report=pending_state.get("risk_report", ""),
                    requires_action=requires_action,
                    email_draft=raw_draft,
                    email_draft_html=raw_draft.replace("\n", "<br>") if raw_draft else None,
                    client_id=str(job.client_id) if job.client_id else None,
                    client_name=client_name,
                    blueprint_name=job.blueprint_name,
                    compliance_score=job.compliance_score,
                    open_violations=job.open_violations,
                    total_financial_exposure=job.total_financial_exposure,
                )
            )
            
    return pending_responses

@router.delete("/clear")
async def clear_pending_audits(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
):
    """Clears all pending audit jobs for the current user."""
    result = await db.execute(
        delete(AuditJob).where(
            AuditJob.user_id == current_user.id,
            AuditJob.status == "pending"
        )
    )
    await db.commit()
    return {"status": "success", "cleared": result.rowcount}

@router.post("/{thread_id}/approve")
async def approve_audit_task(
    thread_id: str,
    req: Request,
    request: ApprovalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
):
    """Approves an AI-drafted remediation and dispatches the webhook."""
    ip, ua = extract_request_meta(req)
    await log_audit_event(
        db, current_user.id, "audit_run",
        resource_type="audit_job", resource_id=thread_id,
        ip_address=ip, user_agent=ua,
    )
    _, db_dir = get_session_paths(str(current_user.id))
    
    # 1. Verify ownership of the DB job (use first() to handle duplicate uploads)
    query = select(AuditJob).where(
        AuditJob.user_id == current_user.id, 
        AuditJob.langgraph_thread_id == thread_id
    )
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    if not jobs:
        raise HTTPException(status_code=404, detail="Audit job not found for user")
    job = jobs[0]
        
    # 2. Unpause LangGraph
    try:
        orchestrator = ComplianceOrchestrator(db_dir=str(db_dir))
        approval_svc = ApprovalService(orchestrator)
        approval_svc.approve_and_resume(thread_id, request.edited_draft)

        # 3. Mark ALL matching jobs done (handles duplicate uploads)
        for j in jobs:
            j.status = "dispatched"
        await db.commit()

        # 4. Send email to subscriber's preferred email + client email
        email_sent = False
        email_error = None

        # Always fetch CA branding & subscriber preferred email
        pref_result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == current_user.id)
        )
        prefs = pref_result.scalar_one_or_none()
        ca_name = prefs.ca_name if prefs else None
        firm_name = prefs.firm_name if prefs else None
        reply_to = prefs.firm_email if prefs else None
        subscriber_email = (prefs.preferred_email if prefs else None) or current_user.email

        # Build recipient list: subscriber always gets a copy
        recipients = [subscriber_email]

        if job.client_id:
            client_result = await db.execute(
                select(Client).where(Client.id == job.client_id)
            )
            client = client_result.scalar_one_or_none()
            if client and client.email:
                recipients.append(client.email)

        subject = f"Compliance Audit Report: {job.document_name}"
        if firm_name:
            subject += f" — {firm_name}"

        try:
            email_sent = EmailService.send_audit_dispatch(
                to=recipients,
                ca_name=ca_name or firm_name or "",
                subject=subject,
                body=request.edited_draft,
                reply_to=reply_to,
            )
            if not email_sent:
                email_error = "SMTP send failed — check server SMTP configuration"
        except Exception as email_exc:
            logger.error(f"Failed to send audit email to {recipients}: {email_exc}")
            email_error = str(email_exc)

        return {
            "status": "success",
            "message": "Approved and Dispatched",
            "email_sent": email_sent,
            "email_error": email_error,
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{thread_id}/reject")
async def reject_audit_task(
    thread_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
):
    """Rejects the task and cancels webhook execution."""
    _, db_dir = get_session_paths(str(current_user.id))
    
    query = select(AuditJob).where(AuditJob.user_id == current_user.id, AuditJob.langgraph_thread_id == thread_id)
    result = await db.execute(query)
    jobs = result.scalars().all()
    
    if not jobs:
        raise HTTPException(status_code=404, detail="Audit job not found")
    job = jobs[0]
        
    try:
        orchestrator = ComplianceOrchestrator(db_dir=str(db_dir))
        approval_svc = ApprovalService(orchestrator)
        approval_svc.reject_and_cancel(thread_id)
        
        for j in jobs:
            j.status = "rejected"
        await db.commit()
        return {"status": "success", "message": "Rejected Task"}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
