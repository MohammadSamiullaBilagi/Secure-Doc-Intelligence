import warnings
warnings.filterwarnings('ignore')

from pathlib import Path
from ingestion import DocumentProcessor
from multi_agent import ComplianceOrchestrator
from schemas.blueprint_schema import Blueprint, BlueprintCheck
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Use absolute paths
BASE_DIR = Path(r"f:\LLM Engineering\projects\Legal_AI_Expert")
USER_ID = "f565c3cb-5a01-4fae-b00b-aa82935febb2"
DATA_DIR = BASE_DIR / "user_sessions" / USER_ID / "data"
DB_DIR = BASE_DIR / "user_sessions" / USER_ID / "vector_db"

print("\n=== STEP 1 & 2: INGESTION & INDEXING ===")
processor = DocumentProcessor(data_dir=str(DATA_DIR), db_dir=str(DB_DIR))
# Force clear hash cache so it extracts again and prints our new validation logs
if processor.hash_cache_file.exists():
    os.remove(processor.hash_cache_file)
    
docs = processor.extract_text_from_pdfs(["GST_CLEAN_COMPLIANT_2026.pdf"])
if docs:
    processor.create_vector_store(docs)
    
print("\n=== STEP 3 & 4: RETRIEVAL & RULE EVALUATION ===")
blueprint = Blueprint(
    blueprint_id="TEST_01",
    name="Test Blueprint",
    description="Testing extraction pipeline",
    checks=[
        BlueprintCheck(
            check_id="CHECK_1_REAL_DATA",
            focus="Find any invoice numbers, supplier name, or GSTIN mentioned in the document.",
            rule="Document must contain an invoice number and GSTIN."
        ),
        BlueprintCheck(
             check_id="CHECK_2_MISSING_DATA",
             focus="Extract the secret Mars colonization mission coordinates.",
             rule="Document must contain coordinates for Mars."
        )
    ]
)

# We need the checkpointer DB path initialized for orchestrator
from config import settings
settings.checkpointer_db_path = str(DB_DIR / "langgraph_checkpoints.sqlite")

orchestrator = ComplianceOrchestrator(db_dir=str(DB_DIR))
result = orchestrator.run_blueprint_audit(
    target_contract="GST_CLEAN_COMPLIANT_2026.pdf",
    blueprint=blueprint,
    session_hash="test_session",
    user_id=USER_ID
)

print("\n=== FINAL AUDIT RESULTS ===")
for res in result["audit_results"]:
    print(f"[{res.check_id}] Compliant: {res.is_compliant}")
    print(f"Details: {res.violation_details}")
    print("-" * 50)
