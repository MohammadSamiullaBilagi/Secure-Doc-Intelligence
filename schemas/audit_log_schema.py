"""Schemas for audit log endpoints."""

from pydantic import BaseModel
from typing import Optional, List


class AuditLogResponse(BaseModel):
    id: str
    user_id: str
    user_email: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    ip_address: Optional[str] = None
    details: Optional[dict] = None
    created_at: str


class AuditLogListResponse(BaseModel):
    total: int
    logs: List[AuditLogResponse]
