import warnings
warnings.filterwarnings('ignore')

from pathlib import Path
from multi_agent import ComplianceOrchestrator
from schemas.blueprint_schema import Blueprint, BlueprintCheck
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

BASE_DIR = Path(r"f:\LLM Engineering\projects\Legal_AI_Expert")
USER_ID = "f565c3cb-5a01-4fae-b00b-aa82935febb2"
DB_DIR = BASE_DIR / "user_sessions" / USER_ID / "vector_db"

blueprint = Blueprint(
    blueprint_id="TEST_02",
    name="Test Blueprint Missing",
    description="Testing missing context pipeline",
    checks=[
        BlueprintCheck(
            check_id="CHECK_3_NO_CONTEXT",
            focus="Find any invoice numbers.",
            rule="Document must contain an invoice number."
        )
    ]
)

from config import settings
settings.checkpointer_db_path = str(DB_DIR / "langgraph_checkpoints.sqlite")

orchestrator = ComplianceOrchestrator(db_dir=str(DB_DIR))
# Passing a fake target contract name ensures filter yields 0 docs,
# which triggers the "No document content was found" response.
result = orchestrator.run_blueprint_audit(
    target_contract="FAKE_NON_EXISTENT_DOC.pdf",
    blueprint=blueprint,
    session_hash="test_session",
    user_id=USER_ID
)

print("\n=== FINAL AUDIT RESULTS FOR MISSING DOC ===")
for res in result["audit_results"]:
    print(f"[{res.check_id}] Compliant: {res.is_compliant}")
    print(f"Details: {res.violation_details}")
    print("-" * 50)
