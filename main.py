import os
import sys
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import sqlalchemy as sa
import uvicorn
import logging

from config import settings
from api.rate_limit import limiter

# Set up central logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Import custom routers
from api.routes import auth, documents, chat, audits, billing, payments, blueprints, reports, status, clients, calendar, notices
from api.routes import gst_reconciliation, bank_analysis, capital_gains, gstr9_recon, depreciation, advance_tax, feedback
from services.scheduler import start_background_tasks

app = FastAPI(
    title="Secure Doc-Intelligence SaaS API",
    description="Multi-tenant backend for Legal AI interactions, audits, and orchestrations.",
    version="2.0.0"
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Middleware stack (LIFO order — last added runs first)
# 1. SlowAPI middleware (runs AFTER CORS, so rate limiting only hits real requests)
app.add_middleware(SlowAPIMiddleware)

# 2. CORS middleware (runs FIRST — handles OPTIONS preflight before anything else)
origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.lovable\.app|https://.*\.lovableproject\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch-all handler — returns JSON instead of HTML traceback in production."""
    logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc) if not settings.is_production else "An unexpected error occurred"},
    )


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every incoming request for debugging frontend-backend connectivity."""
    # Log Origin header on ALL requests to diagnose CORS issues
    origin = request.headers.get("origin", "NO-ORIGIN")
    if request.method == "OPTIONS":
        logger.info(f"CORS PREFLIGHT: {request.url.path} | Origin: {origin}")
        response = await call_next(request)
        logger.info(f"CORS PREFLIGHT RESPONSE: {response.status_code} | Origin: {origin}")
        return response
    logger.info(f"→ {request.method} {request.url.path} from {request.client.host if request.client else 'unknown'} | Origin: {origin}")
    response = await call_next(request)
    logger.info(f"← {request.method} {request.url.path} → {response.status_code}")
    return response

# Mount all the routers
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(chat.router)
app.include_router(audits.router)
app.include_router(billing.router)
app.include_router(payments.router)
app.include_router(blueprints.router)
app.include_router(reports.router)
app.include_router(status.router)
app.include_router(clients.router)
app.include_router(calendar.router)
app.include_router(notices.router)
app.include_router(gst_reconciliation.router)
app.include_router(bank_analysis.router)
app.include_router(capital_gains.router)
app.include_router(gstr9_recon.router)
app.include_router(depreciation.router)
app.include_router(advance_tax.router)
app.include_router(feedback.router)


@app.on_event("startup")
async def startup_event():
    """Initializes necessary background operations on server boot."""
    logger.info("Initializing Secure Doc-Intelligence SaaS Backend Engine...")

    # Production safety: SECRET_KEY must be set
    if settings.is_production and (not settings.SECRET_KEY or settings.SECRET_KEY == "your-very-secret-key-change-in-production"):
        logger.critical("FATAL: SECRET_KEY is empty or default in production. Set it in .env or environment.")
        sys.exit(1)

    from db.database import engine, Base, AsyncSessionLocal
    from db.models import core  # noqa: F401
    from db.models import billing  # noqa: F401
    from db.models import clients as clients_models  # noqa: F401
    from db.models import calendar as calendar_models  # noqa: F401
    from db.models import notices as notices_models  # noqa: F401
    from db.models import feedback as feedback_models  # noqa: F401

    # Auto-create tables only for local SQLite dev; PostgreSQL uses Alembic migrations
    if settings.is_sqlite:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("SQLite dev tables auto-created.")
    else:
        logger.info("PostgreSQL mode — tables managed by Alembic migrations.")

    # Seed Indian tax deadlines (idempotent)
    try:
        from services.calendar_service import CalendarService
        async with AsyncSessionLocal() as session:
            await CalendarService.seed_indian_deadlines(session)
        logger.info("Tax calendar deadlines verified/seeded.")
    except Exception as e:
        logger.error(f"Error seeding tax deadlines: {e}")

    # Seed system blueprints from blueprints/*.json (idempotent)
    try:
        from services.blueprint_service import BlueprintService
        async with AsyncSessionLocal() as session:
            await BlueprintService.seed_system_blueprints(session)
        logger.info("System blueprints verified/seeded.")
    except Exception as e:
        logger.error(f"Error seeding system blueprints: {e}")

    # Auto-promote admin users (configured via ADMIN_EMAILS env var)
    admin_emails_str = settings.ADMIN_EMAILS
    if admin_emails_str:
        try:
            from sqlalchemy import select as sa_select
            from db.models.core import User as UserModel
            admin_emails = [e.strip() for e in admin_emails_str.split(",") if e.strip()]
            async with AsyncSessionLocal() as session:
                for email in admin_emails:
                    result = await session.execute(
                        sa_select(UserModel).where(UserModel.email == email)
                    )
                    user = result.scalar_one_or_none()
                    if user and not user.is_admin:
                        user.is_admin = True
                        await session.commit()
                        logger.info(f"Auto-promoted {email} to admin.")
                    elif user and user.is_admin:
                        logger.info(f"Admin already set for {email}.")
                    else:
                        logger.warning(f"Admin email {email} not found in DB — will be promoted on next login/register.")
        except Exception as e:
            logger.error(f"Error auto-promoting admins: {e}")

    # Background job scheduler (TTL sweep, knowledge scrape, email reminders)
    try:
        start_background_tasks()
        logger.info("Background TTL Scheduler verified.")
    except Exception as e:
        logger.error(f"Error starting background sweeps: {e}")


@app.options("/{rest_of_path:path}")
async def preflight_handler(request: Request, rest_of_path: str):
    """Catch-all OPTIONS handler — ensures preflight never returns 400/405."""
    from starlette.responses import PlainTextResponse
    origin = request.headers.get("origin", "*")
    return PlainTextResponse(
        "OK",
        headers={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
            "Access-Control-Allow-Headers": "content-type, authorization, ngrok-skip-browser-warning",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "600",
        },
    )


@app.get("/health")
async def health_check():
    """Health check with DB + ChromaDB connectivity for load balancers."""
    from db.database import AsyncSessionLocal

    checks = {}

    # Database check
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sa.text("SELECT 1"))
        checks["database"] = "connected"
    except Exception as e:
        checks["database"] = f"error: {str(e)}"

    # ChromaDB check
    try:
        import chromadb
        client = chromadb.PersistentClient(path=settings.GLOBAL_DB_DIR)
        client.heartbeat()
        checks["vector_db"] = "connected"
    except Exception as e:
        checks["vector_db"] = f"error: {str(e)}"

    all_ok = all(v == "connected" for v in checks.values())
    status_code = 200 if all_ok else 503

    from starlette.responses import JSONResponse as StarletteJSONResponse
    return StarletteJSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if all_ok else "degraded",
            "service": "legal-ai-expert-saas",
            "env": os.getenv("ENV", "development"),
            **checks,
        },
    )

if __name__ == "__main__":
    reload = os.getenv("ENV") == "development"  # defaults to False if ENV not set
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload)
