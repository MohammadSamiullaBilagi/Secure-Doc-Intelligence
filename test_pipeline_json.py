import asyncio
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

sys.path.append(str(Path(__file__).resolve().parent))

from schemas.blueprint_schema import Blueprint
from multi_agent import ComplianceOrchestrator
from ingestion import DocumentProcessor

async def main():
    # Load the real GST Blueprint
    with open("blueprints/gst_blueprint.json", "r") as f:
        bp_dict = json.load(f)
    blueprint = Blueprint(**bp_dict)

    # Use a test directory with a real PDF
    DATA_DIR = Path("user_sessions/f565c3cb-5a01-4fae-b00b-aa82935febb2/data")
    DB_DIR = Path("test_vector_db_v3")
    DB_DIR.mkdir(parents=True, exist_ok=True)
    
    target_doc = "GST_MINOR_RISK_2026.pdf"
    pdf_path = DATA_DIR / target_doc
    
    if not pdf_path.exists():
        print(f"ERROR: PDF not found at {pdf_path}. Cannot run test without real document.")
        return
    
    # 0. INGEST: Extract text and create vector store from real PDF
    print(f"\n[STEP 0] INGESTING {target_doc} from {DATA_DIR} into {DB_DIR}...")
    processor = DocumentProcessor(data_dir=str(DATA_DIR), db_dir=str(DB_DIR))
    docs = processor.extract_text_from_pdfs(only_files=[target_doc])
    if docs:
        processor.create_vector_store(docs)
        print(f"  Ingested {len(docs)} pages/documents into vector store.")
    else:
        print("  No new documents extracted (may be cached).")
    
    # 1. RUN THE PIPELINE with data_dir for fallback
    print(f"\n[STEP 1] Running compliance audit pipeline...")
    orchestrator = ComplianceOrchestrator(db_dir=str(DB_DIR), data_dir=str(DATA_DIR))
    
    result_state = orchestrator.run_blueprint_audit(
        target_contract=target_doc,
        blueprint=blueprint,
        session_hash="test_session_v3",
        user_id="test_user"
    )
    
    print("\n" + "="*60)
    print("  EXTRACT -> VERIFY -> MAP -> AUDIT VALIDATION RESULTS")
    print("="*60)
    
    # 2. Check extracted fields
    extracted = result_state.get('extracted_fields', {}) if isinstance(result_state, dict) else getattr(result_state, 'extracted_fields', {})
    non_null = sum(1 for v in extracted.values() if v is not None)
    print(f"\n[STAGE 3 - MAPPING]: Extracted {len(extracted)} fields ({non_null} non-null)")
    print(json.dumps(extracted, indent=2))
    
    # 3. Check compliance results
    print("\n[STAGE 4 - AUDIT RESULTS]:")
    audit_results = result_state.get('audit_results', []) if isinstance(result_state, dict) else getattr(result_state, 'audit_results', [])
    
    compliant_count = 0
    non_compliant_count = 0
    partial_count = 0
    
    for res in audit_results:
        status = getattr(res, 'compliance_status', 'UNKNOWN')
        print(f"\nRule: {getattr(res, 'rule', '')[:60]}...")
        print(f"Status:   {status}")
        print(f"Evidence: {getattr(res, 'evidence', '')}")
        if status != "COMPLIANT":
            print(f"Issue:    {getattr(res, 'violation_details', '')}")
        
        if status == "COMPLIANT": compliant_count += 1
        elif status == "PARTIAL": partial_count += 1
        else: non_compliant_count += 1
    
    print(f"\n{'='*60}")
    print(f"SUMMARY: {compliant_count} COMPLIANT, {partial_count} PARTIAL, {non_compliant_count} NON_COMPLIANT")
    print(f"{'='*60}")
            
    print("\n[EXECUTIVE REPORT]:")
    report = result_state.get('risk_report', '') if isinstance(result_state, dict) else getattr(result_state, 'risk_report', '')
    print(report)

if __name__ == "__main__":
    asyncio.run(main())
