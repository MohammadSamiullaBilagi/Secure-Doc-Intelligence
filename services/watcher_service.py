import logging
from pathlib import Path
from services.blueprint_service import BlueprintService
from multi_agent import ComplianceOrchestrator
from config import settings

logger = logging.getLogger(__name__)

class WatcherService:
    @staticmethod
    async def run_background_audit(session_hash: str, filename: str, selected_blueprint_file: str):
        logger.info(f"WATCHER ACTIVATED: Starting background audit for {filename} using {selected_blueprint_file}")
        
        try:
            # 1. Load the blueprint
            blueprint = BlueprintService.load_blueprint(selected_blueprint_file)
            
            # 2. Get the DB directory
            db_dir = str(Path(settings.user_sessions_dir) / session_hash / "vector_db")
            
            # 3. Initialize Orchestrator
            orchestrator = ComplianceOrchestrator(db_dir=db_dir)
            
            # 4. Run the Graph. 
            # Because of the SqliteSaver checkpointer, this will automatically PAUSE before dispatching.
            # Do NOT call WebhookService or generate_pdf here!
            orchestrator.run_blueprint_audit(
                target_contract=filename,
                blueprint=blueprint,
                session_hash=session_hash
            )
            
            logger.info("WATCHER: Audit complete and paused. Awaiting Human-in-the-Loop approval.")
            
        except Exception as e:
            logger.error(f"Watcher background task failed for {filename}: {e}")