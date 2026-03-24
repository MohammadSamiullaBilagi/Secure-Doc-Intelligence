# CLAUDE.md

This file provides guidance to Claude Code when working with this repository.
**Persistent memory files** (read these first — they contain full project context):
- `memory/code_map.md` — **PRIMARY REFERENCE** — every class, method, endpoint, schema with signatures. Read this FIRST to avoid exploring the codebase.
- `memory/MEMORY.md` — index + quick facts
- `memory/architecture.md` — directory layout, data flows, pipelines
- `memory/api_reference.md` — all endpoints with exact request/response shapes
- `memory/db_models.md` — all SQLAlchemy models and relationships
- `memory/known_issues.md` — confirmed bugs, P0/P1/P2 priority fixes
- `memory/blueprints.md` — blueprint JSON format, existing + missing blueprints

---

## Commands

```bash
# Install dependencies (use uv, NEVER pip)
uv sync
uv add <package>   # to add new package

# Start the FastAPI backend (port 8000)
python main.py

# Run database migrations
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"

# Ingest PDFs from data/ into global vector DB
python ingestion.py

# Docker (production)
docker build -t legal-ai-expert .
docker-compose up

# SQLite → PostgreSQL migration (one-time)
POSTGRES_URL=postgresql://... python scripts/migrate_sqlite_to_postgres.py

# Test scripts (no pytest — standalone)
python test_pipeline.py
python test_pipeline_json.py
python test_pipeline_missing.py
python test_pdf.py
python test_ocr.py
```

---

## Architecture (quick summary — see memory/architecture.md for full detail)

**Stack**: FastAPI + LangGraph + LangChain + SQLite/PostgreSQL + ChromaDB + Anthropic (Haiku 4.5 for chat/extraction, Sonnet 4.6 for reports)

### Core Pipelines
- **`agent.py` — `SecureDocAgent`**: 4-stage RAG (Route→Retrieve→Generate→Evaluate). Methods: `query()`, `extract_for_audit()`, `extract_structured_fields()`
- **`multi_agent.py` — `ComplianceOrchestrator`**: 5-stage multi-agent (Researcher→Auditor→Analyst→Remediation→Dispatch). HITL pause at Dispatch. State in `Database/checkpointer.db`.
- **`ingestion.py` — `DocumentProcessor`**: Extract (PyMuPDF + OCR) → Chunk (1000/150) → Embed → ChromaDB

### Data Isolation
- User docs: `user_sessions/{user_id}/vector_db/` (local) or S3/GCS bucket (production)
- Global regulations: `global_vector_db/`

### Plan Tiers & Feature Gating
```
free_trial: 75 credits    | starter: 100 (Rs.499)
professional: 300 (Rs.999) | enterprise: 1000 (Rs.2,499)
```

**Free trial users get ALL features** (including analysis, notices, blueprints, clients, calendar) — access is **credit-gated**, not plan-gated. When credits exhaust, features become restricted.

Plan gating in `api/dependencies.py`: `require_starter`, `require_professional`, `require_enterprise` — all allow `free_trial` users with `credits_balance > 0`.

### Credit Costs
- DOCUMENT_SCAN = 3 credits
- CHAT_QUERY = 1 credit
- BLUEPRINT_CREATE = 2 credits
- NOTICE_REPLY = 5 credits
- NOTICE_REGENERATE = 1 credit
- GSTR_RECON = 10 credits
- BANK_ANALYSIS = 8 credits
- CAPITAL_GAINS_ANALYSIS = 10 credits
- GSTR9_RECON = 15 credits
- DEPRECIATION_CALC = 8 credits
- ADVANCE_TAX_CALC = 2 credits

---

## API Routes (see memory/api_reference.md for full detail)

| Prefix | File | Access |
|--------|------|--------|
| /api/v1/auth | routes/auth.py | All |
| /api/v1/documents | routes/documents.py | All (bulk-upload: Enterprise) |
| /api/v1/chat | routes/chat.py | All |
| /api/v1/audits | routes/audits.py | All |
| /api/v1/blueprints | routes/blueprints.py | All (credit-gated) |
| /api/v1/reports | routes/reports.py | All (export: Enterprise) |
| /api/v1/billing | routes/billing.py | All |
| /api/v1/payments | routes/payments.py | All |
| /api/v1/status | routes/status.py | All |
| /api/v1/clients | routes/clients.py | All (credit-gated) |
| /api/v1/calendar | routes/calendar.py | All (credit-gated) |
| /api/v1/notices | routes/notices.py | All (credit-gated) |
| /api/v1/gst-recon | routes/gst_reconciliation.py | All (credit-gated) |
| /api/v1/gstr9-recon | routes/gstr9_recon.py | All (credit-gated) |
| /api/v1/bank-analysis | routes/bank_analysis.py | All (credit-gated) |
| /api/v1/capital-gains | routes/capital_gains.py | All (credit-gated) |
| /api/v1/depreciation | routes/depreciation.py | All (credit-gated) |
| /api/v1/advance-tax | routes/advance_tax.py | All (credit-gated) |
| /api/v1/feedback | routes/feedback.py | All |

