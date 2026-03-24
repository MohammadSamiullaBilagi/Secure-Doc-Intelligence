"""Compliance scan accuracy test — validates pipeline results against expected answers.

Usage:
    python test_compliance_accuracy.py                              # All 3 PDFs
    python test_compliance_accuracy.py --pdf test_gst_invoice.pdf   # Single PDF
"""

import argparse
import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

# ─── Expected answers ────────────────────────────────────────────────────────
# Each entry: (check_id, expected_status, evidence_keywords, expect_financial_impact)

GST_EXPECTED = [
    ("GST_01_INVOICE_MANDATORY_FIELDS", "PARTIAL",
     ["hsn", "sac", "not provided", "signature", "rule 46"],
     False),
    ("GST_02_GSTIN_VALIDATION", "COMPLIANT",
     ["29AAECP4321R1ZK", "state code", "pan"],
     False),
    ("GST_03_E_INVOICE_COMPLIANCE", "NON_COMPLIANT",
     ["irn", "not available", "qr code", "irp"],
     True),
    ("GST_04_BLOCKED_ITC_SECTION_17_5", "NON_COMPLIANT",
     ["17(5)", "club", "catering", "health", "blocked"],
     True),
    ("GST_05_RULE_36_4_RECONCILIATION", "NON_COMPLIANT",
     ["gstr-2b", "not reflected", "rule 36"],
     False),  # Financial impact may or may not be present
    ("MSME_06_SECTION_43B_H", "NON_COMPLIANT",
     ["50 days", "45 day", "43b", "msme", "payment"],
     True),
    ("GST_07_TAX_RATE_VALIDATION", "INCONCLUSIVE",
     ["hsn", "sac", "not provided", "cannot validate"],
     False),
]

TDS_EXPECTED = [
    ("TDS_01_DEDUCTION_AT_CORRECT_RATE", "PARTIAL",
     ["194j", "cloudbase", "ramesh", "rate"],
     True),
    ("TDS_02_TIMELY_DEPOSIT_CHALLAN", "PARTIAL",
     ["march", "30-apr", "194s", "vda"],
     False),
    ("TDS_03_QUARTERLY_RETURN_FILING", "PARTIAL",
     ["q3", "late", "234e", "14 day"],
     True),
    ("TDS_04_FORM_16_16A_ISSUANCE", "PARTIAL",
     ["q3", "late", "16a", "272a"],
     True),
    ("TDS_05_194A_BANK_INTEREST_THRESHOLD", "COMPLIANT",
     ["sbi", "85,000", "50,000", "194a"],
     False),
    ("TDS_06_SECTION_194S_VDA_CRYPTO", "NON_COMPLIANT",
     ["wazirx", "bitcoin", "194s", "2,50,000", "nil"],
     True),
    ("TDS_07_LOWER_DEDUCTION_CERTIFICATE_VALIDITY", "INCONCLUSIVE",
     ["form 13", "no", "certificate"],
     False),
    ("TDS_08_PAN_VERIFICATION_HIGHER_RATE", "NON_COMPLIANT",
     ["ramesh", "pan", "206aa", "20%"],
     True),
    ("TDS_09_FORM_15G_15H_VALIDITY", "NON_COMPLIANT",
     ["orbit", "15g", "6,75,000", "vinod"],
     True),
    ("TDS_10_TAN_REGISTRATION_AND_QUOTING", "COMPLIANT",
     ["blrn12345e", "tan"],
     False),
]

