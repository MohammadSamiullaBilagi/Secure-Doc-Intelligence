import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class ClientCreate(BaseModel):
    name: str
    gstin: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    gstin: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class ClientResponse(BaseModel):
    id: uuid.UUID
    name: str
    gstin: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    created_at: datetime
    document_count: int = 0

    model_config = {"from_attributes": True}


class ClientDocumentResponse(BaseModel):
    id: uuid.UUID
    document_name: str
    audit_job_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------- Activity endpoint schemas ----------

class AuditSummaryItem(BaseModel):
    id: uuid.UUID
    status: Optional[str] = None
    document_name: Optional[str] = None
    blueprint_name: Optional[str] = None
    compliance_score: Optional[float] = None
    open_violations: int = 0
    total_financial_exposure: float = 0.0
    thread_id: Optional[str] = None
    created_at: Optional[datetime] = None


class GSTReconSummaryItem(BaseModel):
    id: uuid.UUID
    status: Optional[str] = None
    period: Optional[str] = None
    total_itc_at_risk: Optional[float] = None
    created_at: Optional[datetime] = None


class GSTR9ReconSummaryItem(BaseModel):
    id: uuid.UUID
    status: Optional[str] = None
    gstin: Optional[str] = None
    fy: Optional[str] = None
    discrepancy_count: Optional[int] = None
    created_at: Optional[datetime] = None


class BankAnalysisSummaryItem(BaseModel):
    id: uuid.UUID
    status: Optional[str] = None
    filename: Optional[str] = None
    high_flags: Optional[int] = None
    created_at: Optional[datetime] = None


class CapitalGainsSummaryItem(BaseModel):
    id: uuid.UUID
    status: Optional[str] = None
    fy: Optional[str] = None
    total_gain_loss: Optional[float] = None
    created_at: Optional[datetime] = None


class DepreciationSummaryItem(BaseModel):
    id: uuid.UUID
    status: Optional[str] = None
    fy: Optional[str] = None
    it_act_depreciation: Optional[float] = None
    created_at: Optional[datetime] = None


class AdvanceTaxSummaryItem(BaseModel):
    id: uuid.UUID
    status: Optional[str] = None
    fy: Optional[str] = None
    total_interest: Optional[float] = None
    created_at: Optional[datetime] = None


class ClientActivityResponse(BaseModel):
    client_id: uuid.UUID
    client_name: str
    audits: list[AuditSummaryItem] = []
    gst_reconciliations: list[GSTReconSummaryItem] = []
    gstr9_reconciliations: list[GSTR9ReconSummaryItem] = []
    bank_analyses: list[BankAnalysisSummaryItem] = []
    capital_gains: list[CapitalGainsSummaryItem] = []
    depreciation: list[DepreciationSummaryItem] = []
    advance_tax: list[AdvanceTaxSummaryItem] = []


# ---------- Dashboard schemas ----------

class ClientDashboardItem(BaseModel):
    client_id: uuid.UUID
    client_name: str
    gstin: Optional[str] = None
    last_audit_date: Optional[datetime] = None
    compliance_score: Optional[float] = None  # 0-100
    open_violations: int = 0
    total_financial_exposure: float = 0.0
    blueprint_name: Optional[str] = None
    next_deadline: Optional[dict] = None  # {name, due_date, days_remaining}
    features_used: dict = {}
    total_itc_at_risk: float = 0.0
    high_risk_flags: int = 0
    total_interest_liability: float = 0.0
    recent_scans: list[AuditSummaryItem] = []
