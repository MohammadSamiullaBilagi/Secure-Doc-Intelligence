# Database Models Reference

DB file: `micro_saas.db` (SQLite via aiosqlite)
LangGraph checkpointer: `Database/checkpointer.db` (synchronous sqlite3)
ORM: SQLAlchemy 2.0 async mapped_column style
Base class: `db/database.py::Base` + `TimestampMixin` (adds `created_at`, `updated_at`)

## core.py — `db/models/core.py`

### User (`users` table)
```python
id: Uuid (PK, default uuid4)
email: String(255), unique, indexed
hashed_password: String(255), nullable  # None for Google-only users
is_active: Boolean, default True
# Relationships:
preferences -> UserPreference (one-to-one, cascade delete)
blueprints  -> Blueprint[] (cascade delete)
audit_jobs  -> AuditJob[] (cascade delete)
clients     -> Client[] (cascade delete)  # Phase 3
```

### UserPreference (`user_preferences` table)
```python
id: Uuid (PK)
user_id: Uuid (FK users.id, CASCADE, unique)
preferred_email: String(255), nullable
whatsapp_number: String(50), nullable
alert_tier: String(50), default "standard"
```

### Blueprint (`blueprints` table)
```python
id: Uuid (PK)
user_id: Uuid (FK users.id, CASCADE, nullable)  # NULL = system blueprint
name: String(255)
description: String(500), nullable
rules_json: JSON  # [{check_id, focus, rule}, ...]
```

### AuditJob (`audit_jobs` table)
```python
id: Uuid (PK)
user_id: Uuid (FK users.id, CASCADE)
client_id: Uuid (FK clients.id, SET NULL, nullable)  # Phase 3
document_name: String(255)
status: String(50), default "pending"  # pending | approved | rejected | dispatched
langgraph_thread_id: String(255), nullable, indexed  # UUID used to look up LangGraph state
results_summary: JSON, nullable
# Relationships:
user   -> User
client -> Client (nullable)
```

## billing.py — `db/models/billing.py`

### PlanTier (enum)
```python
FREE_TRIAL = "free_trial"
STARTER = "starter"
PROFESSIONAL = "professional"
ENTERPRISE = "enterprise"
PAY_AS_YOU_GO = "pay_as_you_go"
```

### CreditActionType (enum)
```python
DOCUMENT_SCAN = "document_scan"     # cost: 5
CHAT_QUERY = "chat_query"           # cost: 1
WEB_RESEARCH = "web_research"       # cost: 1
BLUEPRINT_CREATE = "blueprint_create"  # cost: 2
SUBSCRIPTION_CREDIT = "subscription_credit"
TOPUP = "topup"
REFERRAL_CREDIT = "referral_credit"
```

### Subscription (`subscriptions` table)
```python
id: Uuid (PK)
user_id: Uuid (FK users.id, CASCADE, unique)
plan: String(50), default "free_trial"
credits_balance: Integer, default 0
credits_monthly_quota: Integer, default 0
is_active: Boolean, default True
razorpay_subscription_id: String(255), nullable
```

### CreditTransaction (`credit_transactions` table)
```python
id: Uuid (PK)
user_id: Uuid (FK users.id, CASCADE)
action: String(50)       # CreditActionType value
credits_delta: Integer   # negative for costs, positive for grants
credits_after: Integer   # balance after this transaction
description: String(500), nullable
```

## clients.py — `db/models/clients.py` (Phase 3)

### Client (`clients` table)
```python
id: Uuid (PK)
ca_user_id: Uuid (FK users.id, CASCADE)
name: String(255)
gstin: String(15), nullable
email: String(255), nullable
phone: String(50), nullable
# UniqueConstraint: (ca_user_id, name) — name "uq_client_ca_user_name"
# Relationships:
ca_user   -> User (back_populates="clients")
documents -> ClientDocument[] (cascade delete)
```

### ClientDocument (`client_documents` table)
```python
id: Uuid (PK)
client_id: Uuid (FK clients.id, CASCADE)
audit_job_id: Uuid (FK audit_jobs.id, CASCADE)
document_name: String(255)
# Relationships:
client    -> Client
audit_job -> AuditJob
```

## calendar.py — `db/models/calendar.py` (Phase 3)

### TaxDeadline (`tax_deadlines` table)
```python
id: Uuid (PK)
title: String(255)
due_date: Date, indexed
category: String(50)  # "GST" | "Income Tax" | "TDS" | "Advance Tax"
description: String(500), nullable
is_system: Boolean, default True
```

### UserReminder (`user_reminders` table)
```python
id: Uuid (PK)
user_id: Uuid (FK users.id, CASCADE)
deadline_id: Uuid (FK tax_deadlines.id, CASCADE)
remind_days_before: Integer, default 3
channel: String(50)  # "email" | "whatsapp" — validated by Literal in schema
is_active: Boolean, default True
```

## Key Patterns

### get-or-create subscription (always use CreditsService.get_or_create_subscription)
New users have no Subscription row until first action. Never access Subscription directly without this helper.

### LangGraph state retrieval (always run in thread executor)
```python
# WRONG — blocks event loop:
state = approval_svc.get_pending_approval(thread_id)

# CORRECT:
state = await asyncio.to_thread(_get_audit_state_sync, user_id, thread_id)
```

### Session paths
```python
from api.routes.documents import get_session_paths
data_dir, db_dir = get_session_paths(str(user_id))
# data_dir = user_sessions/{user_id}/data/
# db_dir   = user_sessions/{user_id}/vector_db/
```

### Alembic migration notes
- SQLite doesn't support ALTER COLUMN — always use `batch_alter_table` for column changes
- New tables already created by `create_all` on startup — migrations must use `if_not_exists` checks
- Import new model modules in `alembic/env.py` for autogenerate to detect them
