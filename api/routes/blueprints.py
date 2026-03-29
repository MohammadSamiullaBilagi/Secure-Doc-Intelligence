import logging
from typing import Annotated, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.dependencies import get_current_user
from db.database import get_db
from db.models.core import User, Blueprint as BlueprintModel
from db.models.billing import CreditActionType, Subscription
from services.credits_service import CreditsService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/blueprints", tags=["blueprints"])


class BlueprintCheckInput(BaseModel):
    check_id: str
    focus: str
    rule: str


class CreateBlueprintRequest(BaseModel):
    name: str
    description: str
    checks: List[BlueprintCheckInput]
    category: str = "audit"  # "audit" or "notice"


class BlueprintResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    rules_json: list
    is_system: bool

    class Config:
        from_attributes = True


PROFESSIONAL_PLANS = {"professional", "enterprise"}


async def _get_user_plan_and_credits(user_id, db: AsyncSession) -> tuple:
    """Returns (plan, credits_balance) for the user."""
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        return "free_trial", 0
    return sub.plan, sub.credits_balance


@router.get("")
async def list_blueprints(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    category: Optional[str] = None,
):
    """List blueprints. Professional+ and free_trial with credits see system + own blueprints.

    Optional ?category=audit or ?category=notice to filter by type.
    """
    plan, credits = await _get_user_plan_and_credits(current_user.id, db)

    # Admins bypass plan restrictions
    # Allow professional+, OR free_trial users with remaining credits
    if not current_user.is_admin and plan not in PROFESSIONAL_PLANS and not (plan == "free_trial" and credits > 0):
        return []

    query = select(BlueprintModel).where(
        (BlueprintModel.user_id == current_user.id) | (BlueprintModel.user_id.is_(None))
    )
    if category:
        query = query.where(BlueprintModel.category == category)
    result = await db.execute(query)
    blueprints = result.scalars().all()

    return [
        {
            "id": str(bp.id),
            "name": bp.name,
            "description": bp.description,
            "checks_count": len(bp.rules_json) if bp.rules_json else 0,
            "is_system": bp.user_id is None,
            "category": getattr(bp, 'category', 'audit'),
        }
        for bp in blueprints
    ]


@router.post("")
async def create_custom_blueprint(
    request: CreateBlueprintRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Create a custom compliance blueprint. Costs 2 credits. Professional+ or free_trial with credits."""
    plan, credits = await _get_user_plan_and_credits(current_user.id, db)
    if not current_user.is_admin and plan not in PROFESSIONAL_PLANS and not (plan == "free_trial" and credits > 0):
        raise HTTPException(
            403,
            {
                "error": "Professional plan required",
                "message": "Custom blueprints are available on Professional and Enterprise plans, or during your free trial.",
                "current_plan": plan,
            },
        )

    if request.category not in ("audit", "notice"):
        raise HTTPException(400, "category must be 'audit' or 'notice'")

    if not request.checks or len(request.checks) == 0:
        raise HTTPException(400, "Blueprint must have at least one check")

    # Deduct 2 credits
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.BLUEPRINT_CREATE,
        db,
        description=f"Custom blueprint: {request.name}",
    )

    # Convert checks to JSON format matching BlueprintCheck schema
    rules_json = [
        {"check_id": c.check_id, "focus": c.focus, "rule": c.rule}
        for c in request.checks
    ]

    new_bp = BlueprintModel(
        user_id=current_user.id,
        name=request.name,
        description=request.description,
        rules_json=rules_json,
        category=request.category,
    )
    db.add(new_bp)
    await db.commit()
    await db.refresh(new_bp)

    logger.info(f"Custom blueprint created: {new_bp.name} ({len(rules_json)} checks)")
    return {
        "id": str(new_bp.id),
        "name": new_bp.name,
        "description": new_bp.description,
        "checks_count": len(rules_json),
        "category": new_bp.category,
        "message": f"Blueprint '{new_bp.name}' created with {len(rules_json)} checks",
    }


@router.delete("/{blueprint_id}")
async def delete_blueprint(
    blueprint_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Delete a user's custom blueprint (cannot delete system blueprints)."""
    plan, credits = await _get_user_plan_and_credits(current_user.id, db)
    if not current_user.is_admin and plan not in PROFESSIONAL_PLANS and not (plan == "free_trial" and credits > 0):
        raise HTTPException(
            403,
            {
                "error": "Professional plan required",
                "current_plan": plan,
            },
        )

    query = select(BlueprintModel).where(
        BlueprintModel.id == blueprint_id,
        BlueprintModel.user_id == current_user.id,
    )
    result = await db.execute(query)
    bp = result.scalar_one_or_none()

    if not bp:
        raise HTTPException(404, "Blueprint not found or you don't have permission")

    await db.delete(bp)
    await db.commit()
    return {"message": f"Blueprint '{bp.name}' deleted"}
