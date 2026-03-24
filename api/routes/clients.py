import logging
from datetime import date
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from api.dependencies import get_current_user, require_enterprise
from db.database import get_db
from db.models.core import (
    User, AuditJob, GSTReconciliation, GSTR9Reconciliation,
    BankStatementAnalysis, CapitalGainsAnalysis, DepreciationAnalysis,
    AdvanceTaxComputation,
)
from db.models.clients import Client, ClientDocument
from db.models.calendar import TaxDeadline
from schemas.client_schema import (
    ClientCreate, ClientUpdate, ClientResponse, ClientDocumentResponse,
    ClientDashboardItem, ClientActivityResponse,
    AuditSummaryItem, GSTReconSummaryItem, GSTR9ReconSummaryItem,
    BankAnalysisSummaryItem, CapitalGainsSummaryItem,
    DepreciationSummaryItem, AdvanceTaxSummaryItem,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/clients", tags=["clients"])


@router.get("/", response_model=list[ClientResponse])
async def list_clients(
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = Query(None, description="Search by name or GSTIN"),
):
    """List all clients belonging to the current CA user."""
    # Subquery for document counts — avoids N+1
    doc_count_subq = (
        select(
            ClientDocument.client_id,
            func.count(ClientDocument.id).label("doc_count"),
        )
        .group_by(ClientDocument.client_id)
        .subquery()
    )

    query = (
        select(Client, func.coalesce(doc_count_subq.c.doc_count, 0).label("doc_count"))
        .outerjoin(doc_count_subq, Client.id == doc_count_subq.c.client_id)
        .where(Client.ca_user_id == current_user.id)
    )

    if search:
        query = query.where(
            (Client.name.ilike(f"%{search}%")) | (Client.gstin.ilike(f"%{search}%"))
        )

    query = query.order_by(Client.created_at.desc())
    result = await db.execute(query)
    rows = result.all()

    return [
        ClientResponse(
            id=client.id,
            name=client.name,
            gstin=client.gstin,
            email=client.email,
            phone=client.phone,
            created_at=client.created_at,
            document_count=doc_count,
        )
        for client, doc_count in rows
    ]


@router.post("/", response_model=ClientResponse, status_code=201)
async def create_client(
    body: ClientCreate,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """Create a new client for the current CA user."""
    client = Client(
        ca_user_id=current_user.id,
        name=body.name,
        gstin=body.gstin,
        email=body.email,
        phone=body.phone,
    )
    db.add(client)
    await db.commit()
    await db.refresh(client)

    return ClientResponse(
        id=client.id,
        name=client.name,
        gstin=client.gstin,
        email=client.email,
        phone=client.phone,
        created_at=client.created_at,
        document_count=0,
    )


@router.put("/{client_id}", response_model=ClientResponse)
async def update_client(
    client_id: UUID,
    body: ClientUpdate,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """Update a client (must be owned by current user)."""
    result = await db.execute(
        select(Client).where(Client.id == client_id, Client.ca_user_id == current_user.id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Client not found")

    if body.name is not None:
        client.name = body.name
    if body.gstin is not None:
        client.gstin = body.gstin
    if body.email is not None:
        client.email = body.email
    if body.phone is not None:
        client.phone = body.phone

    await db.commit()
    await db.refresh(client)

    doc_count_result = await db.execute(
        select(func.count(ClientDocument.id)).where(ClientDocument.client_id == client.id)
    )
    doc_count = doc_count_result.scalar() or 0

    return ClientResponse(
        id=client.id,
        name=client.name,
        gstin=client.gstin,
        email=client.email,
        phone=client.phone,
        created_at=client.created_at,
        document_count=doc_count,
    )


@router.delete("/{client_id}", status_code=204)
async def delete_client(
    client_id: UUID,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """Delete a client (must be owned by current user)."""
    result = await db.execute(
        select(Client).where(Client.id == client_id, Client.ca_user_id == current_user.id)
    )
    client = result.scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Client not found")

    await db.delete(client)
    await db.commit()


@router.get("/dashboard", response_model=list[ClientDashboardItem])
async def client_compliance_dashboard(
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """Per-client compliance health dashboard for CAs.

    Reads denormalized compliance metrics directly from AuditJob columns
    (populated by WatcherService after each scan completes), avoiding
    expensive LangGraph checkpointer reads.
    """
    # Get all clients for this CA
    result = await db.execute(
        select(Client).where(Client.ca_user_id == current_user.id).order_by(Client.name)
    )
    clients = result.scalars().all()

    # Get nearest upcoming deadline (shared across all clients)
    today = date.today()
    deadline_result = await db.execute(
        select(TaxDeadline)
        .where(TaxDeadline.due_date >= today)
        .order_by(TaxDeadline.due_date)
        .limit(1)
    )
    nearest_deadline = deadline_result.scalar_one_or_none()
    next_deadline_info = None
    if nearest_deadline:
        days_remaining = (nearest_deadline.due_date - today).days
        next_deadline_info = {
            "name": nearest_deadline.title,
            "due_date": nearest_deadline.due_date.isoformat(),
            "days_remaining": days_remaining,
        }

    dashboard = []
    for client in clients:
        cid = client.id

        # Latest audit — use denormalized columns instead of LangGraph state
        audit_result = await db.execute(
            select(AuditJob)
            .where(AuditJob.client_id == cid)
            .order_by(AuditJob.created_at.desc())
            .limit(1)
        )
        latest_job = audit_result.scalar_one_or_none()

        last_audit_date = latest_job.created_at if latest_job else None
        compliance_score = latest_job.compliance_score if latest_job else None
        open_violations = latest_job.open_violations if latest_job else 0
        total_financial_exposure = latest_job.total_financial_exposure if latest_job else 0.0
        blueprint_name = latest_job.blueprint_name if latest_job else None

        # Recent scans (last 5) — gives frontend a quick history per client
        recent_result = await db.execute(
            select(AuditJob)
            .where(AuditJob.client_id == cid)
            .order_by(AuditJob.created_at.desc())
            .limit(5)
        )
        recent_scans = [
            AuditSummaryItem(
                id=j.id,
                status=j.status,
                document_name=j.document_name,
                blueprint_name=j.blueprint_name,
                compliance_score=j.compliance_score,
                open_violations=j.open_violations,
                total_financial_exposure=j.total_financial_exposure,
                thread_id=j.langgraph_thread_id,
                created_at=j.created_at,
            )
            for j in recent_result.scalars().all()
        ]

        # Feature counts
        feature_counts = {}
        for model, key in [
            (AuditJob, "audits"),
            (GSTReconciliation, "gst_recon"),
            (GSTR9Reconciliation, "gstr9_recon"),
            (BankStatementAnalysis, "bank_analysis"),
            (CapitalGainsAnalysis, "capital_gains"),
            (DepreciationAnalysis, "depreciation"),
            (AdvanceTaxComputation, "advance_tax"),
        ]:
            cnt_result = await db.execute(
                select(func.count(model.id)).where(model.client_id == cid)
            )
            feature_counts[key] = cnt_result.scalar() or 0

        # Latest GST recon ITC at risk
        total_itc_at_risk = 0.0
        gst_latest = await db.execute(
            select(GSTReconciliation.total_itc_at_risk)
            .where(GSTReconciliation.client_id == cid, GSTReconciliation.status == "completed")
            .order_by(desc(GSTReconciliation.created_at))
            .limit(1)
        )
        row = gst_latest.scalar_one_or_none()
        if row is not None:
            total_itc_at_risk = float(row) if row else 0.0

        # Latest bank analysis high flags
        high_risk_flags = 0
        bank_latest = await db.execute(
            select(BankStatementAnalysis.high_flags)
            .where(BankStatementAnalysis.client_id == cid, BankStatementAnalysis.status == "completed")
            .order_by(desc(BankStatementAnalysis.created_at))
            .limit(1)
        )
        row = bank_latest.scalar_one_or_none()
        if row is not None:
            high_risk_flags = int(row) if row else 0

        # Latest advance tax interest
        total_interest_liability = 0.0
        at_latest = await db.execute(
            select(AdvanceTaxComputation.total_interest)
            .where(AdvanceTaxComputation.client_id == cid, AdvanceTaxComputation.status == "completed")
            .order_by(desc(AdvanceTaxComputation.created_at))
            .limit(1)
        )
        row = at_latest.scalar_one_or_none()
        if row is not None:
            total_interest_liability = float(row) if row else 0.0

        dashboard.append(ClientDashboardItem(
            client_id=cid,
            client_name=client.name,
            gstin=client.gstin,
            last_audit_date=last_audit_date,
            compliance_score=compliance_score,
            open_violations=open_violations,
            total_financial_exposure=total_financial_exposure,
            blueprint_name=blueprint_name,
            next_deadline=next_deadline_info,
            features_used=feature_counts,
            total_itc_at_risk=total_itc_at_risk,
            high_risk_flags=high_risk_flags,
            total_interest_liability=total_interest_liability,
            recent_scans=recent_scans,
        ))

    return dashboard


@router.get("/{client_id}/activity", response_model=ClientActivityResponse)
async def get_client_activity(
    client_id: UUID,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """Return all feature activity for a specific client."""
    # Verify ownership
    client_result = await db.execute(
        select(Client).where(Client.id == client_id, Client.ca_user_id == current_user.id)
    )
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Client not found")

    limit = 20

    # Audits — include compliance results from denormalized columns
    r = await db.execute(
        select(AuditJob)
        .where(AuditJob.client_id == client_id)
        .order_by(desc(AuditJob.created_at))
        .limit(limit)
    )
    audits = [
        AuditSummaryItem(
            id=j.id, status=j.status,
            document_name=j.document_name,
            blueprint_name=j.blueprint_name,
            compliance_score=j.compliance_score,
            open_violations=j.open_violations,
            total_financial_exposure=j.total_financial_exposure,
            thread_id=j.langgraph_thread_id,
            created_at=j.created_at,
        )
        for j in r.scalars().all()
    ]

    # GST Reconciliations
    r = await db.execute(
        select(GSTReconciliation)
        .where(GSTReconciliation.client_id == client_id)
        .order_by(desc(GSTReconciliation.created_at))
        .limit(limit)
    )
    gst_recons = [
        GSTReconSummaryItem(
            id=x.id, status=x.status, period=x.period,
            total_itc_at_risk=x.total_itc_at_risk,
            created_at=x.created_at,
        )
        for x in r.scalars().all()
    ]

    # GSTR-9 Reconciliations
    r = await db.execute(
        select(GSTR9Reconciliation)
        .where(GSTR9Reconciliation.client_id == client_id)
        .order_by(desc(GSTR9Reconciliation.created_at))
        .limit(limit)
    )
    gstr9_recons = [
        GSTR9ReconSummaryItem(
            id=x.id, status=x.status, gstin=x.gstin, fy=x.fy,
            discrepancy_count=x.discrepancy_count,
            created_at=x.created_at,
        )
        for x in r.scalars().all()
    ]

    # Bank Analyses
    r = await db.execute(
        select(BankStatementAnalysis)
        .where(BankStatementAnalysis.client_id == client_id)
        .order_by(desc(BankStatementAnalysis.created_at))
        .limit(limit)
    )
    bank_analyses = [
        BankAnalysisSummaryItem(
            id=x.id, status=x.status, filename=x.filename,
            high_flags=x.high_flags,
            created_at=x.created_at,
        )
        for x in r.scalars().all()
    ]

    # Capital Gains
    r = await db.execute(
        select(CapitalGainsAnalysis)
        .where(CapitalGainsAnalysis.client_id == client_id)
        .order_by(desc(CapitalGainsAnalysis.created_at))
        .limit(limit)
    )
    capital_gains = [
        CapitalGainsSummaryItem(
            id=x.id, status=x.status, fy=x.fy,
            total_gain_loss=x.total_gain_loss,
            created_at=x.created_at,
        )
        for x in r.scalars().all()
    ]

    # Depreciation
    r = await db.execute(
        select(DepreciationAnalysis)
        .where(DepreciationAnalysis.client_id == client_id)
        .order_by(desc(DepreciationAnalysis.created_at))
        .limit(limit)
    )
    depreciation = [
        DepreciationSummaryItem(
            id=x.id, status=x.status, fy=x.fy,
            it_act_depreciation=x.it_act_depreciation,
            created_at=x.created_at,
        )
        for x in r.scalars().all()
    ]

    # Advance Tax
    r = await db.execute(
        select(AdvanceTaxComputation)
        .where(AdvanceTaxComputation.client_id == client_id)
        .order_by(desc(AdvanceTaxComputation.created_at))
        .limit(limit)
    )
    advance_tax = [
        AdvanceTaxSummaryItem(
            id=x.id, status=x.status, fy=x.fy,
            total_interest=x.total_interest,
            created_at=x.created_at,
        )
        for x in r.scalars().all()
    ]

    return ClientActivityResponse(
        client_id=client.id,
        client_name=client.name,
        audits=audits,
        gst_reconciliations=gst_recons,
        gstr9_reconciliations=gstr9_recons,
        bank_analyses=bank_analyses,
        capital_gains=capital_gains,
        depreciation=depreciation,
        advance_tax=advance_tax,
    )


@router.get("/{client_id}/compliance-scans")
async def get_client_compliance_scans(
    client_id: UUID,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """Return all compliance scan results for a specific client.

    Returns the full results_summary JSON for each audit, including
    per-check results, risk report, and financial impact breakdown.
    This powers the per-client compliance detail view in the frontend.
    """
    # Verify ownership
    client_result = await db.execute(
        select(Client).where(Client.id == client_id, Client.ca_user_id == current_user.id)
    )
    client = client_result.scalar_one_or_none()
    if not client:
        raise HTTPException(404, "Client not found")

    r = await db.execute(
        select(AuditJob)
        .where(AuditJob.client_id == client_id)
        .order_by(desc(AuditJob.created_at))
        .limit(50)
    )
    jobs = r.scalars().all()

    scans = []
    for j in jobs:
        scan = {
            "id": str(j.id),
            "thread_id": j.langgraph_thread_id,
            "document_name": j.document_name,
            "blueprint_name": j.blueprint_name,
            "status": j.status,
            "compliance_score": j.compliance_score,
            "open_violations": j.open_violations,
            "total_financial_exposure": j.total_financial_exposure,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }

        # Include detailed results if available
        if j.results_summary and isinstance(j.results_summary, dict):
            scan["audit_results"] = j.results_summary.get("audit_results", [])
            scan["risk_report"] = j.results_summary.get("risk_report", "")
        else:
            scan["audit_results"] = []
            scan["risk_report"] = ""

        scans.append(scan)

    return {"client_id": str(client.id), "client_name": client.name, "scans": scans}


@router.get("/{client_id}/documents", response_model=list[ClientDocumentResponse])
async def list_client_documents(
    client_id: UUID,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """List all documents for a specific client."""
    # Verify ownership
    client_result = await db.execute(
        select(Client).where(Client.id == client_id, Client.ca_user_id == current_user.id)
    )
    if not client_result.scalar_one_or_none():
        raise HTTPException(404, "Client not found")

    result = await db.execute(
        select(ClientDocument)
        .where(ClientDocument.client_id == client_id)
        .order_by(ClientDocument.created_at.desc())
    )
    docs = result.scalars().all()

    return [
        ClientDocumentResponse(
            id=doc.id,
            document_name=doc.document_name,
            audit_job_id=doc.audit_job_id,
            created_at=doc.created_at,
        )
        for doc in docs
    ]
