import logging
from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

logger = logging.getLogger(__name__)

from api.dependencies import get_current_user
from db.database import get_db
from db.models.core import User, AuditJob
from db.models.clients import Client
from multi_agent import ComplianceOrchestrator
from services.approval_service import ApprovalService
from api.routes.documents import get_session_paths

router = APIRouter(prefix="/api/v1/audits", tags=["audits"])

class PendingAuditResponse(BaseModel):
    thread_id: str
    document_name: str
    risk_report: str
    requires_action: bool
    email_draft: Optional[str] = None
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

            pending_responses.append(
                PendingAuditResponse(
                    thread_id=job.langgraph_thread_id,
                    document_name=job.document_name,
                    risk_report=pending_state.get("risk_report", ""),
                    requires_action=requires_action,
                    email_draft=remediation.get("email_body", "") if requires_action else None,
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
    request: ApprovalRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db)
):
    """Approves an AI-drafted remediation and dispatches the webhook."""
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
        
        return {"status": "success", "message": "Approved and Dispatched"}
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
