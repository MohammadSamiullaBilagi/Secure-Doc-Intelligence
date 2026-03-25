from typing import Annotated, List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.dependencies import get_current_user
from db.database import get_db
from db.models.core import User
from db.models.billing import CreditTransaction, CreditActionType, PlanTier, Subscription
from services.credits_service import CreditsService, PLAN_CREDITS, PLAN_PRICES_PAISE, CREDIT_COSTS

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


class TopupRequest(BaseModel):
    amount: int  # Number of credits to add


class UpgradePlanRequest(BaseModel):
    plan: str  # "starter", "professional", "enterprise"
    razorpay_subscription_id: Optional[str] = None


# ============ Balance & Usage ============

@router.get("/balance")
async def get_balance(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Returns current credit balance, plan info, and usage stats."""
    return await CreditsService.get_balance(current_user.id, db)


@router.get("/transactions")
async def get_transactions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    """Returns recent credit transaction history for the user."""
    query = (
        select(CreditTransaction)
        .where(CreditTransaction.user_id == current_user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    txns = result.scalars().all()

    return [
        {
            "action": t.action,
            "credits_delta": t.credits_delta,
            "credits_after": t.credits_after,
            "description": t.description,
            "timestamp": t.created_at,
        }
        for t in txns
    ]


# ============ Plans & Pricing ============

@router.get("/plans")
async def get_available_plans():
    """Returns all available subscription plans with pricing."""
    plans = []
    for tier in PlanTier:
        if tier == PlanTier.PAY_AS_YOU_GO:
            plans.append({
                "id": tier.value,
                "name": tier.value.replace("_", " ").title(),
                "credits": 0,
                "price_inr": 10,  # ₹10 per credit
                "price_label": "₹10/credit",
            })
        else:
            price_paise = PLAN_PRICES_PAISE.get(tier, 0)
            plans.append({
                "id": tier.value,
                "name": tier.value.replace("_", " ").title(),
                "credits": PLAN_CREDITS.get(tier, 0),
                "price_inr": price_paise // 100 if price_paise else 0,
                "price_label": f"₹{price_paise // 100}/month" if price_paise else "Free",
            })
    return plans


CREDIT_COST_DISPLAY = {
    "document_scan": {"label": "Document Compliance Scan", "credits": 0, "category": "analysis"},
    "chat_query": {"label": "AI Chat Query", "credits": 0, "category": "chat"},
    "blueprint_create": {"label": "Blueprint Creation", "credits": 0, "category": "analysis"},
    "notice_reply": {"label": "Notice Reply Assistant", "credits": 0, "category": "notices"},
    "notice_regenerate": {"label": "Notice Re-generation", "credits": 0, "category": "notices"},
    "gstr_recon": {"label": "GSTR-2B vs Purchase Register Reconciliation", "credits": 0, "category": "gst"},
    "bank_analysis": {"label": "Bank Statement Analyzer", "credits": 0, "category": "analysis"},
    "capital_gains_analysis": {"label": "Capital Gains Analysis", "credits": 0, "category": "tax"},
    "gstr9_recon": {"label": "GSTR-9 Annual Return Reconciliation", "credits": 0, "category": "gst"},
    "depreciation_calc": {"label": "Depreciation Calculator", "credits": 0, "category": "tax"},
    "advance_tax_calc": {"label": "Advance Tax Calculator", "credits": 0, "category": "tax"},
}

# Populate actual costs from CREDIT_COSTS (single source of truth)
for action_type, cost in CREDIT_COSTS.items():
    if action_type.value in CREDIT_COST_DISPLAY:
        CREDIT_COST_DISPLAY[action_type.value]["credits"] = cost


@router.get("/credit-costs")
async def get_credit_costs():
    """Returns credit costs for all features — used by frontend pricing/billing pages."""
    return {
        "costs": CREDIT_COST_DISPLAY,
        "plans": [
            {
                "id": tier.value,
                "name": tier.value.replace("_", " ").title(),
                "credits": PLAN_CREDITS.get(tier, 0),
                "price_inr": PLAN_PRICES_PAISE.get(tier, 0) // 100,
                "price_label": f"₹{PLAN_PRICES_PAISE[tier] // 100}/month" if tier in PLAN_PRICES_PAISE else "Free",
            }
            for tier in PlanTier
            if tier != PlanTier.PAY_AS_YOU_GO
        ],
    }


# Feature access matrix — single source of truth for plan gating
FEATURE_ACCESS = {
    "document_upload": {
        "label": "Document Upload",
        "min_plan": "free_trial",
        "description": "Upload and scan documents for compliance",
    },
    "chat": {
        "label": "AI Chat",
        "min_plan": "free_trial",
        "description": "Ask questions about your uploaded documents",
    },
    "compliance_scan": {
        "label": "Compliance Scan",
        "min_plan": "free_trial",
        "description": "Run AI-powered compliance checks on documents",
    },
    "advance_tax": {
        "label": "Advance Tax Calculator",
        "min_plan": "free_trial",
        "description": "Section 234B/C advance tax interest computation",
        "credit_gated": True,
    },
    "bank_analysis": {
        "label": "Bank Statement Analyzer",
        "min_plan": "free_trial",
        "description": "Analyze bank statements for statutory thresholds",
        "credit_gated": True,
    },
    "capital_gains": {
        "label": "Capital Gains Analysis",
        "min_plan": "free_trial",
        "description": "Compute Schedule CG from broker statements",
        "credit_gated": True,
    },
    "depreciation": {
        "label": "Depreciation Calculator",
        "min_plan": "free_trial",
        "description": "IT Act & Companies Act depreciation schedules",
        "credit_gated": True,
    },
    "gstr2b_recon": {
        "label": "GSTR-2B Reconciliation",
        "min_plan": "free_trial",
        "description": "GSTR-2B vs Purchase Register reconciliation",
        "credit_gated": True,
    },
    "gstr9_recon": {
        "label": "GSTR-9 Reconciliation",
        "min_plan": "free_trial",
        "description": "GSTR-9 annual return pre-filling reconciliation",
        "credit_gated": True,
    },
    "blueprints": {
        "label": "Compliance Blueprints",
        "min_plan": "free_trial",
        "description": "Create and manage custom compliance blueprints",
        "credit_gated": True,
    },
    "notice_reply": {
        "label": "Notice Reply Assistant",
        "min_plan": "free_trial",
        "description": "AI-drafted replies to IT/GST notices",
        "credit_gated": True,
    },
    "bulk_upload": {
        "label": "Bulk Upload",
        "min_plan": "free_trial",
        "description": "Upload multiple documents at once with client tagging",
        "credit_gated": True,
    },
    "client_management": {
        "label": "Client Management",
        "min_plan": "free_trial",
        "description": "Manage clients, link documents, compliance dashboard",
        "credit_gated": True,
    },
    "tax_calendar": {
        "label": "Tax Calendar & Reminders",
        "min_plan": "free_trial",
        "description": "Track tax deadlines and set automated reminders",
        "credit_gated": True,
    },
    "export": {
        "label": "Export (CSV / Tally / Zoho)",
        "min_plan": "free_trial",
        "description": "Export reports in CSV, Tally XML, or Zoho JSON format",
        "credit_gated": True,
    },
}

# Plan hierarchy for comparison
_PLAN_ORDER = {"free_trial": 0, "starter": 1, "professional": 2, "enterprise": 3}


@router.get("/feature-access")
async def get_feature_access(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Returns feature access matrix for the user's current plan."""
    # Use get_or_create to ensure subscription exists (auto-creates free trial if missing)
    sub = await CreditsService.get_or_create_subscription(current_user.id, db)
    current_plan = sub.plan
    current_rank = _PLAN_ORDER.get(current_plan, 0)
    credits_balance = sub.credits_balance

    # Admins get access to everything
    is_admin = current_user.is_admin

    features = {}
    for key, info in FEATURE_ACCESS.items():
        min_rank = _PLAN_ORDER.get(info["min_plan"], 0)
        is_credit_gated = info.get("credit_gated", False)

        if is_admin:
            accessible = True
        elif is_credit_gated and current_plan == "free_trial":
            accessible = credits_balance > 0
        else:
            accessible = current_rank >= min_rank

        features[key] = {
            **info,
            "accessible": accessible,
            "upgrade_to": info["min_plan"] if not accessible else None,
        }

    return {
        "current_plan": "admin" if is_admin else current_plan,
        "features": features,
    }


@router.post("/upgrade")
async def upgrade_plan(
    request: UpgradePlanRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Upgrade the user's plan after successful Razorpay payment."""
    try:
        new_plan = PlanTier(request.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {request.plan}")

    return await CreditsService.upgrade_plan(
        current_user.id, new_plan, db,
        razorpay_subscription_id=request.razorpay_subscription_id,
    )


# ============ Top-Up Credits ============

@router.post("/topup")
async def topup_credits(
    request: TopupRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Manually top-up credits (call after Razorpay payment confirmation)."""
    if request.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")

    balance = await CreditsService.add_credits(
        current_user.id,
        request.amount,
        CreditActionType.TOPUP,
        db,
        description=f"Manual top-up: +{request.amount} credits",
    )
    return {"message": f"Added {request.amount} credits", "new_balance": balance}
