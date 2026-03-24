from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, Literal


class FeedbackCreate(BaseModel):
    """Payload for submitting feedback."""
    category: Literal["feature_request", "bug_report", "general"] = Field(
        ..., description="Type of feedback"
    )
    subject: str = Field(..., min_length=3, max_length=255)
    message: str = Field(..., min_length=10, max_length=5000)
    page: Optional[str] = Field(
        None, max_length=255, description="Page the feedback was submitted from"
    )


class FeedbackResponse(BaseModel):
    """Response payload for a feedback entry."""
    id: UUID
    user_id: UUID
    user_email: Optional[str] = None
    category: str
    subject: str
    message: str
    page: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