IT_EXPECTED = [
    ("IT_01_SECTION_44AB_APPLICABILITY", "COMPLIANT",
     ["turnover", "1 crore", "44ab", "audit"],
     False),
    ("IT_02_FORM_3CD_CLAUSE_19_DEDUCTIONS", "PARTIAL",
     ["depreciation", "schedule", "3cd", "clause 19"],
     False),
    ("IT_03_SECTION_40A3_CASH_PAYMENTS", "NON_COMPLIANT",
     ["cash", "10,000", "40a(3)", "transport"],
     True),
    ("IT_04_SECTION_43B_STATUTORY_DUES", "NON_COMPLIANT",
     ["pf", "81,000", "25-may", "36(1)(va)"],
     True),
    ("IT_05_CAPITAL_GAINS_CLASSIFICATION", "PARTIAL",
     ["reliance", "gold", "ltcg", "stcg"],
     False),
    ("IT_06_CHAPTER_VIA_DEDUCTIONS", "INCONCLUSIVE",
     ["80c", "80d", "vi-a", "not visible"],
     False),
    ("IT_07_ADVANCE_TAX_COMPLIANCE", "NON_COMPLIANT",
     ["234c", "shortfall", "advance tax"],
     True),
    ("IT_08_RETURN_FILING_DUE_DATE", "INCONCLUSIVE",
     ["31-oct", "2026", "not yet filed"],
     False),
    ("IT_09_SECTION_40A_IA_TDS_DISALLOWANCE", "NON_COMPLIANT",
     ["rent", "194i", "6,60,000", "40(a)(ia)", "30%"],
     True),
    ("IT_10_SECTION_36_1_VA_EMPLOYEE_PF_ESI", "NON_COMPLIANT",
     ["pf", "81,000", "36(1)(va)"],
     True),
    ("IT_11_SECTION_14A_EXEMPT_INCOME_DISALLOWANCE", "NON_COMPLIANT",
     ["14a", "dividend", "rule 8d", "15,000"],
     True),
    ("IT_12_RELATED_PARTY_TRANSACTIONS_DISCLOSURE", "NON_COMPLIANT",
     ["harish", "40a(2)", "4,50,000", "1,70,000"],
     True),
]

TEST_CONFIGS = {
    "test_gst_invoice.pdf": {
        "blueprint": "blueprints/gst_blueprint.json",
        "expected": GST_EXPECTED,
    },
    "test_tds_compliance.pdf": {
        "blueprint": "blueprints/tds_blueprint.json",
        "expected": TDS_EXPECTED,
    },
    "test_income_tax_pl.pdf": {
        "blueprint": "blueprints/income_tax_blueprint.json",
        "expected": IT_EXPECTED,
    },
}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_field(result, field: str, default=""):
    """Get a field from either a dict or a Pydantic-like object."""
    if isinstance(result, dict):
        return result.get(field, default)
    return getattr(result, field, default)


def _normalize_status(status: str) -> str:
    """Normalize compliance status for comparison."""
    s = status.upper().strip().replace(" ", "_")
    for prefix in ("NON_COMP", "NON-COMP"):
        if s.startswith(prefix):
            return "NON_COMPLIANT"
    if s.startswith("INCONCLUS"):
        return "INCONCLUSIVE"
    return s


def _check_evidence(actual_evidence: str, keywords: list[str]) -> bool:
    """Check if at least 40% of expected keywords appear in the evidence."""
    if not actual_evidence:
        return False
    evidence_lower = actual_evidence.lower()
    hits = sum(1 for kw in keywords if kw.lower() in evidence_lower)
    return hits >= max(1, len(keywords) * 0.4)


# ─── Core test runner ─────────────────────────────────────────────────────────

