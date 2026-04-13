"""Schemas for DPDPA legal compliance endpoints."""

from pydantic import BaseModel
from typing import Optional


class ConsentRequest(BaseModel):
    accepted: bool
    version: str


class ConsentStatusResponse(BaseModel):
    consent_accepted: bool
    consent_version: Optional[str] = None
    consent_accepted_at: Optional[str] = None
    current_version: str


class DataDeletionRequest(BaseModel):
    confirm: bool


class DataDeletionResponse(BaseModel):
    message: str
    summary: dict
