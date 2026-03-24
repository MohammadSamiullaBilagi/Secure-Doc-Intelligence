# Known Issues & Technical Debt

## P0 — Breaks Core UX (fix immediately)

### SSE Status Updates Broken
**File**: `multi_agent.py:58-59`
**Problem**: Orchestrator constructs `thread_id = f"{user_id}_{target_contract}"` for status updates, but the AuditJob DB record stores a pure UUID as `langgraph_thread_id`. These never match. SSE stream at `/api/v1/status/stream/{uuid}` connects fine but never receives updates.
**Fix needed**: Pass the UUID thread_id into `ComplianceOrchestrator` state and use it in `update_audit_status()` calls.

### Calendar Seeding Won't Re-Seed for FY 2027-28
**File**: `services/calendar_service.py:20-26`
**Problem**: Seed guard checks `if any system deadline exists → skip`. All dates hardcoded to FY 2026-27. When FY rolls over, no new deadlines appear.
**Fix needed**: Parameterize by fiscal year or check by `due_date >= date(2027, 4, 1)`.

## P1 — Significant Gaps (high willingness to pay)

### Only 6 of 7 Blueprints Seed
**Location**: `blueprints/` folder has 7 JSON files but `rbi_blueprint.json` has invalid JSON
**Impact**: RBI compliance checks fail to seed
**Fix needed**: Fix the JSON syntax in `rbi_blueprint.json`

### Email Reminders Never Send
**File**: `db/models/calendar.py` — `UserReminder` stores data but scheduler job may not be sending emails reliably
**Fix needed**: Verify APScheduler daily job queries reminders where `(due_date - today).days == remind_days_before` and sends email via SMTP

## P2 — Important for Retention

### N+1 Queries in list_clients
**File**: `api/routes/clients.py:39-53`
**Problem**: Executes separate `SELECT COUNT(*)` per client for document_count. 100 clients = 101 queries.
**Fix needed**: Single query with LEFT JOIN + GROUP BY or subquery.

### N+1 Queries in list_reminders
**File**: `api/routes/calendar.py:108-131`
**Problem**: Loads deadline via separate query per reminder.
**Fix needed**: Use `selectinload(UserReminder.deadline)` on initial query.

### No Shareable Report Links
**Impact**: CAs want to share reports with their clients directly, not download and email
**Fix needed**: Generate time-limited token, `/report/share/{token}` endpoint returning clean client-facing view

### SSE Status Not Durable Across Restarts
**Problem**: `_audit_status` is an in-memory dict — lost on server restart
**Fix needed**: Use Redis or DB-backed status storage in production (Cloud Run instances can restart)

## P3 — Nice to Have

### ITC Mismatch Detection
Upload purchase register + GSTR-2A → AI cross-references → vendor-wise mismatch table.
Highest GST pain point, nothing in market does it with AI.

### Multi-Blueprint per Upload
Currently one upload → one blueprint. CAs need GST + Income Tax checks simultaneously.
Fix: Multi-select blueprint picker, parallel LangGraph threads.

### TOCTOU Race in Bulk Upload Credits
**File**: `api/routes/documents.py:194-219`
Upfront check then per-file deduction — concurrent request could drain credits between check and deduction.
Fix: Deduct all upfront atomically, refund on failure.

## Production Deployment Checklist
- [x] Remove hardcoded SECRET_KEY default
- [x] Fix CORS regex (removed allow_origin_regex wildcard)
- [x] Fix uvicorn reload default (defaults to False)
- [x] Make webhook secret validation mandatory
- [x] Add global exception handler (JSON, not HTML traceback)
- [x] Enhanced health check (DB + ChromaDB, returns 503 on degraded)
- [x] Create `.env.production` template
- [x] Create SQLite → PostgreSQL migration script
- [ ] GCP: Create Cloud SQL PostgreSQL instance
- [ ] GCP: Create GCS bucket + S3 interop keys
- [ ] GCP: Store secrets in Secret Manager
- [ ] GCP: Deploy to Cloud Run
- [ ] GCP: Map legalaiexpert.in domain
- [ ] Run alembic migrations on PostgreSQL
- [ ] Run data migration script
- [ ] Switch Razorpay to production keys (later)

## Resolved Issues (do not re-introduce)
- ✅ `_safe_get` returns None instead of default — fixed in `export_service.py`
- ✅ `audit_results: None` bypasses default — fixed to `or []` in `reports.py`
- ✅ Duplicate client creation in bulk upload — fixed with `client_cache` dict
- ✅ Synchronous LangGraph in async export — fixed with `asyncio.to_thread()`
- ✅ Reminder channel not validated — fixed with `Literal["email", "whatsapp"]` in schema
- ✅ No UniqueConstraint on Client(ca_user_id, name) — added
- ✅ Razorpay SDK not installed — installed via `uv add razorpay`
- ✅ Hardcoded SECRET_KEY default — removed, validated at startup
- ✅ CORS allow_origin_regex accepts any origin — removed
- ✅ uvicorn reload defaults to True — fixed to default False
- ✅ Webhook signature skippable — made mandatory
