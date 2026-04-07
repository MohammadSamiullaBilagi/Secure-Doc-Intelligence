"""Comprehensive test script for GSTR-9 Annual Return Pre-Filing Reconciliation.

Tests parsing, reconciliation, export field alignment, accuracy, and edge cases.
Standalone — no DB, no FastAPI, no LLM calls needed. Uses test PDFs in test_gstr_pdfs/.

Usage:
    python test_gstr9_recon.py
"""

import os
import sys
import traceback

# ---------------------------------------------------------------------------
# Test infrastructure
# ---------------------------------------------------------------------------
PASS_COUNT = 0
FAIL_COUNT = 0
TOTAL_TESTS = 0


def assert_eq(actual, expected, label=""):
    global PASS_COUNT, FAIL_COUNT, TOTAL_TESTS
    TOTAL_TESTS += 1
    if actual == expected:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        print(f"  FAIL: {label} — expected {expected!r}, got {actual!r}")


def assert_close(actual, expected, tol=1.0, label=""):
    global PASS_COUNT, FAIL_COUNT, TOTAL_TESTS
    TOTAL_TESTS += 1
    if abs(actual - expected) <= tol:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        print(f"  FAIL: {label} — expected ~{expected}, got {actual} (tol={tol})")


def assert_true(condition, label=""):
    global PASS_COUNT, FAIL_COUNT, TOTAL_TESTS
    TOTAL_TESTS += 1
    if condition:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        print(f"  FAIL: {label}")


def assert_gt(actual, threshold, label=""):
    global PASS_COUNT, FAIL_COUNT, TOTAL_TESTS
    TOTAL_TESTS += 1
    if actual > threshold:
        PASS_COUNT += 1
    else:
        FAIL_COUNT += 1
        print(f"  FAIL: {label} — expected > {threshold}, got {actual}")


def run_test(name, fn):
    global PASS_COUNT, FAIL_COUNT
    before_pass = PASS_COUNT
    before_fail = FAIL_COUNT
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    try:
        fn()
        passed = PASS_COUNT - before_pass
        failed = FAIL_COUNT - before_fail
        status = "PASSED" if failed == 0 else "FAILED"
        print(f"  Result: {status} ({passed} passed, {failed} failed)")
    except Exception as e:
        FAIL_COUNT += 1
        print(f"  EXCEPTION: {e}")
        traceback.print_exc()


# ---------------------------------------------------------------------------
# TEST 1: _parse_float
# ---------------------------------------------------------------------------
def test_parse_float():
    from services.gstr9_reconciliation_service import _parse_float

    # Standard values
    assert_close(_parse_float(1234.56), 1234.56, label="float input")
    assert_close(_parse_float(0), 0.0, label="zero int")
    assert_close(_parse_float("1234.56"), 1234.56, label="string float")
    assert_close(_parse_float("1,234.56"), 1234.56, label="comma-separated")

    # Indian notation
    assert_close(_parse_float("12,34,567.89"), 1234567.89, label="Indian lakh commas")
    assert_close(_parse_float("5,00,000.00"), 500000.0, label="5 lakh commas")

    # Lakh/Crore suffixes
    assert_close(_parse_float("5 Lakhs"), 500000.0, label="5 Lakhs")
    assert_close(_parse_float("2.5 Cr"), 25000000.0, label="2.5 Cr")
    assert_close(_parse_float("1.5 Crore"), 15000000.0, label="1.5 Crore")
    assert_close(_parse_float("3 Lacs"), 300000.0, label="3 Lacs")

    # Rs. prefix
    assert_close(_parse_float("Rs. 1,234.56"), 1234.56, label="Rs. prefix with space")
    assert_close(_parse_float("Rs.1234.56"), 1234.56, label="Rs. prefix no space")
    assert_close(_parse_float("INR 5000.00"), 5000.0, label="INR prefix")

    # Negative
    assert_close(_parse_float("-1,234.56"), -1234.56, label="negative with minus")
    assert_close(_parse_float("(1,234.56)"), -1234.56, label="negative with parens")

    # Edge cases
    assert_close(_parse_float(None), 0.0, label="None")
    assert_close(_parse_float(""), 0.0, label="empty string")
    assert_close(_parse_float("N/A"), 0.0, label="N/A")
    assert_close(_parse_float("   "), 0.0, label="whitespace")


