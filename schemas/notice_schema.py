from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel


class NoticeUploadResponse(BaseModel):
    notice_job_id: str
    status: str
    message: str


class NoticeDetailResponse(BaseModel):
    id: str
    notice_type: str
    notice_type_display: str
    notice_document_name: str
    supporting_documents: Optional[list] = None
    status: str
    extracted_data: Optional[dict] = None
    draft_reply: Optional[str] = None
    final_reply: Optional[str] = None
    client_id: Optional[str] = None
    created_at: Optional[str] = None


class NoticeListItem(BaseModel):
    id: str
    notice_type: str
    notice_type_display: str
    notice_document_name: str
    status: str
    client_id: Optional[str] = None
    created_at: Optional[str] = None


class NoticeApproveRequest(BaseModel):
    edited_reply: Optional[str] = None


class NoticeRegenerateRequest(BaseModel):
    notice_type: Optional[str] = None
    notice_blueprint_id: Optional[str] = None


NOTICE_TYPE_DISPLAY = {
    "143_1": "Section 143(1) - Income Tax Intimation",
    "148": "Section 148 - Reopening Notice",
    "asmt_10": "ASMT-10 - GST Scrutiny",
    "drc_01": "DRC-01 - GST Demand / Show Cause",
    "271_1c": "Section 271(1)(c) - Penalty Notice",
    "156": "Section 156 Tax Demand",
    "traces": "TRACES TDS Default Notice",
    "26qb": "Section 194IA Property TDS Notice",
    "other": "Other / Generic Notice",
}

VALID_NOTICE_TYPES = set(NOTICE_TYPE_DISPLAY.keys())

# Sentinel value for custom blueprint-based notice processing
CUSTOM_NOTICE_TYPE = "custom"
