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
    extracted_clause: str
    is_compliant: bool
    violation_details: str
    suggested_amendment: str