### CSV/Excel Export Endpoints (all analysis features)
Each analysis feature has `GET /{id}/csv?sheet={name}` (per-table CSV) and `GET /{id}/excel` (multi-sheet XLSX).
Uses `services/tabular_export_service.py` — `TabularExportService.to_csv()` / `to_excel()`.

---

## Database (see memory/db_models.md for full detail)

- **Dev**: `micro_saas.db` (SQLite + aiosqlite)
- **Production**: Cloud SQL PostgreSQL (asyncpg) — set `DATABASE_URL` in `.env`
- **Models**: `db/models/core.py`, `billing.py`, `clients.py`, `calendar.py`, `notices.py`, `references.py`, `feedback.py`
- **Migrations**: Alembic in `alembic/` — always import new model modules in `alembic/env.py`
- **Storage**: Local filesystem or S3/GCS via `services/storage.py` (`STORAGE_BACKEND=s3`)

---

## Environment Variables (required in `.env`)

```
OPENAI_API_KEY=
TAVILY_API_KEY=
ANTHROPIC_API_KEY=           # for Haiku/Sonnet models
DATABASE_URL=sqlite+aiosqlite:///./micro_saas.db
CHECKPOINTER_DB_PATH=Database/checkpointer.db
SECRET_KEY=                  # REQUIRED — no safe default
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173
N8N_WEBHOOK_URL=             # optional
RAZORPAY_KEY_ID=             # configured (rzp_test_...)
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=     # REQUIRED for webhook endpoint
GOOGLE_CLIENT_ID=            # optional
SMTP_HOST=                   # for email reminders
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
STORAGE_BACKEND=local        # "local" or "s3" (GCS via S3 interop)
S3_BUCKET=
S3_REGION=
S3_ACCESS_KEY=
S3_SECRET_KEY=
S3_ENDPOINT_URL=             # https://storage.googleapis.com for GCS
```

See `.env.production` for production template with Cloud SQL + GCS + Secret Manager notes.

## External Dependencies

- **Tesseract OCR**: must be installed separately (Windows: UB-Mannheim, Docker: apt package)
- **LLM**: Anthropic Haiku 4.5 (chat/extraction), Sonnet 4.6 (reports/remediation) + OpenAI `text-embedding-3-small`
- **razorpay**: installed via uv
- **Rate limiting**: slowapi middleware on all routes

---

## Production Deployment (GCP)

**Architecture**: Cloud Run → Cloud SQL (PostgreSQL) + GCS (file storage) + Secret Manager
**Domain**: `legalaiexpert.in` (Namecheap DNS → Cloud Run custom domain mapping)
**Docker**: Multi-stage build with gunicorn + uvicorn workers. `ENV=production` set in Dockerfile.

Key production safeguards:
- SECRET_KEY validated at startup (exits if empty/default)
- CORS restricted to `ALLOWED_ORIGINS` (no regex wildcard)
- Webhook signature validation mandatory
- Global exception handler returns JSON (not HTML traceback)
- Health check at `/health` verifies DB + ChromaDB connectivity

See plan file or `scripts/migrate_sqlite_to_postgres.py` for SQLite → PostgreSQL migration.

---

## Known P0 Bugs (see memory/known_issues.md for all)

1. **SSE status never updates** — `multi_agent.py:58-59` constructs wrong thread_id format
2. **Calendar won't re-seed FY 2027-28** — hardcoded dates + over-eager skip guard

## Key Services

| Service | File | Purpose |
|---------|------|---------|
| CreditsService | services/credits_service.py | Credit balance, deduction, upgrade |
| TabularExportService | services/tabular_export_service.py | CSV/Excel export for analysis tables |
| CalendarService | services/calendar_service.py | Tax deadline seeding, reminders |
| ReportService | services/report_service.py | PDF compliance reports |
| ExportService | services/export_service.py | CSV, Tally XML, Zoho JSON |
| NoticeService | services/notice_service.py | GST/IT notice reply drafting |
| DocumentParser | services/document_parser.py | Haiku L1 parsing for audit pipeline |
| CheckAgentService | services/check_agent.py | Haiku L2 parallel audit checks |
| ReferenceService | services/reference_service.py | Ground truth DB cache |
| StorageService | services/storage.py | Local or S3/GCS file storage |
| Scheduler | services/scheduler.py | APScheduler background jobs |
| RateLimit | api/rate_limit.py | slowapi rate limiting |