def run_single_test(pdf_name: str, config: dict) -> dict:
    """Run the full compliance pipeline on one PDF and return scores."""
    from schemas.blueprint_schema import Blueprint
    from multi_agent import ComplianceOrchestrator

    pdf_path = Path(pdf_name)
    if not pdf_path.exists():
        print(f"  SKIP: {pdf_name} not found")
        return {"skipped": True, "pdf": pdf_name}

    blueprint_path = Path(config["blueprint"])
    if not blueprint_path.exists():
        print(f"  SKIP: Blueprint {config['blueprint']} not found")
        return {"skipped": True, "pdf": pdf_name}

    # Load blueprint
    with open(blueprint_path) as f:
        bp_data = json.load(f)
    blueprint = Blueprint(**bp_data)

    expected = config["expected"]
    expected_ids = {e[0] for e in expected}

    # Create temp vector DB directory
    temp_dir = tempfile.mkdtemp(prefix="compliance_test_")
    data_dir = str(pdf_path.parent.resolve())

    try:
        # Ingest the PDF into temp vector store
        print(f"  Ingesting {pdf_name}...")
        _ingest_pdf(pdf_path, temp_dir)

        # Run the orchestrator
        print(f"  Running {len(blueprint.checks)}-check compliance scan...")
        orchestrator = ComplianceOrchestrator(db_dir=temp_dir, data_dir=data_dir)

        import uuid
        thread_id = str(uuid.uuid4())

        start = time.time()
        final_state = orchestrator.run_blueprint_audit(
            target_contract=pdf_name,
            blueprint=blueprint,
            session_hash="test_accuracy",
            user_id="test_user",
            thread_id=thread_id,
        )
        elapsed = time.time() - start
        print(f"  Pipeline completed in {elapsed:.1f}s")

        # Extract results
        audit_results = final_state.get("audit_results", [])
        results_by_id = {}
        for r in audit_results:
            cid = _get_field(r, "check_id", "")
            results_by_id[cid] = r

        # Score
        status_matches = 0
        evidence_matches = 0
        fi_expected = 0
        fi_present = 0
        details = []

        for check_id, exp_status, evidence_kw, expect_fi in expected:
            actual = results_by_id.get(check_id)
            if not actual:
                details.append({
                    "check_id": check_id,
                    "expected": exp_status,
                    "actual": "MISSING",
                    "status_match": False,
                    "evidence_match": False,
                })
                if expect_fi:
                    fi_expected += 1
                continue

            actual_status = _normalize_status(_get_field(actual, "compliance_status", ""))
            exp_norm = _normalize_status(exp_status)

            s_match = actual_status == exp_norm
            if s_match:
                status_matches += 1

            actual_evidence = _get_field(actual, "evidence", "")
            e_match = _check_evidence(actual_evidence, evidence_kw)
            if e_match:
                evidence_matches += 1

            if expect_fi:
                fi_expected += 1
                fi = _get_field(actual, "financial_impact")
                if fi and (isinstance(fi, dict) and fi.get("estimated_amount")) or \
                   (hasattr(fi, "estimated_amount") and fi.estimated_amount):
                    fi_present += 1

            details.append({
                "check_id": check_id,
                "expected": exp_norm,
                "actual": actual_status,
                "status_match": s_match,
                "evidence_match": e_match,
            })

        return {
            "skipped": False,
            "pdf": pdf_name,
            "total_checks": len(expected),
            "status_matches": status_matches,
            "evidence_matches": evidence_matches,
            "fi_expected": fi_expected,
            "fi_present": fi_present,
            "elapsed": elapsed,
            "details": details,
        }

    finally:
        # Cleanup temp dir
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass


def _ingest_pdf(pdf_path: Path, db_dir: str):
    """Ingest a single PDF into a ChromaDB vector store at db_dir."""
    import pymupdf
    from langchain_openai import OpenAIEmbeddings
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    # Extract text
    doc = pymupdf.open(str(pdf_path))
    pages_text = []
    try:
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text("text").strip()

            # Try pdfplumber for tables
            try:
                import pdfplumber
                with pdfplumber.open(str(pdf_path)) as pl_doc:
                    pl_page = pl_doc.pages[page_num]
                    if not text:
                        extracted = pl_page.extract_text()
                        if extracted:
                            text = extracted.strip()
                    tables = pl_page.extract_tables()
                    if tables:
                        table_text = "\n".join([
                            " | ".join([cell if cell else "" for cell in row])
                            for table in tables for row in table
                        ])
                        text += "\n\n[TABLE DATA]:\n" + table_text
            except Exception:
                pass

            # OCR fallback
            if not text:
                try:
                    from PIL import Image
                    import pytesseract
                    zoom_matrix = pymupdf.Matrix(2, 2)
                    pix = page.get_pixmap(matrix=zoom_matrix)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    text = pytesseract.image_to_string(img).strip()
                except Exception:
                    pass

            if text:
                pages_text.append(Document(
                    page_content=text,
                    metadata={"source": pdf_path.name, "page": page_num + 1},
                ))
    finally:
        doc.close()

    if not pages_text:
        print(f"  WARNING: No text extracted from {pdf_path.name}")
        return

    # Chunk and embed
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = splitter.split_documents(pages_text)

    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    Chroma.from_documents(
        chunks,
        embedding=embeddings,
        persist_directory=db_dir,
        collection_name="user_docs",
    )
    print(f"  Ingested {len(chunks)} chunks from {pdf_path.name}")


