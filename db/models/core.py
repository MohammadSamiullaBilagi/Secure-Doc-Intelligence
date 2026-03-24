import uuid
from typing import Optional, List
from datetime import datetime, date

from sqlalchemy import String, Boolean, ForeignKey, JSON, Uuid, Date, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.database import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Core user accounting table."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Relationships
    preferences: Mapped["UserPreference"] = relationship(
        "UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    blueprints: Mapped[List["Blueprint"]] = relationship(
        "Blueprint", back_populates="user", cascade="all, delete-orphan"
    )
    audit_jobs: Mapped[List["AuditJob"]] = relationship(
        "AuditJob", back_populates="user", cascade="all, delete-orphan"
    )
    clients: Mapped[List["Client"]] = relationship(
        "Client", back_populates="ca_user", cascade="all, delete-orphan"
    )
    notice_jobs: Mapped[List["NoticeJob"]] = relationship(
        "NoticeJob", back_populates="user", cascade="all, delete-orphan"
    )


class UserPreference(Base, TimestampMixin):
    """Notification targets for alerting the user."""
    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    preferred_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    whatsapp_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    alert_tier: Mapped[str] = mapped_column(String(50), default="standard")

    # CA branding fields (Phase 2)
    firm_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ca_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    icai_membership_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    # CA contact info (Phase 5)
    firm_address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    firm_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    firm_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="preferences")


class Blueprint(Base, TimestampMixin):
    """Dynamic LLM compliance checklists."""
    __tablename__ = "blueprints"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    # A null user_id means it's a global system blueprint available to everyone
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Stores the JSON array of checks: [{"focus": "...", "rule": "..."}]
    rules_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="blueprints")


class AuditJob(Base, TimestampMixin):
    """State tracking for a specific LangGraph audit run."""
    __tablename__ = "audit_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE")
    )
    document_name: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # 'pending', 'approved', 'rejected', 'dispatched'
    status: Mapped[str] = mapped_column(String(50), default="pending")
    
    # Store LangGraph's exact specific thread ID to retrieve state later
    langgraph_thread_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    results_summary: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Denormalized compliance metrics — populated by WatcherService after audit completes
    blueprint_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    compliance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    open_violations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_financial_exposure: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="audit_jobs")
    client: Mapped[Optional["Client"]] = relationship("Client")


class GSTReconciliation(Base, TimestampMixin):
    """GSTR-2B vs Purchase Register reconciliation job."""
    __tablename__ = "gst_reconciliations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    period: Mapped[str] = mapped_column(String(10), nullable=False)  # "2025-12" (YYYY-MM)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing/completed/error
    gstr2b_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purchase_register_filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    matched_count: Mapped[int] = mapped_column(default=0)
    mismatched_count: Mapped[int] = mapped_column(default=0)
    missing_in_books_count: Mapped[int] = mapped_column(default=0)
    missing_in_gstr2b_count: Mapped[int] = mapped_column(default=0)
    total_itc_available: Mapped[float] = mapped_column(default=0.0)
    total_itc_at_risk: Mapped[float] = mapped_column(default=0.0)

    # Relationships
    user: Mapped["User"] = relationship("User")
    client: Mapped[Optional["Client"]] = relationship("Client")


class BankStatementAnalysis(Base, TimestampMixin):
    """Bank statement analysis — statutory threshold flagging."""
    __tablename__ = "bank_statement_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    period_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    total_transactions: Mapped[int] = mapped_column(Integer, default=0)
    total_debit: Mapped[float] = mapped_column(Float, default=0.0)
    total_credit: Mapped[float] = mapped_column(Float, default=0.0)
    flags_count: Mapped[int] = mapped_column(Integer, default=0)
    high_flags: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    user: Mapped["User"] = relationship("User")
    client: Mapped[Optional["Client"]] = relationship("Client")


class CapitalGainsAnalysis(Base, TimestampMixin):
    """Capital gains analysis — broker PDF extraction + Schedule CG computation."""
    __tablename__ = "capital_gains_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    fy: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    total_transactions: Mapped[int] = mapped_column(Integer, default=0)
    total_gain_loss: Mapped[float] = mapped_column(Float, default=0.0)
    total_estimated_tax: Mapped[float] = mapped_column(Float, default=0.0)
    ltcg_equity_taxable: Mapped[float] = mapped_column(Float, default=0.0)
    stcg_equity_net: Mapped[float] = mapped_column(Float, default=0.0)
    exemption_112a: Mapped[float] = mapped_column(Float, default=0.0)
    reconciliation_warnings: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    user: Mapped["User"] = relationship("User")
    client: Mapped[Optional["Client"]] = relationship("Client")


class DepreciationAnalysis(Base, TimestampMixin):
    """Depreciation analysis — IT Act WDV + Companies Act SLM + deferred tax."""
    __tablename__ = "depreciation_analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    fy: Mapped[str] = mapped_column(String(10), nullable=False)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.25)
    status: Mapped[str] = mapped_column(String(20), default="processing")
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    total_assets: Mapped[int] = mapped_column(Integer, default=0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    it_act_depreciation: Mapped[float] = mapped_column(Float, default=0.0)
    ca_depreciation: Mapped[float] = mapped_column(Float, default=0.0)
    timing_difference: Mapped[float] = mapped_column(Float, default=0.0)
    deferred_tax_amount: Mapped[float] = mapped_column(Float, default=0.0)

    # Relationships
    user: Mapped["User"] = relationship("User")
    client: Mapped[Optional["Client"]] = relationship("Client")


class AdvanceTaxComputation(Base, TimestampMixin):
    """Advance tax instalment and Section 234 interest computation."""
    __tablename__ = "advance_tax_computations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    fy: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="completed")
    estimated_tax: Mapped[float] = mapped_column(Float, default=0.0)
    total_interest: Mapped[float] = mapped_column(Float, default=0.0)
    interest_234a: Mapped[float] = mapped_column(Float, default=0.0)
    interest_234b: Mapped[float] = mapped_column(Float, default=0.0)
    interest_234c: Mapped[float] = mapped_column(Float, default=0.0)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
    client: Mapped[Optional["Client"]] = relationship("Client")


class GSTR9Reconciliation(Base, TimestampMixin):
    """GSTR-9 Annual Return — GSTR-1 vs GSTR-3B vs Books reconciliation."""
    __tablename__ = "gstr9_reconciliations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        Uuid, ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    gstin: Mapped[str] = mapped_column(String(15), nullable=False)
    fy: Mapped[str] = mapped_column(String(7), nullable=False)  # "2025-26"
    status: Mapped[str] = mapped_column(String(20), default="processing")
    gstr1_turnover: Mapped[float] = mapped_column(Float, default=0.0)
    gstr3b_turnover: Mapped[float] = mapped_column(Float, default=0.0)
    books_turnover: Mapped[float] = mapped_column(Float, default=0.0)
    gstr1_tax_paid: Mapped[float] = mapped_column(Float, default=0.0)
    gstr3b_tax_paid: Mapped[float] = mapped_column(Float, default=0.0)
    discrepancy_count: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # Relationships
    user: Mapped["User"] = relationship("User")
    client: Mapped[Optional["Client"]] = relationship("Client")
