# Architecture Reference

## Directory Layout
```
Legal_AI_Expert/
├── main.py                    # FastAPI app, startup event, router registration
├── agent.py                   # SecureDocAgent (RAG, 4-stage LangGraph)
├── multi_agent.py             # ComplianceOrchestrator (5-stage multi-agent)
├── ingestion.py               # DocumentProcessor (extract→chunk→embed)
├── config.py                  # Pydantic settings (reads .env)
├── Dockerfile                 # Multi-stage: python:3.12 + gunicorn + Tesseract
├── docker-compose.yml         # Dev: app + PostgreSQL + volumes
├── .env.production            # Production env template (GCP Cloud SQL + GCS)
├── api/
│   ├── dependencies.py        # get_current_user, require_starter/professional/enterprise
│   ├── rate_limit.py          # slowapi rate limiter configuration
│   └── routes/
│       ├── auth.py            # /api/v1/auth — register, login, google, me
│       ├── documents.py       # /api/v1/documents — upload, bulk-upload
│       ├── chat.py            # /api/v1/chat — AI Q&A
│       ├── audits.py          # /api/v1/audits — pending, approve, reject, clear
│       ├── blueprints.py      # /api/v1/blueprints — CRUD
│       ├── reports.py         # /api/v1/reports — pdf, export
│       ├── billing.py         # /api/v1/billing — balance, transactions, plans, feature-access
│       ├── payments.py        # /api/v1/payments — Razorpay orders + webhooks
│       ├── status.py          # /api/v1/status — SSE stream, poll
│       ├── clients.py         # /api/v1/clients — CRUD
│       ├── calendar.py        # /api/v1/calendar — deadlines, reminders
│       ├── notices.py         # /api/v1/notices — upload, AI reply, regenerate
│       ├── gst_reconciliation.py  # /api/v1/gst-recon — upload, results, csv, excel, report
│       ├── gstr9_recon.py     # /api/v1/gstr9-recon — upload, results, csv, excel, report
│       ├── bank_analysis.py   # /api/v1/bank-analysis — upload, results, csv, excel, report
│       ├── capital_gains.py   # /api/v1/capital-gains — upload, results, csv, excel, report
│       ├── depreciation.py    # /api/v1/depreciation — upload, results, csv, excel, report
│       ├── advance_tax.py     # /api/v1/advance-tax — compute, results, csv, excel, report
│       └── feedback.py        # /api/v1/feedback — submit feedback
├── db/
│   ├── database.py            # Base, TimestampMixin, engine, AsyncSessionLocal, get_db
│   ├── config.py              # Settings alias (imports from config.py)
│   └── models/
│       ├── core.py            # User, UserPreference, Blueprint, AuditJob, 6 analysis models
│       ├── billing.py         # Subscription, CreditTransaction, PlanTier enum
│       ├── clients.py         # Client, ClientDocument
│       ├── calendar.py        # TaxDeadline, UserReminder
│       ├── notices.py         # NoticeJob
│       ├── references.py      # ReferenceCache
│       └── feedback.py        # Feedback
├── schemas/                   # Pydantic request/response models
├── services/
│   ├── auth_service.py        # JWT creation, password hashing
│   ├── credits_service.py     # CreditsService — balance, deduct, add, upgrade plan
│   ├── tabular_export_service.py  # TabularExportService — CSV/Excel for analysis tables
│   ├── watcher_service.py     # Runs ComplianceOrchestrator in background
│   ├── approval_service.py    # ApprovalService — HITL pause/resume LangGraph
│   ├── webhook_service.py     # WebhookService — N8N dispatch with retry
│   ├── blueprint_service.py   # Load/validate blueprint JSON files
│   ├── report_service.py      # ReportService.generate_compliance_pdf()
│   ├── export_service.py      # ExportService — to_csv, to_tally_xml, to_zoho_json
│   ├── calendar_service.py    # CalendarService — seed_indian_deadlines, get_upcoming
│   ├── notice_service.py      # NoticeService — GST/IT notice reply drafting
│   ├── document_parser.py     # DocumentParser — Haiku L1 parsing
│   ├── check_agent.py         # CheckAgentService — Haiku L2 parallel audit checks
│   ├── reference_service.py   # ReferenceService — ground truth DB cache
│   ├── storage.py             # StorageService — local filesystem or S3/GCS
│   ├── email_service.py       # SMTP email sending
│   ├── cleanup_service.py     # TTL sweep of stale user sessions
│   ├── scraper_service.py     # Weekly Tavily → global_vector_db refresh
│   └── scheduler.py           # APScheduler wiring
├── blueprints/                # System blueprint JSON files (7 blueprints)
├── scripts/
│   └── migrate_sqlite_to_postgres.py  # One-time SQLite → PostgreSQL migration
├── alembic/                   # DB migrations (async env.py)
├── micro_saas.db              # SQLite main database (dev)
├── Database/checkpointer.db   # LangGraph SQLite checkpointer
├── global_vector_db/          # ChromaDB for regulatory knowledge
└── user_sessions/
    └── {user_id}/
        ├── data/              # Uploaded PDFs
        └── vector_db/         # User-isolated ChromaDB
```

