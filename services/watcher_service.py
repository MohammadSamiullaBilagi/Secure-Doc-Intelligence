import asyncio
import logging
from pathlib import Path
from services.blueprint_service import BlueprintService
from multi_agent import ComplianceOrchestrator
from config import settings

logger = logging.getLogger(__name__)

class WatcherService:
    @staticmethod
    async def _resolve_blueprint(selected_blueprint_file: str):
        """Resolve a blueprint identifier to a Blueprint object.
        
        Handles both:
        - UUID strings from the database (sent by the Lovable frontend)
        - Filename strings like 'gst_blueprint.json' (legacy/Gradio)
        """
        # Try loading as a UUID from the database first
        try:
            from uuid import UUID
            blueprint_uuid = UUID(selected_blueprint_file)  # validates AND converts to UUID object
            
            # It's a UUID — load from database
            from db.database import AsyncSessionLocal
            from db.models.core import Blueprint as BlueprintModel
            from sqlalchemy import select
            from schemas.blueprint_schema import Blueprint, BlueprintCheck
            
            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(BlueprintModel).where(BlueprintModel.id == blueprint_uuid)
                )
                bp = result.scalar_one_or_none()
                
                if bp and bp.rules_json:
                    logger.info(f"Resolved blueprint UUID '{selected_blueprint_file}' -> '{bp.name}'")
                    checks = [BlueprintCheck(**c) for c in bp.rules_json]
                    return Blueprint(
                        blueprint_id=str(bp.id),
                        name=bp.name,
                        description=bp.description or "",
                        checks=checks
                    )
                else:
                    logger.warning(f"Blueprint UUID '{selected_blueprint_file}' not found in DB, falling back to file")
        except (ValueError, TypeError):
            pass  # Not a UUID, try as filename
        
        # Fall back to filename-based loading
        return BlueprintService.load_blueprint(selected_blueprint_file)

    @staticmethod
    async def run_background_audit(session_hash: str, filename: str, selected_blueprint_file: str, user_id: str = "", thread_id: str = ""):
        logger.info(f"WATCHER ACTIVATED: Starting background audit for {filename} using {selected_blueprint_file}")

        # Import status updater for real-time UI streaming
        from api.routes.status import update_audit_status

        try:
            # Stage 1: Loading blueprint
            update_audit_status(thread_id, "loading_blueprint", "Loading compliance framework...", 10)
            blueprint = await WatcherService._resolve_blueprint(selected_blueprint_file)

            # Stage 2: Initializing
            update_audit_status(thread_id, "initializing", "Initializing AI audit agents...", 20)
            db_dir = str(Path(settings.user_sessions_dir) / session_hash / "vector_db")
            data_dir = str(Path(settings.user_sessions_dir) / session_hash / "data")
            orchestrator = ComplianceOrchestrator(db_dir=db_dir, data_dir=data_dir)

            # Stage 3: Running audit — run in thread pool so the async event loop is not blocked
            update_audit_status(thread_id, "researching", f"Researcher: Scanning {filename} for compliance checks...", 40)

            final_state = await asyncio.to_thread(
                orchestrator.run_blueprint_audit,
                target_contract=filename,
                blueprint=blueprint,
                session_hash=session_hash,
                user_id=user_id or session_hash,
                thread_id=thread_id,
            )

            # Stage 4: Persist compliance results back to AuditJob for dashboard/client linkage
            await WatcherService._store_audit_results(
                thread_id=thread_id,
                final_state=final_state,
                blueprint_name=blueprint.name if blueprint else None,
            )

            # Stage 5: Awaiting review
            update_audit_status(thread_id, "awaiting_review", "Audit complete! Awaiting your review.", 100)
            logger.info("WATCHER: Audit complete and paused. Awaiting Human-in-the-Loop approval.")

        except Exception as e:
            update_audit_status(thread_id, "error", f"Audit failed: {str(e)}", 0)
            logger.error(f"Watcher background task failed for {filename}: {e}")

    @staticmethod
    async def _store_audit_results(thread_id: str, final_state: dict, blueprint_name: str | None):
        """Persist compliance results from LangGraph state back to the AuditJob row.

        This populates results_summary (full JSON) and denormalized columns
        (compliance_score, open_violations, total_financial_exposure, blueprint_name)
        so the client dashboard can query them directly without touching LangGraph.
        """
        if not final_state or not thread_id:
            return

        try:
            from db.database import AsyncSessionLocal
            from db.models.core import AuditJob
            from sqlalchemy import select
            from services.report_service import ReportService

            audit_results = final_state.get("audit_results", [])
            risk_report = final_state.get("risk_report", "")

            # Compute compliance score
            score, violations = ReportService.compute_compliance_score(final_state)

            # Compute total financial exposure from individual check results
            total_exposure = 0.0
            serialized_results = []
            for r in audit_results:
                if isinstance(r, dict):
                    rd = r
                else:
                    rd = r.__dict__ if hasattr(r, '__dict__') else {}
                    # Handle Pydantic models
                    if hasattr(r, 'model_dump'):
                        rd = r.model_dump()

                fi = rd.get("financial_impact")
                if fi and isinstance(fi, dict) and fi.get("estimated_amount"):
                    total_exposure += float(fi["estimated_amount"])

                serialized_results.append({
                    "check_id": rd.get("check_id", ""),
                    "focus": rd.get("focus", ""),
                    "compliance_status": rd.get("compliance_status", ""),
                    "evidence": rd.get("evidence", ""),
                    "violation_details": rd.get("violation_details", ""),
                    "suggested_amendment": rd.get("suggested_amendment", ""),
                    "financial_impact": fi,
                    "confidence": rd.get("confidence", ""),
                })

            results_summary = {
                "audit_results": serialized_results,
                "risk_report": risk_report,
                "compliance_score": score,
                "open_violations": violations,
                "total_financial_exposure": total_exposure,
            }

            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(AuditJob).where(AuditJob.langgraph_thread_id == thread_id)
                )
                jobs = result.scalars().all()
                for job in jobs:
                    job.results_summary = results_summary
                    job.blueprint_name = blueprint_name
                    job.compliance_score = score
                    job.open_violations = violations
                    job.total_financial_exposure = total_exposure
                await session.commit()

            logger.info(
                f"WATCHER: Stored results for thread {thread_id}: "
                f"score={score}, violations={violations}, exposure={total_exposure:.2f}"
            )

        except Exception as e:
            logger.error(f"WATCHER: Failed to store audit results for {thread_id}: {e}")