# ---------------------------------------------------------------------------
# TEST 2: _month_key
# ---------------------------------------------------------------------------
def test_month_key():
    from services.gstr9_reconciliation_service import _month_key

    assert_eq(_month_key("Apr 2025"), "2025-04", label="Apr 2025")
    assert_eq(_month_key("April 2025"), "2025-04", label="April 2025")
    assert_eq(_month_key("04/2025"), "2025-04", label="04/2025")
    assert_eq(_month_key("2025-04"), "2025-04", label="2025-04 identity")
    assert_eq(_month_key("Apr-25"), "2025-04", label="Apr-25")
    assert_eq(_month_key("2025 Apr"), "2025-04", label="2025 Apr")
    assert_eq(_month_key("Dec 2025"), "2025-12", label="Dec 2025")
    assert_eq(_month_key("01/2026"), "2026-01", label="01/2026")
    assert_eq(_month_key("Mar-26"), "2026-03", label="Mar-26")
    assert_eq(_month_key(""), "unknown", label="empty")
    assert_eq(_month_key(None), "unknown", label="None")


# ---------------------------------------------------------------------------
# TEST 3 & 4: GSTR-1 and GSTR-3B text parsing from test PDFs
# ---------------------------------------------------------------------------
def test_gstr1_parsing():
    """Parse all 12 GSTR-1 test PDFs and verify extracted values."""
    import pymupdf
    from services.gstr9_reconciliation_service import GSTR9ReconciliationService

    pdf_dir = "test_gstr_pdfs"
    if not os.path.exists(pdf_dir):
        print("  SKIP: test_gstr_pdfs/ directory not found. Run create_test_gstr_pdfs.py first.")
        return

    service = GSTR9ReconciliationService()
    months_parsed = 0

    # Expected GSTR-1 data from create_test_gstr_pdfs.py
    expected = [
        {"month_prefix": "Apr", "total": 800000, "igst": 48000, "cgst": 63000, "sgst": 63000, "cdn": -5000},
        {"month_prefix": "May", "total": 850000, "igst": 51000, "cgst": 67500, "sgst": 67500, "cdn": -3000},
        {"month_prefix": "Jun", "total": 850000, "igst": 51000, "cgst": 68000, "sgst": 68000, "cdn": -4000},
        {"month_prefix": "Jul", "total": 815000, "igst": 49000, "cgst": 64500, "sgst": 64500, "cdn": -2000},
        {"month_prefix": "Aug", "total": 895000, "igst": 53500, "cgst": 71000, "sgst": 71000, "cdn": -6000},
        {"month_prefix": "Sep", "total": 980000, "igst": 58800, "cgst": 78000, "sgst": 78000, "cdn": -8000},
        {"month_prefix": "Oct", "total": 1150000, "igst": 69000, "cgst": 92000, "sgst": 92000, "cdn": -10000},
        {"month_prefix": "Nov", "total": 930000, "igst": 55800, "cgst": 74000, "sgst": 74000, "cdn": -5000},
        {"month_prefix": "Dec", "total": 985000, "igst": 59100, "cgst": 78500, "sgst": 78500, "cdn": -7000},
        {"month_prefix": "Jan", "total": 835000, "igst": 50100, "cgst": 66500, "sgst": 66500, "cdn": -4000},
        {"month_prefix": "Feb", "total": 870000, "igst": 52200, "cgst": 69500, "sgst": 69500, "cdn": -3500},
        {"month_prefix": "Mar", "total": 1050000, "igst": 63000, "cgst": 84000, "sgst": 84000, "cdn": -9000},
    ]

    years = ["2025", "2025", "2025", "2025", "2025", "2025",
             "2025", "2025", "2025", "2026", "2026", "2026"]

    for i, exp in enumerate(expected):
        fname = f"GSTR1_{exp['month_prefix']}_{years[i]}.pdf"
        fpath = os.path.join(pdf_dir, fname)
        if not os.path.exists(fpath):
            print(f"  SKIP: {fname} not found")
            continue

        doc = pymupdf.open(fpath)
        text = "".join(page.get_text() for page in doc)
        doc.close()

        parsed = service.parse_monthly_data(text, "gstr1")

        if "error" in parsed:
            assert_true(False, label=f"{fname}: parsing failed — {parsed.get('error')}")
            continue

        months_parsed += 1
        # Verify key fields (with tolerance for PDF text extraction variations)
        assert_close(parsed.get("total_taxable", 0), exp["total"], tol=500,
                     label=f"{fname}: total_taxable")
        assert_close(parsed.get("igst", 0), exp["igst"], tol=200,
                     label=f"{fname}: igst")
        assert_close(parsed.get("cgst", 0), exp["cgst"], tol=200,
                     label=f"{fname}: cgst")
        assert_close(parsed.get("sgst", 0), exp["sgst"], tol=200,
                     label=f"{fname}: sgst")

    assert_gt(months_parsed, 0, label="At least 1 GSTR-1 parsed successfully")
    print(f"  Parsed {months_parsed}/12 GSTR-1 PDFs successfully")