## Production Architecture (GCP)
```
                        ┌─────────────┐
  legalaiexpert.in ───→ │ Cloud Run   │ ← Docker container (gunicorn+uvicorn)
                        │ (port 8000) │
                        └──────┬──────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
     ┌──────────────┐  ┌────────────┐  ┌──────────────┐
     │ Cloud SQL    │  │ GCS Bucket │  │ Secret       │
     │ PostgreSQL   │  │ (files)    │  │ Manager      │
     └──────────────┘  └────────────┘  └──────────────┘
```
- **Cloud Run**: Auto-scaling (0-3 instances), 2 vCPU, 2GB RAM, 300s timeout
- **Cloud SQL**: PostgreSQL 15, db-f1-micro, connected via Unix socket
- **GCS**: S3-compatible via interop API (`STORAGE_BACKEND=s3`)
- **Secret Manager**: All API keys and credentials
- **SSL**: Managed by GCP (auto-provisioned)
- **DNS**: Namecheap → Cloud Run custom domain mapping

## Core Data Flows

### Document Upload → Audit Flow
1. `POST /api/v1/documents/upload` (multipart/form-data: files[], blueprint_file)
2. `documents.py` deducts 3 credits per PDF via `CreditsService.check_and_deduct`
3. Files saved to `user_sessions/{user_id}/data/` (or S3/GCS in production)
4. `DocumentProcessor.extract_text_from_pdfs()` → `create_vector_store()` → ChromaDB
5. `AuditJob` created in DB with fresh UUID as `langgraph_thread_id`
6. `BackgroundTasks.add_task(WatcherService.run_background_audit, ...)`
7. `WatcherService` runs `ComplianceOrchestrator` → 5 nodes → pauses at Dispatch (HITL)
8. SSE stream at `/api/v1/status/stream/{thread_id}` polls `_audit_status` dict

### HITL Approval Flow
1. Frontend polls `GET /api/v1/audits/pending`
2. `ApprovalService.get_pending_approval(thread_id)` reads LangGraph checkpointer state
3. User edits email draft, clicks Approve
4. `POST /api/v1/audits/{thread_id}/approve` → `ApprovalService.approve_and_resume()`
5. LangGraph resumes → Dispatch node → `WebhookService.post_to_n8n()`
6. `AuditJob.status` updated to "dispatched"

### Multi-Agent Pipeline (ComplianceOrchestrator, multi_agent.py)
```
Researcher → Auditor → Analyst → Remediation → [HITL PAUSE] → Dispatch
```
- **Researcher**: Calls `SecureDocAgent.extract_structured_fields()` with blueprint
- **Auditor**: Per check, calls `SecureDocAgent.extract_for_audit()` → LLM evaluates compliance
- **Analyst**: Generates `risk_report` string from all `audit_results`
- **Remediation**: Drafts email if any NON_COMPLIANT results
- **Dispatch**: Posts to N8N webhook (pauses for HITL approval first)

State persisted in `Database/checkpointer.db` via `SqliteSaver`.

### Analysis Features (GST Recon, GSTR-9, Bank, Capital Gains, Depreciation, Advance Tax)
Each follows the pattern:
1. `POST /upload` → deduct credits → process files → store results in DB
2. `GET /{id}` → return full analysis results as JSON
3. `GET /{id}/report` → generate PDF via fpdf2
4. `GET /{id}/csv?sheet={name}` → per-table CSV via `TabularExportService`
5. `GET /{id}/excel` → multi-sheet XLSX via `TabularExportService` + openpyxl

### Feature Access & Credit Gating
- `GET /api/v1/billing/feature-access` returns `accessible: true/false` per feature
- Free trial users: `accessible = true` while `credits_balance > 0`
- Paid plan users: `accessible` based on plan rank
- Frontend shows upgrade card when `accessible: false`
- HTTP 402 returned when credits exhausted during action

## Key Architectural Decisions
- **LangGraph checkpointer**: SqliteSaver (synchronous sqlite3) — must use `asyncio.to_thread()` when called from async routes
- **ChromaDB per user**: strict tenant isolation, never mix user data
- **Credits**: checked AND deducted atomically per action; no upfront bulk deduction except bulk-upload UX check
- **SSE status**: in-memory dict `_audit_status` keyed by thread_id — NOT durable across restarts; use Redis in production
- **HITL**: LangGraph graph pauses at Dispatch interrupt; `ApprovalService` uses `graph.update_state()` to resume
- **Background tasks**: FastAPI `BackgroundTasks` (not Celery) — simple enough for current scale
- **Rate limiting**: slowapi middleware on all routes (configurable per-endpoint)
- **Storage abstraction**: `services/storage.py` supports local filesystem and S3/GCS backends

## Plan Tiers
```
free_trial:   75 credits (all features, credit-gated)
starter:      100 credits/month — ₹499
professional: 300 credits/month — ₹999
enterprise:   1000 credits/month — ₹2,499
```
Free trial users get ALL features until credits exhaust — enforced via `require_starter/professional/enterprise` dependencies that check `credits_balance > 0` for free_trial plans.
