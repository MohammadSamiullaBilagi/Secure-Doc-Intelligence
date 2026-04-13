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

**Stack**: FastAPI + LangGraph + LangChain + SQLite/PostgreSQL + ChromaDB + Gemini 2.5 Pro (extraction/evaluation) + Gemini 2.0 Flash (routing/reranking) + OpenAI Embeddings (text-embedding-3-small)

### LLM Configuration
- **Central factory**: `services/llm_config.py` — `get_heavy_llm()` (Gemini 2.5 Pro), `get_light_llm()` (Gemini 2.0 Flash), `get_json_llm()`, `get_embeddings()`
- **Fallback**: If `GOOGLE_API_KEY` not set, all models fall back to `gpt-4o-mini`
- **Reranker**: `services/reranker.py` — scores retrieved chunks by relevance, keeps top-k
- **Query Expander**: `services/query_expander.py` — generates 3 targeted queries per compliance check

### Core Pipelines
- **`agent.py` — `SecureDocAgent`**: Hybrid RAG (Retrieve from both local+global → Rerank → Generate → Evaluate). Methods: `query()`, `extract_for_audit()`, `extract_structured_fields()`. Supports conversation history via `chat_history` parameter.
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

Blueprint access check: `GET /api/v1/blueprints/access` → `{has_access, reason, plan, credits_balance}`. Frontend must use this (not plan name) to decide blueprint selector vs upgrade prompt.

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
| /api/v1/chat | routes/chat.py | All (session_id for conversation memory, hybrid routing, general knowledge fallback) |
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
| /api/v1/legal | routes/legal.py | Public (privacy-policy, terms, ai-disclosure) / Auth (consent) |
| /api/v1/account | routes/account.py | Auth (data deletion, data export) |
| /api/v1/audit-logs | routes/audit_logs.py | Admin (all logs) / Auth (own logs) |
| /api/v1/tools | routes/tools.py | Public (redactor download, info) |

### CSV/Excel Export Endpoints (all analysis features)
Each analysis feature has `GET /{id}/csv?sheet={name}` (per-table CSV) and `GET /{id}/excel` (multi-sheet XLSX).
Uses `services/tabular_export_service.py` — `TabularExportService.to_csv()` / `to_excel()`.

---

## Database (see memory/db_models.md for full detail)

- **Dev**: `micro_saas.db` (SQLite + aiosqlite)
- **Production**: Cloud SQL PostgreSQL (asyncpg) — set `DATABASE_URL` in `.env`
- **Models**: `db/models/core.py`, `billing.py`, `clients.py`, `calendar.py`, `notices.py`, `references.py`, `feedback.py`, `chat.py`, `audit_log.py`
- **Migrations**: Alembic in `alembic/` — always import new model modules in `alembic/env.py`
- **Storage**: Local filesystem or S3/GCS via `services/storage.py` (`STORAGE_BACKEND=s3`)

---

## Environment Variables (required in `.env`)

```
OPENAI_API_KEY=
TAVILY_API_KEY=
ANTHROPIC_API_KEY=           # for Haiku/Sonnet models (legacy)
GOOGLE_API_KEY=              # Gemini 2.5 Pro / 2.0 Flash (primary LLM)
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
- **LLM**: Gemini 2.5 Pro (extraction/evaluation/drafting), Gemini 2.0 Flash (routing/reranking/query expansion). Fallback: OpenAI gpt-4o-mini. Embeddings: OpenAI `text-embedding-3-small`
- **langchain-google-genai**: `langchain-google-genai>=4.2.1` — Google Gemini integration
- **razorpay**: installed via uv
- **markdown**: `markdown==3.10.2` — converts AI-generated markdown to HTML for emails/webhooks
- **Rate limiting**: slowapi middleware on all routes

---

## Production Deployment (GCP)

**Architecture**: Cloud Run → Cloud SQL (PostgreSQL) + GCS (file storage) + Secret Manager
**Domain**: `legalaiexpert.in` (Namecheap DNS → Cloud Run custom domain mapping)
**Docker**: Multi-stage build with gunicorn + uvicorn workers. `ENV=production` set in Dockerfile.
**Deploy command**: `gcloud run deploy legal-ai-expert --source . --region asia-south1 --allow-unauthenticated`
**GCP Project**: `legal-ai-expert` | **Service**: `legal-ai-expert` | **Region**: `asia-south1`

Key production safeguards:
- SECRET_KEY validated at startup (exits if empty/default)
- CORS restricted to `ALLOWED_ORIGINS` (no regex wildcard)
- Webhook signature validation mandatory
- Global exception handler returns JSON (not HTML traceback)
- Health check at `/health` verifies DB + ChromaDB connectivity
- PostgreSQL pool: `pool_recycle=1800` prevents stale connections after idle
- Auth endpoints rate-limited to 10 requests/minute per IP

See plan file or `scripts/migrate_sqlite_to_postgres.py` for SQLite → PostgreSQL migration.

### Email Dispatch (SendGrid via SMTP)
- **Dual-recipient**: Emails go to BOTH subscriber's preferred email AND client's email
  - Subscriber email = `UserPreference.preferred_email` (fallback: `User.email`)
  - Client email = `Client.email` (only if client is linked)
  - No client linked? Email goes to subscriber only
  - Duplicate emails are auto-deduplicated
- **Audit approval** (`POST /api/v1/audits/{thread_id}/approve`): sends compliance report to subscriber + client
- **Notice approval** (`POST /api/v1/notices/{id}/approve`): sends notice reply to subscriber + client
- Both return `email_sent` (bool) and `email_error` (string|null) in response
- `EmailService.send_email()` accepts `Union[str, List[str]]` for multiple recipients
- CA branding: FROM="CA Name via Legal AI Expert", Reply-To=CA's firm_email
- **Markdown rendering**: `markdown` library converts AI-generated markdown → proper HTML in emails (bold, headers, lists render correctly). Plain text fallback uses `_strip_markdown()` to remove `**`, `##`, `*` etc.
- SMTP config: SendGrid relay via `SMTP_HOST`, `SMTP_USER` (apikey), `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`