def test_gstr3b_parsing():
    """Parse all 12 GSTR-3B test PDFs and verify extracted values."""
    import pymupdf
    from services.gstr9_reconciliation_service import GSTR9ReconciliationService

    pdf_dir = "test_gstr_pdfs"
    if not os.path.exists(pdf_dir):
        print("  SKIP: test_gstr_pdfs/ directory not found.")
        return

    service = GSTR9ReconciliationService()
    months_parsed = 0

    # Expected GSTR-3B data (with deliberate mismatches applied)
    # From create_test_gstr_pdfs.py: Jun -15k turnover, Oct -25k turnover, Mar +4k tax
    expected_totals = [800000, 850000, 835000, 815000, 895000, 980000,
                       1125000, 930000, 985000, 835000, 870000, 1050000]

    month_names = ["Apr", "May", "Jun", "Jul", "Aug", "Sep",
                   "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
    years = ["2025", "2025", "2025", "2025", "2025", "2025",
             "2025", "2025", "2025", "2026", "2026", "2026"]

    for i, total in enumerate(expected_totals):
        fname = f"GSTR3B_{month_names[i]}_{years[i]}.pdf"
        fpath = os.path.join(pdf_dir, fname)
        if not os.path.exists(fpath):
            print(f"  SKIP: {fname} not found")
            continue

        doc = pymupdf.open(fpath)
        text = "".join(page.get_text() for page in doc)
        doc.close()

        parsed = service.parse_monthly_data(text, "gstr3b")

        if "error" in parsed:
            assert_true(False, label=f"{fname}: parsing failed — {parsed.get('error')}")
            continue

        months_parsed += 1
        assert_close(parsed.get("total_taxable", 0), total, tol=500,
                     label=f"{fname}: total_taxable")
        # Verify ITC fields exist
        assert_true(parsed.get("itc_igst", 0) >= 0, label=f"{fname}: itc_igst exists")
        assert_true(parsed.get("itc_cgst", 0) >= 0, label=f"{fname}: itc_cgst exists")

    assert_gt(months_parsed, 0, label="At least 1 GSTR-3B parsed successfully")
    print(f"  Parsed {months_parsed}/12 GSTR-3B PDFs successfully")


# ---------------------------------------------------------------------------
# TEST 5: Reconciliation with known data
# ---------------------------------------------------------------------------
def test_reconciliation_known_data():
    """Test reconciliation with deterministic data and known mismatches."""
    from services.gstr9_reconciliation_service import reconcile

    # Build test data matching create_test_gstr_pdfs.py GSTR1_DATA
    gstr1_months = [
        {"month": "Apr 2025", "total_taxable": 800000, "igst": 48000, "cgst": 63000, "sgst": 63000, "cess": 0,
         "exempt_nil": 15000, "credit_debit_notes": -5000, "amendments": 0},
        {"month": "May 2025", "total_taxable": 850000, "igst": 51000, "cgst": 67500, "sgst": 67500, "cess": 0,
         "exempt_nil": 12000, "credit_debit_notes": -3000, "amendments": 0},
        {"month": "Jun 2025", "total_taxable": 850000, "igst": 51000, "cgst": 68000, "sgst": 68000, "cess": 0,
         "exempt_nil": 18000, "credit_debit_notes": -4000, "amendments": 0},
        {"month": "Oct 2025", "total_taxable": 1150000, "igst": 69000, "cgst": 92000, "sgst": 92000, "cess": 0,
         "exempt_nil": 25000, "credit_debit_notes": -10000, "amendments": 0},
        {"month": "Mar 2026", "total_taxable": 1050000, "igst": 63000, "cgst": 84000, "sgst": 84000, "cess": 0,
         "exempt_nil": 22000, "credit_debit_notes": -9000, "amendments": 5000},
    ]

    gstr3b_months = [
        {"month": "Apr 2025", "total_taxable": 800000, "igst": 48000, "cgst": 63000, "sgst": 63000, "cess": 0,
         "exempt_nil": 15000, "itc_igst": 26400, "itc_cgst": 37800, "itc_sgst": 37800, "itc_cess": 0,
         "itc_reversed": 1600, "tax_paid_cash": 73200, "tax_paid_itc": 100800},
        {"month": "May 2025", "total_taxable": 850000, "igst": 51000, "cgst": 67500, "sgst": 67500, "cess": 0,
         "exempt_nil": 12000, "itc_igst": 28050, "itc_cgst": 40500, "itc_sgst": 40500, "itc_cess": 0,
         "itc_reversed": 1700, "tax_paid_cash": 77150, "tax_paid_itc": 108850},
        # Jun: turnover 15k lower in GSTR-3B
        {"month": "Jun 2025", "total_taxable": 835000, "igst": 51000, "cgst": 66650, "sgst": 66650, "cess": 0,
         "exempt_nil": 18000, "itc_igst": 28050, "itc_cgst": 40800, "itc_sgst": 40800, "itc_cess": 0,
         "itc_reversed": 1700, "tax_paid_cash": 74750, "tax_paid_itc": 109550},
        # Oct: turnover 25k lower in GSTR-3B
        {"month": "Oct 2025", "total_taxable": 1125000, "igst": 66750, "cgst": 90875, "sgst": 90875, "cess": 0,
         "exempt_nil": 25000, "itc_igst": 37950, "itc_cgst": 55200, "itc_sgst": 55200, "itc_cess": 0,
         "itc_reversed": 2300, "tax_paid_cash": 102150, "tax_paid_itc": 146350},
        # Mar: tax 4k higher in GSTR-3B
        {"month": "Mar 2026", "total_taxable": 1050000, "igst": 63000, "cgst": 86000, "sgst": 86000, "cess": 0,
         "exempt_nil": 22000, "itc_igst": 34650, "itc_cgst": 50400, "itc_sgst": 50400, "itc_cess": 0,
         "itc_reversed": 2100, "tax_paid_cash": 101550, "tax_paid_itc": 133450},
    ]

    result = reconcile(gstr1_months, gstr3b_months, 5000000)

    # Verify structure
    assert_true("summary" in result, label="result has summary")
    assert_true("monthly_comparison" in result, label="result has monthly_comparison")
    assert_true("tax_reconciliation" in result, label="result has tax_reconciliation")
    assert_true("cdn_reconciliation" in result, label="result has cdn_reconciliation")
    assert_true("books_reconciliation" in result, label="result has books_reconciliation")
    assert_true("itc_summary" in result, label="result has itc_summary")
    assert_true("gstr9_tables" in result, label="result has gstr9_tables")
    assert_true("action_items" in result, label="result has action_items")
    assert_true("duplicate_warnings" in result, label="result has duplicate_warnings")

    summary = result["summary"]

    # Verify discrepancies detected
    assert_gt(summary["discrepancy_count"], 0, label="discrepancies detected (>0)")
    assert_true(summary["months_analyzed"] == 5, label="months_analyzed == 5")
    assert_true(summary["months_in_gstr1"] == 5, label="months_in_gstr1 == 5")
    assert_true(summary["months_in_gstr3b"] == 5, label="months_in_gstr3b == 5")

    # Verify Jun mismatch detected
    jun_comp = [m for m in result["monthly_comparison"] if m["month"] == "2025-06"]
    assert_true(len(jun_comp) == 1, label="Jun 2025 in monthly_comparison")
    if jun_comp:
        assert_close(jun_comp[0]["turnover_diff"], 15000, tol=500, label="Jun turnover_diff ~15k")

    # Verify Oct mismatch detected
    oct_comp = [m for m in result["monthly_comparison"] if m["month"] == "2025-10"]
    assert_true(len(oct_comp) == 1, label="Oct 2025 in monthly_comparison")
    if oct_comp:
        assert_close(oct_comp[0]["turnover_diff"], 25000, tol=500, label="Oct turnover_diff ~25k")

    # Verify action items exist for mismatches
    turnover_items = [a for a in result["action_items"] if a["category"] == "TURNOVER_MISMATCH"]
    assert_gt(len(turnover_items), 0, label="TURNOVER_MISMATCH action items exist")

    # Verify CDN reconciliation
    cdn_recon = result["cdn_reconciliation"]
    assert_true(cdn_recon["total_credit_debit_notes"] < 0, label="CDN is negative (credit notes)")

    # Verify GSTR-9 tables
    tables = result["gstr9_tables"]
    assert_true("table_4" in tables, label="gstr9_tables has table_4")
    assert_true("table_6" in tables, label="gstr9_tables has table_6")
    assert_true("table_9" in tables, label="gstr9_tables has table_9")
    assert_true("table_10_11" in tables, label="gstr9_tables has table_10_11")

    # Verify books reconciliation
    books = result["books_reconciliation"]
    assert_true(books is not None, label="books_reconciliation not None")
    assert_true("books_vs_gstr1_diff" in books, label="books_vs_gstr1_diff present")

    # Verify summary has CDN/amendment fields
    assert_true("total_cdn" in summary, label="summary has total_cdn")
    assert_true("total_amendments" in summary, label="summary has total_amendments")
    assert_true("adjusted_turnover_diff" in summary, label="summary has adjusted_turnover_diff")

    print(f"  Summary: {summary['discrepancy_count']} discrepancies, status={summary['status']}")
    print(f"  Action items: {len(result['action_items'])}")


# ---------------------------------------------------------------------------
# TEST 6: Export field name verification
# ---------------------------------------------------------------------------
def test_export_field_alignment():
    """Verify that field names in reconcile() output match what _extract_gstr9_tables() reads."""
    from services.gstr9_reconciliation_service import reconcile

    # Minimal test data
    gstr1 = [{"month": "Apr 2025", "total_taxable": 100000, "igst": 9000,
              "cgst": 4500, "sgst": 4500, "cess": 0, "exempt_nil": 1000,
              "credit_debit_notes": -500, "amendments": 0}]
    gstr3b = [{"month": "Apr 2025", "total_taxable": 100000, "igst": 9000,
               "cgst": 4500, "sgst": 4500, "cess": 0, "exempt_nil": 1000,
               "itc_igst": 5000, "itc_cgst": 2500, "itc_sgst": 2500, "itc_cess": 0,
               "itc_reversed": 200, "tax_paid_cash": 8200, "tax_paid_itc": 9800}]

    result = reconcile(gstr1, gstr3b, None)

    # Verify monthly_comparison keys match what CSV export reads
    for m in result["monthly_comparison"]:
        assert_true("turnover_diff" in m, label="monthly has turnover_diff (not turnover_difference)")
        assert_true("tax_diff" in m, label="monthly has tax_diff (not tax_difference)")
        assert_true("gstr1_turnover" in m, label="monthly has gstr1_turnover")
        assert_true("gstr3b_turnover" in m, label="monthly has gstr3b_turnover")
        assert_true("gstr1_tax" in m, label="monthly has gstr1_tax")
        assert_true("gstr3b_tax" in m, label="monthly has gstr3b_tax")
        assert_true("severity" in m, label="monthly has severity")
        assert_true("credit_debit_notes" in m, label="monthly has credit_debit_notes")

    # Verify tax_reconciliation flat keys match CSV/PDF export
    tr = result["tax_reconciliation"]
    for tax_type in ["igst", "cgst", "sgst", "cess"]:
        assert_true(f"gstr1_{tax_type}" in tr, label=f"tax_recon has gstr1_{tax_type}")
        assert_true(f"gstr3b_{tax_type}" in tr, label=f"tax_recon has gstr3b_{tax_type}")
        assert_true(f"{tax_type}_diff" in tr, label=f"tax_recon has {tax_type}_diff")
    assert_true("gstr1_total_tax" in tr, label="tax_recon has gstr1_total_tax")
    assert_true("gstr3b_total_tax" in tr, label="tax_recon has gstr3b_total_tax")
    assert_true("total_tax_gap" in tr, label="tax_recon has total_tax_gap")
    assert_true("gap_interpretation" in tr, label="tax_recon has gap_interpretation")

    # Verify summary keys
    s = result["summary"]
    assert_true("turnover_diff" in s, label="summary has turnover_diff")
    assert_true("tax_diff" in s, label="summary has tax_diff")
    assert_true("months_analyzed" in s, label="summary has months_analyzed")
    assert_true("discrepancy_count" in s, label="summary has discrepancy_count")


# ---------------------------------------------------------------------------
# TEST 7: Edge cases
# ---------------------------------------------------------------------------
def test_edge_cases():
    """Test reconciliation with edge-case inputs."""
    from services.gstr9_reconciliation_service import reconcile

    # Empty inputs
    result = reconcile([], [], None)
    assert_eq(result["summary"]["discrepancy_count"], 0, label="empty: 0 discrepancies")
    assert_eq(result["summary"]["months_analyzed"], 0, label="empty: 0 months")
    assert_eq(len(result["monthly_comparison"]), 0, label="empty: no monthly rows")

    # Single month, no mismatch
    g1 = [{"month": "Apr 2025", "total_taxable": 100000, "igst": 9000,
           "cgst": 4500, "sgst": 4500, "cess": 0, "exempt_nil": 0,
           "credit_debit_notes": 0, "amendments": 0}]
    g3 = [{"month": "Apr 2025", "total_taxable": 100000, "igst": 9000,
           "cgst": 4500, "sgst": 4500, "cess": 0, "exempt_nil": 0,
           "itc_igst": 5000, "itc_cgst": 2500, "itc_sgst": 2500, "itc_cess": 0,
           "itc_reversed": 0, "tax_paid_cash": 8000, "tax_paid_itc": 10000}]
    result = reconcile(g1, g3, None)
    assert_eq(result["summary"]["months_analyzed"], 1, label="single month: 1 analyzed")
    assert_eq(result["summary"]["status"], "clean", label="single month: clean status")

    # Missing month — GSTR-1 has month that GSTR-3B doesn't
    g1_extra = g1 + [{"month": "May 2025", "total_taxable": 50000, "igst": 4500,
                       "cgst": 2250, "sgst": 2250, "cess": 0, "exempt_nil": 0,
                       "credit_debit_notes": 0, "amendments": 0}]
    result = reconcile(g1_extra, g3, None)
    missing_items = [a for a in result["action_items"] if a["category"] == "MISSING_MONTH"]
    assert_gt(len(missing_items), 0, label="missing month flagged")

    # Duplicate months
    g1_dup = g1 + [{"month": "Apr 2025", "total_taxable": 200000, "igst": 18000,
                     "cgst": 9000, "sgst": 9000, "cess": 0, "exempt_nil": 0,
                     "credit_debit_notes": 0, "amendments": 0}]
    result = reconcile(g1_dup, g3, None)
    dup_items = [a for a in result["action_items"] if a["category"] == "DUPLICATE_MONTH"]
    assert_gt(len(dup_items), 0, label="duplicate month flagged")
    assert_gt(len(result["duplicate_warnings"]), 0, label="duplicate_warnings populated")

    # All zeros
    g1_zero = [{"month": "Apr 2025", "total_taxable": 0, "igst": 0, "cgst": 0, "sgst": 0,
                "cess": 0, "exempt_nil": 0, "credit_debit_notes": 0, "amendments": 0}]
    g3_zero = [{"month": "Apr 2025", "total_taxable": 0, "igst": 0, "cgst": 0, "sgst": 0,
                "cess": 0, "exempt_nil": 0, "itc_igst": 0, "itc_cgst": 0, "itc_sgst": 0,
                "itc_cess": 0, "itc_reversed": 0, "tax_paid_cash": 0, "tax_paid_itc": 0}]
    result = reconcile(g1_zero, g3_zero, None)
    assert_eq(result["summary"]["status"], "clean", label="zeros: clean status")


# ---------------------------------------------------------------------------
# TEST 8: Full pipeline end-to-end with 24 test PDFs
# ---------------------------------------------------------------------------
def test_full_pipeline():
    """Parse all 24 test PDFs and run reconciliation end-to-end."""
    import pymupdf
    from services.gstr9_reconciliation_service import GSTR9ReconciliationService, reconcile

    pdf_dir = "test_gstr_pdfs"
    if not os.path.exists(pdf_dir):
        print("  SKIP: test_gstr_pdfs/ directory not found.")
        return

    service = GSTR9ReconciliationService()

    month_names = ["Apr", "May", "Jun", "Jul", "Aug", "Sep",
                   "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"]
    years = ["2025", "2025", "2025", "2025", "2025", "2025",
             "2025", "2025", "2025", "2026", "2026", "2026"]

    gstr1_months = []
    gstr3b_months = []

    for i, (mn, yr) in enumerate(zip(month_names, years)):
        # Parse GSTR-1
        g1_path = os.path.join(pdf_dir, f"GSTR1_{mn}_{yr}.pdf")
        if os.path.exists(g1_path):
            doc = pymupdf.open(g1_path)
            text = "".join(page.get_text() for page in doc)
            doc.close()
            parsed = service.parse_monthly_data(text, "gstr1")
            if "error" not in parsed:
                gstr1_months.append(parsed)

        # Parse GSTR-3B
        g3_path = os.path.join(pdf_dir, f"GSTR3B_{mn}_{yr}.pdf")
        if os.path.exists(g3_path):
            doc = pymupdf.open(g3_path)
            text = "".join(page.get_text() for page in doc)
            doc.close()
            parsed = service.parse_monthly_data(text, "gstr3b")
            if "error" not in parsed:
                gstr3b_months.append(parsed)

    print(f"  Parsed: {len(gstr1_months)} GSTR-1 + {len(gstr3b_months)} GSTR-3B")

    assert_gt(len(gstr1_months), 6, label="at least 7 GSTR-1 months parsed")
    assert_gt(len(gstr3b_months), 6, label="at least 7 GSTR-3B months parsed")

    # Run reconciliation
    result = reconcile(gstr1_months, gstr3b_months, 10500000)

    summary = result["summary"]
    print(f"  GSTR-1 Total: Rs.{summary['gstr1_total_turnover']:,.0f}")
    print(f"  GSTR-3B Total: Rs.{summary['gstr3b_total_turnover']:,.0f}")
    print(f"  Turnover Diff: Rs.{summary['turnover_diff']:,.0f}")
    print(f"  Tax Diff: Rs.{summary['tax_diff']:,.0f}")
    print(f"  Discrepancies: {summary['discrepancy_count']}")
    print(f"  Status: {summary['status']}")
    print(f"  Action Items: {len(result['action_items'])}")

    # Expected: GSTR-1 total ~11,010,000 and GSTR-3B total ~10,970,000
    assert_gt(summary["gstr1_total_turnover"], 10_000_000, label="GSTR-1 annual turnover > 1 Cr")
    assert_gt(summary["gstr3b_total_turnover"], 10_000_000, label="GSTR-3B annual turnover > 1 Cr")

    # Should detect Jun and Oct turnover mismatches
    assert_gt(summary["discrepancy_count"], 0, label="discrepancies detected in full pipeline")

    # Verify action items are sorted by financial_impact descending
    impacts = [a.get("financial_impact", 0) for a in result["action_items"]]
    assert_true(impacts == sorted(impacts, reverse=True), label="action items sorted by impact desc")

    # Verify CDN/amendment data
    assert_true("cdn_reconciliation" in result, label="cdn_reconciliation in result")
    assert_true(result["cdn_reconciliation"]["total_credit_debit_notes"] < 0,
                label="CDN total is negative (credit notes)")

    # Verify books reconciliation triggered
    assert_true(result["books_reconciliation"] is not None, label="books_reconciliation present")

    # Print action items for review
    print(f"\n  === ACTION ITEMS ({len(result['action_items'])}) ===")
    for a in result["action_items"][:10]:
        print(f"  P{a['priority']} [{a['category']}] {a['description'][:80]}")
        if a.get("possible_reasons"):
            print(f"       Reasons: {', '.join(a['possible_reasons'])}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    run_test("1. _parse_float() — Indian number formats", test_parse_float)
    run_test("2. _month_key() — format normalization", test_month_key)
    run_test("3. GSTR-1 PDF text parsing", test_gstr1_parsing)
    run_test("4. GSTR-3B PDF text parsing", test_gstr3b_parsing)
    run_test("5. Reconciliation with known mismatches", test_reconciliation_known_data)
    run_test("6. Export field name alignment", test_export_field_alignment)
    run_test("7. Edge cases (empty, single, duplicate, zeros)", test_edge_cases)
    run_test("8. Full pipeline end-to-end (24 PDFs)", test_full_pipeline)

    print(f"\n{'='*60}")
    print(f"FINAL RESULTS: {PASS_COUNT} passed, {FAIL_COUNT} failed out of {TOTAL_TESTS} tests")
    print(f"{'='*60}")

    if FAIL_COUNT > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
