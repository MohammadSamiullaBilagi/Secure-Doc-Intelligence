import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.dependencies import get_current_user, require_enterprise
from db.database import get_db
from db.models.core import User, AuditJob, UserPreference
from db.models.clients import Client
from multi_agent import ComplianceOrchestrator
from services.approval_service import ApprovalService
from services.report_service import ReportService
from services.export_service import ExportService
from schemas.export_schema import ExportFormat
from api.routes.documents import get_session_paths

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _get_audit_state_sync(user_id: str, thread_id: str) -> dict:
    """Retrieve audit state from LangGraph checkpointer (synchronous — run via asyncio.to_thread)."""
    _, db_dir = get_session_paths(user_id)
    orchestrator = ComplianceOrchestrator(db_dir=str(db_dir))
    approval_svc = ApprovalService(orchestrator)
    state = approval_svc.get_pending_approval(thread_id)

    if not state:
        graph = orchestrator.get_compiled_graph()
        config = {"configurable": {"thread_id": thread_id}}
        final_state = graph.get_state(config)
        state = final_state.values if final_state else {}

    return state if isinstance(state, dict) else {}


async def _get_audit_state(user_id: str, thread_id: str) -> dict:
    """Async wrapper that runs sync LangGraph calls in a thread executor."""
    return await asyncio.to_thread(_get_audit_state_sync, user_id, thread_id)


@router.get("/{thread_id}/pdf")
async def download_audit_report(
    thread_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Download a PDF compliance report for a completed audit."""
    query = select(AuditJob).where(
        AuditJob.user_id == current_user.id,
        AuditJob.langgraph_thread_id == thread_id,
    )
    result = await db.execute(query)
    jobs = result.scalars().all()

    if not jobs:
        raise HTTPException(404, "Audit report not found")

    job = jobs[0]

    try:
        state = await _get_audit_state(str(current_user.id), thread_id)
        risk_report = state.get("risk_report", "No risk report available.")

        # Fetch client info if audit is linked to a client
        client_info = None
        if job.client_id:
            client_result = await db.execute(
                select(Client).where(Client.id == job.client_id)
            )
            client = client_result.scalar_one_or_none()
            if client:
                client_info = {"name": client.name, "gstin": client.gstin}

        # Fetch CA branding info
        ca_info = None
        pref_result = await db.execute(
            select(UserPreference).where(UserPreference.user_id == current_user.id)
        )
        prefs = pref_result.scalar_one_or_none()
        if prefs and (prefs.firm_name or prefs.ca_name or prefs.icai_membership_number):
            ca_info = {
                "firm_name": prefs.firm_name,
                "ca_name": prefs.ca_name,
                "icai_membership_number": prefs.icai_membership_number,
                "firm_address": prefs.firm_address,
                "firm_phone": prefs.firm_phone,
                "firm_email": prefs.firm_email,
            }

        pdf_buffer = ReportService.generate_compliance_pdf(
            job.document_name, risk_report, state,
            client_info=client_info, ca_info=ca_info,
        )

        safe_name = job.document_name.replace(" ", "_").replace(".pdf", "")
        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="audit_report_{safe_name}.pdf"'
            },
        )
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        raise HTTPException(500, "Failed to generate report. Please try again.")


@router.get("/{thread_id}/export")
async def export_audit_report(
    thread_id: str,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
    format: ExportFormat = Query(..., description="Export format: csv, tally, or zoho"),
):
    """Export audit results in CSV, Tally XML, or Zoho JSON format. Requires Enterprise plan."""
    query = select(AuditJob).where(
        AuditJob.user_id == current_user.id,
        AuditJob.langgraph_thread_id == thread_id,
    )
    result = await db.execute(query)
    jobs = result.scalars().all()

    if not jobs:
        raise HTTPException(404, "Audit report not found")

    job = jobs[0]

    try:
        state = await _get_audit_state(str(current_user.id), thread_id)
        audit_results = state.get("audit_results") or []

        safe_name = job.document_name.replace(" ", "_").replace(".pdf", "")

        if format == ExportFormat.CSV:
            buffer = ExportService.to_csv(audit_results)
            return StreamingResponse(
                buffer,
                media_type="text/csv",
                headers={"Content-Disposition": f'attachment; filename="audit_{safe_name}.csv"'},
            )
        elif format == ExportFormat.TALLY:
            buffer = ExportService.to_tally_xml(audit_results)
            return StreamingResponse(
                buffer,
                media_type="application/xml",
                headers={"Content-Disposition": f'attachment; filename="audit_{safe_name}_tally.xml"'},
            )
        elif format == ExportFormat.ZOHO:
            buffer = ExportService.to_zoho_json(audit_results)
            return StreamingResponse(
                buffer,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="audit_{safe_name}_zoho.json"'},
            )
    except Exception as e:
        logger.error(f"Export failed: {e}")
        raise HTTPException(500, "Failed to export report. Please try again.")
