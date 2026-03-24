from typing import List
from pydantic import BaseModel, Field

class BlueprintCheck(BaseModel):
    """A single compliance check definition."""
    check_id: str = Field(..., description="Unique identifier for the check (e.g., 'GST_01').")
    focus: str = Field(..., description="What the Researcher should look for in the text.")
    rule: str = Field(..., description="The strict rule the Auditor must enforce.")

class Blueprint(BaseModel):
    """A complete regulatory framework blueprint."""
    blueprint_id: str = Field(...)
    name: str = Field(...)
    description: str = Field(...)
    checks: List[BlueprintCheck] = Field(min_length=1, description="List of rules to evaluate.")

class AuditResult(BaseModel):
    """The outcome of a single check evaluation."""
    check_id: str
    focus: str
    rule: str
    compliance_status: str  # e.g. "COMPLIANT", "PARTIAL", "NON_COMPLIANT"
    evidence: str
    violation_details: str
    suggested_amendment: str


class FinancialImpact(BaseModel):
    estimated_amount: float | None = None
    currency: str = "INR"
    calculation: str = ""  # e.g. "3,50,000 x (10% - 2%) = 28,000"
    section_reference: str = ""  # e.g. "Section 194J"


class CheckAgentOutput(BaseModel):
    """Structured output schema for Layer 2 check agents (Haiku)."""
    compliance_status: str  # COMPLIANT|PARTIAL|NON_COMPLIANT|INCONCLUSIVE
    evidence: str
    violation_details: str
    suggested_amendment: str
    financial_impact: FinancialImpact | None = None
    confidence: str = "LOW"  # HIGH|MEDIUM|LOW


class EnhancedAuditResult(AuditResult):
    """Extends AuditResult with financial impact + confidence. Backward-compatible."""
    financial_impact: dict | None = None
    confidence: str = "LOW"
    reference_source: str = "blueprint_only"
    reference_url: str | None = None