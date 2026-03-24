# Legal AI Expert — Project Memory Index

## Quick Facts
- **Stack**: FastAPI + LangGraph + LangChain + SQLite/PostgreSQL + ChromaDB + Anthropic (Haiku 4.5, Sonnet 4.6)
- **Package manager**: `uv` (never pip). Run `uv add <pkg>` to install.
- **Start server**: `python main.py` → http://localhost:8000
- **Migrations**: `uv run alembic upgrade head`
- **Platform**: Windows 11, bash shell (use forward slashes)
- **Production**: GCP Cloud Run + Cloud SQL PostgreSQL + GCS. Domain: `legalaiexpert.in`
- **Docker**: `docker build -t legal-ai-expert .` → multi-stage with gunicorn+uvicorn

## Memory Files (read these before working on specific areas)
- [code_map.md](../../memory/code_map.md) — **START HERE** — Every class, method, endpoint, schema with signatures
- [api_reference.md](api_reference.md) — All endpoints, exact request/response shapes, auth, credit costs
- [architecture.md](architecture.md) — System design, data flow, pipelines, key decisions
- [db_models.md](db_models.md) — All SQLAlchemy models, relationships, table names
- [known_issues.md](known_issues.md) — Confirmed bugs, gaps, P0/P1/P2 priority fixes
- [blueprints.md](blueprints.md) — Blueprint JSON format, existing blueprints, what's missing

## Phase History
- **Phase 1-2**: Core RAG + multi-agent pipeline, auth, billing, Razorpay
- **Phase 3**: CA features — clients CRUD, bulk upload, tax calendar, CSV/Tally/Zoho export
- **Phase 4**: System blueprints (auto-seeded), client-ready PDF reports (CA branding), Notice Reply Assistant
- **Phase 5**: CA-aware enhancements — full contact info in PDFs, CA-aware chat prompt, client compliance dashboard, email reminder dispatch
- **Phase 6**: 3-Layer Agentic Audit Pipeline — DocumentParser (Haiku L1), parallel CheckAgentService (Haiku L2), Sonnet L3 reports. Ground truth ReferenceService with DB cache. FinancialImpact tracking + confidence levels.
- **Phase 6.5**: Free trial access model (all features credit-gated), CSV/Excel tabular exports for all 6 analysis features, GSTR-9 PDF report, rate limiting, feedback system
- **Phase 7**: Production readiness — security hardening (SECRET_KEY validation, CORS fix, webhook secret mandatory, global exception handler), GCP deployment setup (Cloud Run + Cloud SQL + GCS), SQLite→PostgreSQL migration script, `.env.production` template

## Critical Rules
- **Free trial users get ALL features** — access is credit-gated (75 credits), not plan-gated. `require_starter/professional/enterprise` all allow free_trial with credits > 0
- Auth: JWT Bearer tokens, 1-week expiry. `get_current_user` in `api/dependencies.py`
- DB session: always `async with AsyncSessionLocal()` or FastAPI `Depends(get_db)`
- Never use `pip` — always `uv add` or `uv sync`
- Credit costs: DOCUMENT_SCAN=3, CHAT_QUERY=1, BLUEPRINT_CREATE=2, NOTICE_REPLY=5, GSTR_RECON=10, BANK_ANALYSIS=8, CAPITAL_GAINS=10, GSTR9_RECON=15, DEPRECIATION=8, ADVANCE_TAX=2
- SECRET_KEY must be set in production (validated at startup, exits if empty/default)
- RAZORPAY_WEBHOOK_SECRET is mandatory (webhook endpoint rejects if not configured)
- Alembic migrations on SQLite: never include alter_column type changes — SQLite doesn't support ALTER COLUMN TYPE
- `rbi_blueprint.json` has invalid JSON — pre-existing issue, only 6 of 7 blueprints seed
