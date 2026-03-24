import uuid
from typing import Optional, Literal
from datetime import date, datetime
from pydantic import BaseModel


class TaxDeadlineResponse(BaseModel):
    id: uuid.UUID
    title: str
    due_date: date
    category: str
    description: Optional[str] = None
    days_remaining: int = 0

    model_config = {"from_attributes": True}


class ReminderCreate(BaseModel):
    deadline_id: uuid.UUID
    remind_days_before: int = 3
    channel: Literal["email", "whatsapp"] = "email"


class ReminderResponse(BaseModel):
    id: uuid.UUID
    deadline: TaxDeadlineResponse
    remind_days_before: int
    channel: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
