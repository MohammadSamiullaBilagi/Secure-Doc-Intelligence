"""Pydantic schemas for Advance Tax & Section 234 Interest Calculator."""

from typing import Optional
from pydantic import BaseModel


class InstalmentInput(BaseModel):
    due_date: str          # "2025-06-15"
    paid_amount: float     # >= 0
    paid_date: str         # "2025-06-10"


class AdvanceTaxComputeRequest(BaseModel):
    estimated_tax: float   # > 0
    fy: str                # "2025-26"
    client_id: Optional[str] = None
    instalments_paid: list[InstalmentInput] = []
    itr_filing_date: Optional[str] = None
    itr_due_date: Optional[str] = None


class RemainingInstalmentRequest(BaseModel):
    estimated_annual_tax: float  # > 0
    fy: str
    paid_so_far: float = 0.0
    client_id: Optional[str] = None


class AdvanceTaxComputeResponse(BaseModel):
    computation_id: str
    status: str
    fy: str
    estimated_tax: float
    total_interest: float
    interest_234a: float
    interest_234b: float
    interest_234c: float


class AdvanceTaxHistoryItem(BaseModel):
    computation_id: str
    fy: str
    estimated_tax: float
    total_interest: float
    interest_234a: float
    interest_234b: float
    interest_234c: float
    status: str
    created_at: Optional[str] = None


class AdvanceTaxDetailResponse(AdvanceTaxHistoryItem):
    result: Optional[dict] = None