### Markdown Handling (AI-generated content)
- AI models (Anthropic/OpenAI) return markdown (`**bold**`, `## headers`, `* bullets`)
- **Emails**: `markdown` library converts to HTML; `_strip_markdown()` creates plain text fallback
- **PDFs**: `_strip_markdown()` in `report_service.py` removes markdown before rendering via FPDF
- **Webhooks**: `webhook_service.py` sends both `body_html` (markdown→HTML) and `body_plain` (stripped)
- Helper `_strip_markdown()` handles: headers, bold/italic, strikethrough, inline code, links, images, horizontal rules, blockquotes, list markers

### DPDPA Compliance (Phase 10)
- **Consent**: Required on registration (email + Google). Fields on User: `consent_accepted_at`, `consent_version`, `data_deleted_at`. Current version: `v1.0`.
- **Right to Erasure**: `DELETE /api/v1/account/data` — deletes all docs, ChromaDB, analysis records, chat, clients, notices, blueprints. KEEPS: User account, Subscription, CreditTransactions, AuditLogs.
- **Privacy Policy / ToS**: `GET /api/v1/legal/privacy-policy`, `/terms` — structured JSON, no auth required.
- **Audit Logs**: `AuditLog` model in `db/models/audit_log.py`. Events: login, document_upload, audit_run, notice_upload, data_export, data_delete, profile_update, consent_update, password_change. Admin view: `GET /api/v1/audit-logs`. User view: `GET /api/v1/audit-logs/me`.
- **AI Disclosure**: Upload response includes `ai_processing_disclosure` field. Dedicated endpoint: `GET /api/v1/legal/ai-disclosure`.
- **PDF Redaction Tool**: Standalone PyQt6+PyMuPDF desktop app in `tools/pdf_redactor/`. Uses `page.apply_redactions()` for permanent text removal. Download via `GET /api/v1/tools/redactor/download`. Guide: redact PAN/Aadhaar/names, do NOT redact GSTIN/dates/amounts.

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
| EmailService | services/email_service.py | SMTP/SendGrid email: audit dispatch, notice reply, deadline reminders |
| StorageService | services/storage.py | Local or S3/GCS file storage |
| Scheduler | services/scheduler.py | APScheduler background jobs |
| LLMConfig | services/llm_config.py | Central LLM factory: Gemini Pro/Flash with OpenAI fallback |
| Reranker | services/reranker.py | Rerank retrieved chunks by relevance (Gemini Flash) |
| QueryExpander | services/query_expander.py | Generate targeted retrieval queries per compliance check |
| RateLimit | api/rate_limit.py | slowapi rate limiting (auth: 10/min) |
| AuditLogService | services/audit_log_service.py | DPDPA audit trail: log_audit_event(), extract_request_meta() |
| DataDeletionService | services/data_deletion_service.py | Right to Erasure: delete_user_data() — all user data except billing/audit logs |
| LegalContent | services/legal_content.py | Privacy Policy, ToS, AI disclosure (static JSON content) |
