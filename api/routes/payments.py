import logging
import hmac
import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from db.database import get_db
from db.config import settings
from db.models.core import User
from db.models.billing import CreditActionType, PlanTier
from services.credits_service import CreditsService, PLAN_PRICES_PAISE, PLAN_CREDITS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


class CreateOrderRequest(BaseModel):
    plan: str  # "starter", "professional", "enterprise"


class CreateTopupOrderRequest(BaseModel):
    credits: int  # Number of credits to buy (e.g. 10, 25, 50)


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    plan: str


class VerifyTopupRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str
    credits: int


# ============ Create Razorpay Order ============

@router.post("/create-order")
async def create_order(
    request: CreateOrderRequest,
    current_user=Depends(get_current_user),
):
    """Creates a Razorpay order for the selected plan."""
    try:
        plan_tier = PlanTier(request.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {request.plan}")

    amount = PLAN_PRICES_PAISE.get(plan_tier)
    if not amount:
        raise HTTPException(status_code=400, detail="This plan doesn't have a price")

    # Lazy import — only needed when payments are actually used
    try:
        import razorpay

        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        order = client.order.create(
            {
                "amount": amount,
                "currency": "INR",
                "notes": {
                    "user_id": str(current_user.id),
                    "plan": request.plan,
                    "email": current_user.email,
                },
            }
        )
        logger.info(f"Razorpay order created: {order['id']} for {request.plan}")
        return {
            "order_id": order["id"],
            "amount": amount,
            "currency": "INR",
            "plan": request.plan,
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        }
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Razorpay SDK not installed. Run: pip install razorpay",
        )
    except Exception as e:
        logger.error(f"Razorpay order creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Payment error: {str(e)}")


# ============ Verify Payment & Activate Plan ============

@router.post("/verify")
async def verify_payment(
    request: VerifyPaymentRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verifies Razorpay payment signature and activates the plan."""
    # 1. Verify the Razorpay signature
    message = f"{request.razorpay_order_id}|{request.razorpay_payment_id}"
    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, request.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # 2. Activate the plan
    try:
        plan_tier = PlanTier(request.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid plan: {request.plan}")

    result = await CreditsService.upgrade_plan(
        current_user.id,
        plan_tier,
        db,
        razorpay_subscription_id=request.razorpay_payment_id,
    )

    logger.info(
        f"Payment verified for user {current_user.id}: {request.plan} activated"
    )
    return {
        "status": "success",
        "message": f"Plan upgraded to {request.plan}",
        **result,
    }


# ============ Razorpay Webhook (Server-to-Server) ============

@router.post("/webhook")
async def razorpay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Razorpay webhook for automatic payment confirmations.

    Verifies the X-Razorpay-Signature header to ensure the request
    genuinely came from Razorpay — prevents forged events from activating
    plans for free.
    """
    import json
    raw_body = await request.body()

    # Verify webhook signature — mandatory (reject if secret not configured)
    webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    if not webhook_secret:
        logger.error("RAZORPAY_WEBHOOK_SECRET not set — rejecting webhook for security")
        raise HTTPException(status_code=500, detail="Webhook secret not configured")

    signature = request.headers.get("X-Razorpay-Signature", "")
    expected = hmac.new(
        webhook_secret.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        logger.warning("Razorpay webhook: invalid signature — request rejected")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = json.loads(raw_body)
    event = payload.get("event", "")

    logger.info(f"Razorpay webhook received: {event}")

    if event == "payment.captured":
        payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
        notes = payment.get("notes", {})
        user_id = notes.get("user_id")
        plan = notes.get("plan")
        topup_credits = notes.get("topup_credits")

        if user_id and plan:
            try:
                plan_tier = PlanTier(plan)
                await CreditsService.upgrade_plan(user_id, plan_tier, db)
                logger.info(f"Webhook: Activated {plan} for user {user_id}")
            except Exception as e:
                logger.error(f"Webhook processing failed: {e}")
        elif user_id and topup_credits:
            try:
                await CreditsService.add_credits(
                    user_id, int(topup_credits), CreditActionType.TOPUP, db,
                    description=f"Razorpay top-up: +{topup_credits} credits"
                )
                logger.info(f"Webhook: Added {topup_credits} credits for user {user_id}")
            except Exception as e:
                logger.error(f"Webhook topup processing failed: {e}")

    return {"status": "ok"}


# ============ Credit Top-Up Orders ============

TOPUP_PRICE_PER_CREDIT_PAISE = 1000  # ₹10 per credit = 1000 paise


@router.post("/create-topup-order")
async def create_topup_order(
    request: CreateTopupOrderRequest,
    current_user=Depends(get_current_user),
):
    """Creates a Razorpay order for credit top-up purchases."""
    if request.credits <= 0:
        raise HTTPException(status_code=400, detail="Credits must be positive")
    if request.credits > 500:
        raise HTTPException(status_code=400, detail="Maximum 500 credits per top-up")

    amount = request.credits * TOPUP_PRICE_PER_CREDIT_PAISE  # ₹10 per credit

    try:
        import razorpay

        client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        order = client.order.create(
            {
                "amount": amount,
                "currency": "INR",
                "notes": {
                    "user_id": str(current_user.id),
                    "topup_credits": str(request.credits),
                    "email": current_user.email,
                    "type": "topup",
                },
            }
        )
        logger.info(f"Razorpay topup order created: {order['id']} for {request.credits} credits")
        return {
            "order_id": order["id"],
            "amount": amount,
            "currency": "INR",
            "credits": request.credits,
            "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        }
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="Razorpay SDK not installed. Run: pip install razorpay",
        )
    except Exception as e:
        logger.error(f"Razorpay topup order creation failed: {e}")
        raise HTTPException(status_code=500, detail=f"Payment error: {str(e)}")


@router.post("/verify-topup")
async def verify_topup(
    request: VerifyTopupRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verifies Razorpay payment and adds purchased credits to user balance."""
    # Verify signature
    message = f"{request.razorpay_order_id}|{request.razorpay_payment_id}"
    expected_signature = hmac.new(
        settings.RAZORPAY_KEY_SECRET.encode(),
        message.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_signature, request.razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid payment signature")

    # Add credits
    balance = await CreditsService.add_credits(
        current_user.id,
        request.credits,
        CreditActionType.TOPUP,
        db,
        description=f"Top-up purchase: +{request.credits} credits (₹{request.credits * 10})",
    )

    logger.info(f"Topup verified: +{request.credits} credits for user {current_user.id}")
    return {
        "status": "success",
        "message": f"Added {request.credits} credits",
        "credits_added": request.credits,
        "new_balance": balance,
    }

