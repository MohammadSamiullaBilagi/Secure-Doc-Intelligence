import uuid
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Boolean, ForeignKey, Uuid, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base, TimestampMixin


class PlanTier(str, enum.Enum):
    FREE_TRIAL = "free_trial"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
    PAY_AS_YOU_GO = "pay_as_you_go"


class CreditActionType(str, enum.Enum):
    DOCUMENT_SCAN = "document_scan"       # -3 credits
    CHAT_QUERY = "chat_query"             # -1 credit
    WEB_RESEARCH = "web_research"         # -1 credit
    BLUEPRINT_CREATE = "blueprint_create" # -2 credits
    SUBSCRIPTION_CREDIT = "subscription"  # + monthly credits
    TOPUP = "topup"                       # + purchased credits
    REFERRAL_BONUS = "referral"           # + bonus credits
    NOTICE_REPLY = "notice_reply"         # -5 credits
    NOTICE_REGENERATE = "notice_regenerate"  # -1 credit
    GSTR_RECON = "gstr_recon"              # -10 credits
    BANK_ANALYSIS = "bank_analysis"        # -8 credits
    CAPITAL_GAINS_ANALYSIS = "capital_gains_analysis"  # -10 credits
    GSTR9_RECON = "gstr9_recon"                        # -15 credits
    DEPRECIATION_CALC = "depreciation_calc"            # -8 credits
    ADVANCE_TAX_CALC = "advance_tax_calc"              # -2 credits


class Subscription(Base, TimestampMixin):
    """Tracks the user's active subscription plan and credit balance."""
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    plan: Mapped[str] = mapped_column(String(50), default=PlanTier.FREE_TRIAL.value)
    credits_balance: Mapped[int] = mapped_column(Integer, default=75)
    credits_monthly_quota: Mapped[int] = mapped_column(Integer, default=75)
    billing_cycle_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    razorpay_subscription_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationships
    user: Mapped["User"] = relationship("User", backref="subscription")


class CreditTransaction(Base, TimestampMixin):
    """Immutable audit log of every credit change."""
    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(50))
    credits_delta: Mapped[int] = mapped_column(Integer)
    credits_after: Mapped[int] = mapped_column(Integer)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", backref="credit_transactions")
