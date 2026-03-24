"""Pydantic schemas for GSTR-9 Annual Return reconciliation."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class GSTR9UploadResponse(BaseModel):
    recon_id: str
    status: str
    message: str


class MonthlyComparison(BaseModel):
    month: str
    gstr1_turnover: float = 0.0
    gstr3b_turnover: float = 0.0
    turnover_diff: float = 0.0
    gstr1_tax: float = 0.0
    gstr3b_tax: float = 0.0
    tax_diff: float = 0.0
    severity: str = "LOW"  # LOW / MEDIUM / HIGH


class ActionItem(BaseModel):
    priority: int
    category: str  # TURNOVER_MISMATCH / TAX_MISMATCH / ITC_EXCESS / BOOKS_GAP / MISSING_MONTH
    description: str
    financial_impact: float = 0.0
    recommendation: str = ""


class GSTR9Summary(BaseModel):
    fy: str
    gstin: str
    gstr1_total_turnover: float = 0.0
    gstr3b_total_turnover: float = 0.0
    turnover_diff: float = 0.0
    gstr1_total_tax: float = 0.0
    gstr3b_total_tax: float = 0.0
    tax_diff: float = 0.0
    discrepancy_count: int = 0
    status: str = "clean"  # clean / minor_issues / needs_attention / critical


class GSTR9ReconResult(BaseModel):
    summary: dict
    monthly_comparison: List[dict]
    tax_reconciliation: dict
    books_reconciliation: Optional[dict] = None
    itc_summary: dict
    gstr9_tables: dict
    action_items: List[dict]


class GSTR9DetailResponse(BaseModel):
    recon_id: str
    gstin: str
    fy: str
    status: str
    gstr1_turnover: float = 0.0
    gstr3b_turnover: float = 0.0
    books_turnover: float = 0.0
    result: Optional[dict] = None
    error: Optional[str] = None
    message: Optional[str] = None


class GSTR9ListItem(BaseModel):
    recon_id: str
    gstin: str
    fy: str
    status: str
    gstr1_turnover: float = 0.0
    gstr3b_turnover: float = 0.0
    books_turnover: float = 0.0
    discrepancy_count: int = 0
    client_id: Optional[str] = None
    created_at: Optional[str] = None