# ─── Output ──────────────────────────────────────────────────────────────────

def print_scorecard(results: list[dict]):
    """Print a formatted scorecard for all test results."""
    w = 66

    print()
    print("=" * w)
    print("  COMPLIANCE SCAN ACCURACY REPORT")
    print("=" * w)

    total_status = 0
    total_evidence = 0
    total_checks = 0
    total_fi_expected = 0
    total_fi_present = 0

    for r in results:
        if r.get("skipped"):
            print(f"\n  {r['pdf']}: SKIPPED")
            continue

        print(f"\n  {r['pdf']} ({r['elapsed']:.1f}s)")
        print("-" * w)
        print(f"  {'Check ID':<40} {'Expected':<12} {'Actual':<12} Match?")
        print("-" * w)

        for d in r["details"]:
            exp_short = d["expected"][:10]
            act_short = d["actual"][:10]
            mark = "Y" if d["status_match"] else "N"
            print(f"  {d['check_id']:<40} {exp_short:<12} {act_short:<12} {mark}")

        sc = r["status_matches"]
        tc = r["total_checks"]
        ec = r["evidence_matches"]
        fi_e = r["fi_expected"]
        fi_p = r["fi_present"]

        print("-" * w)
        print(f"  Status Accuracy:    {sc}/{tc} ({sc/tc*100:.0f}%)")
        print(f"  Evidence Accuracy:  {ec}/{tc} ({ec/tc*100:.0f}%)")
        if fi_e > 0:
            print(f"  Financial Impact:   {fi_p}/{fi_e} violations have FI ({fi_p/fi_e*100:.0f}%)")
        else:
            print(f"  Financial Impact:   N/A (no violations expected)")

        total_status += sc
        total_evidence += ec
        total_checks += tc
        total_fi_expected += fi_e
        total_fi_present += fi_p

    # Overall
    if total_checks > 0:
        print()
        print("=" * w)
        s_pct = total_status / total_checks * 100
        e_pct = total_evidence / total_checks * 100
        fi_pct = total_fi_present / total_fi_expected * 100 if total_fi_expected else 100
        overall = (s_pct * 0.5) + (e_pct * 0.3) + (fi_pct * 0.2)

        print(f"  OVERALL Status Accuracy:    {total_status}/{total_checks} ({s_pct:.0f}%)")
        print(f"  OVERALL Evidence Accuracy:  {total_evidence}/{total_checks} ({e_pct:.0f}%)")
        if total_fi_expected:
            print(f"  OVERALL Financial Impact:   {total_fi_present}/{total_fi_expected} ({fi_pct:.0f}%)")
        print(f"  COMPOSITE SCORE: {overall:.0f}%", end="")
        if overall >= 80:
            print(" — PRODUCTION READY")
        elif overall >= 60:
            print(" — PROMPT ENGINEERING NEEDED")
        else:
            print(" — BLUEPRINT RULES NEED REWRITE")
        print("=" * w)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Compliance scan accuracy test")
    parser.add_argument("--pdf", type=str, help="Test a single PDF (e.g. test_gst_invoice.pdf)")
    parser.add_argument("--verbose", action="store_true", help="Show debug logs")
    args = parser.parse_args()

    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")

    # Ensure we're in the project root
    project_root = Path(__file__).parent.resolve()
    os.chdir(project_root)

    if args.pdf:
        if args.pdf not in TEST_CONFIGS:
            print(f"Unknown PDF: {args.pdf}")
            print(f"Available: {', '.join(TEST_CONFIGS.keys())}")
            sys.exit(1)
        configs = {args.pdf: TEST_CONFIGS[args.pdf]}
    else:
        configs = TEST_CONFIGS

    results = []
    for pdf_name, config in configs.items():
        print(f"\n{'='*50}")
        print(f"Testing: {pdf_name}")
        print(f"{'='*50}")
        result = run_single_test(pdf_name, config)
        results.append(result)

    print_scorecard(results)


if __name__ == "__main__":
    main()
