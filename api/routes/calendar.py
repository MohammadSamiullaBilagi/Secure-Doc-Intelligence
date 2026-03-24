import logging
from typing import Annotated
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.dependencies import get_current_user, require_enterprise
from db.database import get_db
from db.models.core import User
from db.models.calendar import TaxDeadline, UserReminder
from schemas.calendar_schema import TaxDeadlineResponse, ReminderCreate, ReminderResponse
from services.calendar_service import CalendarService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])


@router.get("/deadlines", response_model=list[TaxDeadlineResponse])
async def get_upcoming_deadlines(
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
    days_ahead: int = Query(30, ge=1, le=365, description="Number of days to look ahead"),
):
    """Get upcoming tax deadlines within the specified number of days."""
    deadlines = await CalendarService.get_upcoming_deadlines(days_ahead, db)
    today = date.today()

    return [
        TaxDeadlineResponse(
            id=d.id,
            title=d.title,
            due_date=d.due_date,
            category=d.category,
            description=d.description,
            days_remaining=(d.due_date - today).days,
        )
        for d in deadlines
    ]


@router.post("/reminders", response_model=ReminderResponse, status_code=201)
async def create_reminder(
    body: ReminderCreate,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """Create a reminder for a specific tax deadline."""
    # Reject WhatsApp — not yet implemented
    if body.channel == "whatsapp":
        raise HTTPException(400, "WhatsApp reminders not yet implemented. Use 'email' channel.")

    # Verify deadline exists
    deadline_result = await db.execute(
        select(TaxDeadline).where(TaxDeadline.id == body.deadline_id)
    )
    deadline = deadline_result.scalar_one_or_none()
    if not deadline:
        raise HTTPException(404, "Tax deadline not found")

    # Check for duplicate
    existing = await db.execute(
        select(UserReminder).where(
            UserReminder.user_id == current_user.id,
            UserReminder.deadline_id == body.deadline_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, "Reminder already exists for this deadline")

    reminder = UserReminder(
        user_id=current_user.id,
        deadline_id=body.deadline_id,
        remind_days_before=body.remind_days_before,
        channel=body.channel,
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)

    today = date.today()
    return ReminderResponse(
        id=reminder.id,
        deadline=TaxDeadlineResponse(
            id=deadline.id,
            title=deadline.title,
            due_date=deadline.due_date,
            category=deadline.category,
            description=deadline.description,
            days_remaining=(deadline.due_date - today).days,
        ),
        remind_days_before=reminder.remind_days_before,
        channel=reminder.channel,
        is_active=reminder.is_active,
        created_at=reminder.created_at,
    )


@router.get("/reminders", response_model=list[ReminderResponse])
async def list_reminders(
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """List all active reminders for the current user."""
    reminders = await CalendarService.get_user_reminders(current_user.id, db)
    today = date.today()

    responses = []
    for r in reminders:
        deadline = r.deadline  # already eager-loaded via selectinload
        if not deadline:
            continue

        responses.append(ReminderResponse(
            id=r.id,
            deadline=TaxDeadlineResponse(
                id=deadline.id,
                title=deadline.title,
                due_date=deadline.due_date,
                category=deadline.category,
                description=deadline.description,
                days_remaining=(deadline.due_date - today).days,
            ),
            remind_days_before=r.remind_days_before,
            channel=r.channel,
            is_active=r.is_active,
            created_at=r.created_at,
        ))

    return responses


@router.delete("/reminders/{reminder_id}", status_code=204)
async def delete_reminder(
    reminder_id: UUID,
    current_user: Annotated[User, Depends(require_enterprise)],
    db: AsyncSession = Depends(get_db),
):
    """Delete a reminder (must be owned by current user)."""
    result = await db.execute(
        select(UserReminder).where(
            UserReminder.id == reminder_id,
            UserReminder.user_id == current_user.id,
        )
    )
    reminder = result.scalar_one_or_none()
    if not reminder:
        raise HTTPException(404, "Reminder not found")

    await db.delete(reminder)
    await db.commit()
