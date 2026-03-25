import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from db.models.billing import (
    Subscription, CreditTransaction, CreditActionType, PlanTier
)
from db.models.core import User

logger = logging.getLogger(__name__)

# Credit costs for each action
CREDIT_COSTS = {
    CreditActionType.DOCUMENT_SCAN: 3,
    CreditActionType.CHAT_QUERY: 1,
    CreditActionType.WEB_RESEARCH: 1,
    CreditActionType.BLUEPRINT_CREATE: 2,
    CreditActionType.NOTICE_REPLY: 5,
    CreditActionType.NOTICE_REGENERATE: 1,
    CreditActionType.GSTR_RECON: 10,
    CreditActionType.BANK_ANALYSIS: 8,
    CreditActionType.CAPITAL_GAINS_ANALYSIS: 10,
    CreditActionType.GSTR9_RECON: 15,
    CreditActionType.DEPRECIATION_CALC: 8,
    CreditActionType.ADVANCE_TAX_CALC: 2,
}

# Monthly credits per plan tier
PLAN_CREDITS = {
    PlanTier.FREE_TRIAL: 75,
    PlanTier.STARTER: 100,
    PlanTier.PROFESSIONAL: 300,
    PlanTier.ENTERPRISE: 1000,
}

# Plan prices in paise (for Razorpay)
PLAN_PRICES_PAISE = {
    PlanTier.STARTER: 49900,       # ₹499
    PlanTier.PROFESSIONAL: 99900,  # ₹999
    PlanTier.ENTERPRISE: 249900,   # ₹2,499
}


class CreditsService:
    """Core business logic for the credits/billing system."""

    @staticmethod
    async def get_or_create_subscription(user_id, db: AsyncSession) -> Subscription:
        """Get existing subscription or auto-create free trial for new users."""
        query = select(Subscription).where(Subscription.user_id == user_id)
        result = await db.execute(query)
        sub = result.scalar_one_or_none()

        if not sub:
            sub = Subscription(
                user_id=user_id,
                plan=PlanTier.FREE_TRIAL.value,
                credits_balance=PLAN_CREDITS[PlanTier.FREE_TRIAL],
                credits_monthly_quota=PLAN_CREDITS[PlanTier.FREE_TRIAL],
            )
            db.add(sub)

            # Log the initial credit grant
            txn = CreditTransaction(
                user_id=user_id,
                action=CreditActionType.SUBSCRIPTION_CREDIT.value,
                credits_delta=PLAN_CREDITS[PlanTier.FREE_TRIAL],
                credits_after=PLAN_CREDITS[PlanTier.FREE_TRIAL],
                description="Free trial credits granted on signup",
            )
            db.add(txn)
            await db.commit()
            await db.refresh(sub)

        return sub

    @staticmethod
    async def check_and_deduct(
        user_id, action: CreditActionType, db: AsyncSession, description: str = ""
    ) -> int:
        """Check balance, deduct credits, log transaction.

        Admin users bypass credit deduction entirely.
        Returns remaining balance after deduction.
        Raises HTTP 402 if insufficient credits.
        """
        # Admin users get unlimited access — no credit deduction
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        if user and user.is_admin:
            logger.info(f"CREDITS: admin user={user_id} action={action.value} — skipped (admin)")
            sub = await CreditsService.get_or_create_subscription(user_id, db)
            return sub.credits_balance

        sub = await CreditsService.get_or_create_subscription(user_id, db)
        cost = CREDIT_COSTS.get(action, 1)

        if sub.credits_balance < cost:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Insufficient credits",
                    "required": cost,
                    "balance": sub.credits_balance,
                    "action": action.value,
                    "plan": sub.plan,
                },
            )

        sub.credits_balance -= cost

        txn = CreditTransaction(
            user_id=user_id,
            action=action.value,
            credits_delta=-cost,
            credits_after=sub.credits_balance,
            description=description or f"{action.value}",
        )
        db.add(txn)
        await db.commit()

        logger.info(
            f"CREDITS: user={user_id} action={action.value} "
            f"cost=-{cost} balance={sub.credits_balance}"
        )
        return sub.credits_balance

    @staticmethod
    async def add_credits(
        user_id, amount: int, action: CreditActionType,
        db: AsyncSession, description: str = ""
    ) -> int:
        """Add credits to user's balance (subscription renewal, topup, referral).
        
        Returns new balance after addition.
        """
        sub = await CreditsService.get_or_create_subscription(user_id, db)
        sub.credits_balance += amount

        txn = CreditTransaction(
            user_id=user_id,
            action=action.value,
            credits_delta=amount,
            credits_after=sub.credits_balance,
            description=description or f"{action.value}: +{amount}",
        )
        db.add(txn)
        await db.commit()

        logger.info(
            f"CREDITS: user={user_id} action={action.value} "
            f"added=+{amount} balance={sub.credits_balance}"
        )
        return sub.credits_balance

    @staticmethod
    async def get_balance(user_id, db: AsyncSession) -> dict:
        """Return current balance, plan info, and usage summary."""
        sub = await CreditsService.get_or_create_subscription(user_id, db)

        # Check if user is admin
        user_result = await db.execute(select(User).where(User.id == user_id))
        user = user_result.scalar_one_or_none()
        is_admin = user.is_admin if user else False

        # Count total credits used this billing cycle
        usage_query = (
            select(func.count(CreditTransaction.id))
            .where(
                CreditTransaction.user_id == user_id,
                CreditTransaction.credits_delta < 0,
            )
        )
        usage_result = await db.execute(usage_query)
        total_actions = usage_result.scalar() or 0

        return {
            "plan": "admin" if is_admin else sub.plan,
            "credits_balance": 999999 if is_admin else sub.credits_balance,
            "credits_monthly_quota": sub.credits_monthly_quota,
            "total_actions_taken": total_actions,
            "is_active": True if is_admin else sub.is_active,
            "is_admin": is_admin,
        }

    @staticmethod
    async def upgrade_plan(
        user_id, new_plan: PlanTier, db: AsyncSession,
        razorpay_subscription_id: str = None
    ) -> dict:
        """Upgrade user's plan and grant new monthly credits."""
        sub = await CreditsService.get_or_create_subscription(user_id, db)

        old_plan = sub.plan
        new_quota = PLAN_CREDITS.get(new_plan, 100)

        sub.plan = new_plan.value
        sub.credits_monthly_quota = new_quota
        sub.credits_balance += new_quota  # Grant new credits immediately
        if razorpay_subscription_id:
            sub.razorpay_subscription_id = razorpay_subscription_id

        txn = CreditTransaction(
            user_id=user_id,
            action=CreditActionType.SUBSCRIPTION_CREDIT.value,
            credits_delta=new_quota,
            credits_after=sub.credits_balance,
            description=f"Plan upgrade: {old_plan} → {new_plan.value} (+{new_quota} credits)",
        )
        db.add(txn)
        await db.commit()

        return {
            "plan": sub.plan,
            "credits_balance": sub.credits_balance,
            "credits_added": new_quota,
        }
