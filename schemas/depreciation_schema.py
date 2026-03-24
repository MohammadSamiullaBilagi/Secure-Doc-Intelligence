"""Pydantic schemas for Depreciation Calculator."""

from typing import Optional
from pydantic import BaseModel


class DepreciationComputeResponse(BaseModel):
    analysis_id: str
    status: str
    fy: str
    total_assets: int = 0
    total_cost: float = 0.0
    it_act_depreciation: float = 0.0
    ca_depreciation: float = 0.0
    timing_difference: float = 0.0
    deferred_tax_amount: float = 0.0
    deferred_tax_type: str = "NIL"


class DepreciationHistoryItem(BaseModel):
    analysis_id: str
    filename: str
    fy: str
    status: str
    total_assets: int = 0
    total_cost: float = 0.0
    it_act_depreciation: float = 0.0
    ca_depreciation: float = 0.0
    timing_difference: float = 0.0
    deferred_tax_amount: float = 0.0
    created_at: Optional[str] = None


class DepreciationDetailResponse(DepreciationHistoryItem):
    tax_rate: float = 0.25
    result: Optional[dict] = None
    error: Optional[str] = None
    message: Optional[str] = None
