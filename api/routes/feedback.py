from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from api.dependencies import get_current_user, require_admin
from db.database import get_db
from db.models.core import User
from db.models.feedback import Feedback
from schemas.feedback_schema import FeedbackCreate, FeedbackResponse

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])


@router.post("/", status_code=201, response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Submit feedback — available to all authenticated users."""
    feedback = Feedback(
        user_id=current_user.id,
        category=body.category,
        subject=body.subject,
        message=body.message,
        page=body.page,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)

    return FeedbackResponse(
        id=feedback.id,
        user_id=feedback.user_id,
        user_email=current_user.email,
        category=feedback.category,
        subject=feedback.subject,
        message=feedback.message,
        page=feedback.page,
        created_at=feedback.created_at,
    )


@router.get("/mine", response_model=list[FeedbackResponse])
async def get_my_feedback(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Get the current user's own feedback submissions."""
    result = await db.execute(
        select(Feedback)
        .where(Feedback.user_id == current_user.id)
        .order_by(Feedback.created_at.desc())
    )
    feedbacks = result.scalars().all()
    return [
        FeedbackResponse(
            id=f.id,
            user_id=f.user_id,
            user_email=current_user.email,
            category=f.category,
            subject=f.subject,
            message=f.message,
            page=f.page,
            created_at=f.created_at,
        )
        for f in feedbacks
    ]


# ── Admin-only endpoints ──────────────────────────────────────────────

@router.get("/admin/all", response_model=list[FeedbackResponse])
async def get_all_feedback(
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    category: Optional[str] = Query(None, description="Filter by category"),
    page_filter: Optional[str] = Query(None, alias="page", description="Filter by page"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Get ALL feedback from ALL users — admin only."""
    query = select(Feedback, User.email).join(User, Feedback.user_id == User.id)

    if category:
        query = query.where(Feedback.category == category)
    if page_filter:
        query = query.where(Feedback.page == page_filter)

    query = query.order_by(Feedback.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    rows = result.all()

    return [
        FeedbackResponse(
            id=f.id,
            user_id=f.user_id,
            user_email=email,
            category=f.category,
            subject=f.subject,
            message=f.message,
            page=f.page,
            created_at=f.created_at,
        )
        for f, email in rows
    ]


@router.get("/admin/stats")
async def get_feedback_stats(
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
):
    """Feedback summary stats — admin only."""
    total = await db.execute(select(func.count(Feedback.id)))
    by_category = await db.execute(
        select(Feedback.category, func.count(Feedback.id))
        .group_by(Feedback.category)
    )
    by_page = await db.execute(
        select(Feedback.page, func.count(Feedback.id))
        .group_by(Feedback.page)
        .order_by(func.count(Feedback.id).desc())
        .limit(10)
    )

    return {
        "total": total.scalar() or 0,
        "by_category": {row[0]: row[1] for row in by_category.all()},
        "top_pages": {(row[0] or "unknown"): row[1] for row in by_page.all()},
    }


@router.delete("/admin/{feedback_id}", status_code=204)
async def delete_feedback(
    feedback_id: str,
    current_user: Annotated[User, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
):
    """Delete a feedback entry — admin only."""
    from uuid import UUID
    try:
        fid = UUID(feedback_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid feedback ID")

    result = await db.execute(select(Feedback).where(Feedback.id == fid))
    feedback = result.scalar_one_or_none()
    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    await db.delete(feedback)
    await db.commit()
