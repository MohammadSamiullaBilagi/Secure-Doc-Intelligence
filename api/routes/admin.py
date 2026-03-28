"""Admin dashboard API — analytics, user management, revenue insights."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db, require_admin
from db.models.core import User, AuditJob
from db.models.billing import Subscription, CreditTransaction, CreditActionType
from db.models.feedback import Feedback

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Plan pricing for MRR estimation
# ---------------------------------------------------------------------------
PLAN_PRICING = {
    "starter": 499,
    "professional": 999,
    "enterprise": 2499,
}


@router.get("/overview")
async def admin_overview(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Dashboard summary — cards for total users, activity, plans."""
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_users = (await db.execute(
        select(func.count(User.id)).where(User.is_active == True)
    )).scalar() or 0

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_signups = (await db.execute(
        select(func.count(User.id)).where(User.created_at >= week_ago)
    )).scalar() or 0

    total_audits = (await db.execute(select(func.count(AuditJob.id)))).scalar() or 0
    total_feedback = (await db.execute(select(func.count(Feedback.id)))).scalar() or 0

    plan_rows = (await db.execute(
        select(Subscription.plan, func.count(Subscription.id))
        .where(Subscription.is_active == True)
        .group_by(Subscription.plan)
    )).all()

    plans = {row[0]: row[1] for row in plan_rows}

    return {
        "total_users": total_users,
        "active_users": active_users,
        "recent_signups_7d": recent_signups,
        "total_audits": total_audits,
        "total_feedback": total_feedback,
        "plans": plans,
    }


@router.get("/usage")
async def feature_usage(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    period: str = Query("30d", pattern="^(7d|30d|90d|all)$"),
):
    """Feature usage counts from credit transactions."""
    period_map = {"7d": 7, "30d": 30, "90d": 90}

    query = (
        select(
            CreditTransaction.action,
            func.count(CreditTransaction.id),
            func.sum(func.abs(CreditTransaction.credits_delta)),
        )
        .where(CreditTransaction.credits_delta < 0)
    )

    if period != "all":
        since = datetime.now(timezone.utc) - timedelta(days=period_map[period])
        query = query.where(CreditTransaction.created_at >= since)

    query = query.group_by(CreditTransaction.action)
    result = (await db.execute(query)).all()

    features = [
        {
            "action": row[0],
            "count": row[1],
            "total_credits_consumed": abs(row[2]) if row[2] else 0,
        }
        for row in result
    ]

    return {"period": period, "features": sorted(features, key=lambda f: f["count"], reverse=True)}


@router.get("/usage/timeseries")
async def usage_timeseries(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=7, le=90),
):
    """Daily action counts for trend charting."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    result = (await db.execute(
        select(
            func.date(CreditTransaction.created_at).label("day"),
            func.count(CreditTransaction.id),
        )
        .where(CreditTransaction.credits_delta < 0)
        .where(CreditTransaction.created_at >= since)
        .group_by(func.date(CreditTransaction.created_at))
        .order_by(func.date(CreditTransaction.created_at))
    )).all()

    return {"days": days, "data": [{"date": str(row[0]), "actions": row[1]} for row in result]}


@router.get("/usage/top-users")
async def top_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    """Top users ranked by total actions taken."""
    result = (await db.execute(
        select(
            User.email,
            func.count(CreditTransaction.id).label("total_actions"),
            func.sum(func.abs(CreditTransaction.credits_delta)).label("credits_used"),
        )
        .join(CreditTransaction, CreditTransaction.user_id == User.id)
        .where(CreditTransaction.credits_delta < 0)
        .group_by(User.email)
        .order_by(func.count(CreditTransaction.id).desc())
        .limit(limit)
    )).all()

    return [
        {"email": row[0], "total_actions": row[1], "credits_used": abs(row[2]) if row[2] else 0}
        for row in result
    ]


@router.get("/users/growth")
async def user_growth(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=7, le=365),
):
    """Daily signup counts for growth chart."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    result = (await db.execute(
        select(
            func.date(User.created_at).label("day"),
            func.count(User.id),
        )
        .where(User.created_at >= since)
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at))
    )).all()

    return {"days": days, "data": [{"date": str(row[0]), "signups": row[1]} for row in result]}


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Individual user detail with recent transactions."""
    try:
        uid = UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user ID format")

    result = (await db.execute(
        select(User, Subscription)
        .outerjoin(Subscription, Subscription.user_id == User.id)
        .where(User.id == uid)
    )).first()

    if not result:
        raise HTTPException(status_code=404, detail="User not found")

    user, sub = result

    txns = (await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == uid)
        .order_by(CreditTransaction.created_at.desc())
        .limit(20)
    )).scalars().all()

    return {
        "id": str(user.id),
        "email": user.email,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "plan": sub.plan if sub else "none",
        "credits_balance": sub.credits_balance if sub else 0,
        "credits_monthly_quota": sub.credits_monthly_quota if sub else 0,
        "recent_transactions": [
            {
                "action": t.action,
                "credits_delta": t.credits_delta,
                "description": t.description,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in txns
        ],
    }


@router.get("/users")
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Paginated user list with subscription info."""
    query = (
        select(User, Subscription)
        .outerjoin(Subscription, Subscription.user_id == User.id)
    )
    count_query = select(func.count(User.id))

    if search:
        query = query.where(User.email.ilike(f"%{search}%"))
        count_query = count_query.where(User.email.ilike(f"%{search}%"))

    query = query.order_by(User.created_at.desc()).limit(limit).offset(offset)
    result = (await db.execute(query)).all()
    total = (await db.execute(count_query)).scalar() or 0

    users = [
        {
            "id": str(user.id),
            "email": user.email,
            "is_active": user.is_active,
            "is_admin": user.is_admin,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "plan": sub.plan if sub else "none",
            "credits_balance": sub.credits_balance if sub else 0,
        }
        for user, sub in result
    ]

    return {"total": total, "users": users}


@router.get("/revenue")
async def revenue_analytics(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Subscription and revenue breakdown with estimated MRR."""
    plan_rows = (await db.execute(
        select(Subscription.plan, func.count(Subscription.id))
        .where(Subscription.is_active == True)
        .group_by(Subscription.plan)
    )).all()

    active_subs = {row[0]: row[1] for row in plan_rows}

    topup_row = (await db.execute(
        select(
            func.count(CreditTransaction.id),
            func.sum(CreditTransaction.credits_delta),
        )
        .where(CreditTransaction.action == CreditActionType.TOPUP.value)
    )).first()

    estimated_mrr = sum(
        active_subs.get(plan, 0) * price
        for plan, price in PLAN_PRICING.items()
    )

    return {
        "active_subscriptions": active_subs,
        "total_topups": topup_row[0] if topup_row else 0,
        "total_topup_credits": topup_row[1] if topup_row and topup_row[1] else 0,
        "estimated_mrr": estimated_mrr,
    }
