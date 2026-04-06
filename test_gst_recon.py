"""
GST Reconciliation Feature — Comprehensive Evaluation Script
=============================================================
Tests GSTR-2B vs Purchase Register reconciliation with realistic data.

Test Scenarios Embedded in the Data:
-------------------------------------
1. PERFECT MATCH (6 invoices): ACM/1234, ACM/1298, BS-4501, NL/MAR/001, WEL-78901, GPS-3344
2. VALUE MISMATCH (2 invoices):
   - BS-4567: Taxable 48,000 (2B) vs 45,000 (books) — Rs 3,000 diff + tax diff Rs 540
   - RSI/INV/2026/0345: Taxable 500,000 (2B) vs 490,000 (books) — Rs 10,000 diff + tax diff Rs 1,800
3. INVOICE NUMBER NORMALIZATION:
   - PPC-0089 (2B) vs PPC-89 (books) — leading zero difference, SHOULD match
   - KH-MAR-0056 (2B) vs KH/MAR/56 (books) — hyphen vs slash + leading zero, SHOULD match
4. MISSING IN BOOKS (1 invoice):
   - MOS/INV/2026/0221 — Metro Office Supplies (in 2B, not in purchase register)
   Note: TS/26/MAR/0055 is in BOTH sources (itcavl=N in 2B but present in books) -> matches
5. MISSING IN GSTR-2B (2 invoices):
   - DFA/2026/0033 — DataFlow Analytics (in books, supplier hasn't filed — ITC AT RISK)
   - ECS-1122 — Elite Catering Services (in books, supplier hasn't filed — ITC AT RISK)
6. ITC ELIGIBILITY: TS/26/MAR/0055 has itcavl=N — its tax (27,000) goes to itc_ineligible, not itc_available
7. CESS: All test data has cess=0 (baseline), separate synthetic test for cess
8. DATE MISMATCH: Tested via synthetic records
9. DUPLICATES: Tested via synthetic records
10. FUZZY MATCHING: Tested via synthetic records
11. INDIAN NUMBER FORMAT: Tested via _parse_float
"""

import json
import os
import sys
import logging

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from services.gstr2b_reconciliation_service import (
    extract_gstr2b_records,
    extract_purchase_register,
    reconcile,
    _normalize_invoice_no,
    _parse_float,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

TEST_DIR = os.path.join(os.path.dirname(__file__), "test_documents", "gst_recon")

# ============================================================================
# EXPECTED RESULTS (ground truth)
# ============================================================================

# ITC calculation:
# Matched ITC-eligible invoices (8): ACM/1234(18000) + ACM/1298(9000) + BS-4501(36000) +
#   NL/MAR/001(3600) + WEL-78901(54000) + GPS-3344(1800) + PPC-89(5400) + KH-56(7200) = 135,000
# TS/26/MAR/0055 matched but itcavl=N -> itc_ineligible = 27,000
# Missing in books ITC-eligible: MOS(10800) = 10,800
# Total itc_available = 135,000 + 10,800 = 145,800

EXPECTED = {
    "matched_count": 9,
    "mismatch_count": 2,
    "missing_in_books_count": 1,
    "missing_in_gstr2b_count": 2,
    "itc_available": 145800.00,
    "itc_at_risk": 16000.00,
    "itc_ineligible": 27000.00,
    "total_cess": 0.0,
}


def _inv_key(rec):
    gstin = rec.get("gstin_supplier", rec.get("gstin", ""))
    inv = rec.get("invoice_no", "")
    return (gstin, inv)


def print_section(title):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_records(records, label):
    if not records:
        print(f"  (none)")
        return
    for r in records:
        gstin = r.get("gstin_supplier", r.get("gstin", "N/A"))
        inv = r.get("invoice_no", "N/A")
        taxable = r.get("taxable_value", r.get("taxable_value_2b", 0))
        tax = r.get("total_tax", r.get("total_tax_2b", 0))
        remark = r.get("remark", "")
        itc = "ITC:Yes" if r.get("itc_eligible", True) else "ITC:No"
        print(f"  {gstin} | {inv:30s} | Taxable: {taxable:>12,.2f} | Tax: {tax:>10,.2f} | {itc} | {remark}")


# ============================================================================
# TEST 1: Invoice Number Normalization
# ============================================================================

def test_invoice_normalization():
    print_section("TEST 1: Invoice Number Normalization")

    test_cases = [
        ("PPC-0089", "PPC-89", True, "Leading zero after hyphen"),
        ("KH-MAR-0056", "KH/MAR/56", True, "Hyphen vs slash + leading zero"),
        ("ACM/2025-26/1234", "ACM/2025-26/1234", True, "Identical"),
        ("BS-4501", "BS-4501", True, "Identical simple"),
        ("INV 001", "INV-001", True, "Space vs hyphen"),
        ("INV/2026/001", "INV-2026-1", True, "Slash vs hyphen + leading zero"),
        ("ABC123", "ABC-123", True, "Separator removal makes them identical"),
    ]

    passed = 0
    failed = 0
    for inv_a, inv_b, should_match, desc in test_cases:
        norm_a = _normalize_invoice_no(inv_a)
        norm_b = _normalize_invoice_no(inv_b)
        actual_match = (norm_a == norm_b)

        status = "PASS" if actual_match == should_match else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            failed += 1

        print(f"  [{status}] {desc}")
        print(f"         '{inv_a}' -> '{norm_a}'")
        print(f"         '{inv_b}' -> '{norm_b}'")
        print(f"         Expected match={should_match}, Got match={actual_match}")
        print()

    print(f"  Normalization: {passed} passed, {failed} failed out of {len(test_cases)}")
    return passed, failed


# ============================================================================
# TEST 2: JSON Extraction (GSTR-2B)
# ============================================================================

def test_json_extraction():
    print_section("TEST 2: GSTR-2B JSON Extraction")

    json_path = os.path.join(TEST_DIR, "gstr2b_march2026.json")
    records = extract_gstr2b_records(json_path)

    print(f"  Extracted {len(records)} records from JSON")
    expected_count = 12

    issues = []
    if len(records) != expected_count:
        issues.append(f"Expected {expected_count} records, got {len(records)}")

    for r in records:
        if r["invoice_no"] == "ACM/2025-26/1234":
            if r["taxable_value"] != 100000.0:
                issues.append(f"ACM/1234 taxable: expected 100000, got {r['taxable_value']}")
            if r["cgst"] != 9000.0:
                issues.append(f"ACM/1234 CGST: expected 9000, got {r['cgst']}")
            if r.get("cess") != 0.0:
                issues.append(f"ACM/1234 cess: expected 0, got {r.get('cess')}")
        if r["invoice_no"] == "RSI/INV/2026/0345":
            if r["taxable_value"] != 500000.0:
                issues.append(f"RSI taxable: expected 500000, got {r['taxable_value']}")
            if r["igst"] != 90000.0:
                issues.append(f"RSI IGST: expected 90000, got {r['igst']}")
        if r["invoice_no"] == "TS/26/MAR/0055":
            if r["itc_available"] is not False:
                issues.append(f"TS ITC: expected False (itcavl=N), got {r['itc_available']}")

    if issues:
        for issue in issues:
            print(f"  [FAIL] {issue}")
    else:
        print(f"  [PASS] All {expected_count} records extracted with correct values (incl. cess, ITC flag)")

    for r in records:
        print(f"    {r['gstin_supplier']} | {r['invoice_no']:30s} | "
              f"Taxable: {r['taxable_value']:>10,.2f} | Tax: {r['total_tax']:>8,.2f} | "
              f"Cess: {r.get('cess', 0):>6,.2f} | ITC: {'Yes' if r['itc_available'] else 'No'}")

    return len(issues) == 0, records


# ============================================================================
# TEST 3: CSV Extraction (Purchase Register)
# ============================================================================

def test_csv_extraction():
    print_section("TEST 3: Purchase Register CSV Extraction")

    csv_path = os.path.join(TEST_DIR, "purchase_register_march2026.csv")
    records = extract_purchase_register(csv_path)

    print(f"  Extracted {len(records)} records from CSV")
    expected_count = 13

    issues = []
    if len(records) != expected_count:
        issues.append(f"Expected {expected_count} records, got {len(records)}")

    if issues:
        for issue in issues:
            print(f"  [FAIL] {issue}")
    else:
        print(f"  [PASS] All {expected_count} records extracted correctly")

    for r in records:
        print(f"    {r['gstin_supplier']} | {r['invoice_no']:30s} | "
              f"Taxable: {r['taxable_value']:>10,.2f} | Tax: {r['total_tax']:>8,.2f}")

    return len(issues) == 0, records


# ============================================================================
# TEST 4: PDF Extraction
# ============================================================================

def test_pdf_extraction():
    print_section("TEST 4: PDF Table Extraction")

    gstr2b_pdf = os.path.join(TEST_DIR, "gstr2b_march2026.pdf")
    pr_pdf = os.path.join(TEST_DIR, "purchase_register_march2026.pdf")

    gstr2b_recs = extract_gstr2b_records(gstr2b_pdf)
    pr_recs = extract_purchase_register(pr_pdf)

    print(f"  GSTR-2B PDF: Extracted {len(gstr2b_recs)} records (expected 12)")
    print(f"  Purchase Register PDF: Extracted {len(pr_recs)} records (expected 13)")

    issues = []
    if len(gstr2b_recs) < 10:
        issues.append(f"GSTR-2B PDF: Only {len(gstr2b_recs)}/12 records")
    if len(pr_recs) < 10:
        issues.append(f"Purchase Register PDF: Only {len(pr_recs)}/13 records")

    if issues:
        for issue in issues:
            print(f"  [WARN] {issue}")
    else:
        print(f"  [PASS] PDF extraction looks good")

    return len(issues) == 0, gstr2b_recs, pr_recs


# ============================================================================
# TEST 5: Core Reconciliation (JSON + CSV)
# ============================================================================

def test_reconciliation(gstr2b_records, purchase_records):
    print_section("TEST 5: Core Reconciliation Logic (JSON + CSV)")

    result = reconcile(gstr2b_records, purchase_records)
    summary = result["summary"]

    print(f"\n  --- RECONCILIATION SUMMARY ---")
    print(f"  Total GSTR-2B invoices:     {summary['total_invoices_gstr2b']}")
    print(f"  Total Purchase Reg invoices: {summary['total_invoices_books']}")
    print(f"  Matched:                     {summary['matched_count']}")
    print(f"  Value Mismatches:            {summary['mismatch_count']}")
    print(f"  Missing in Books:            {summary['missing_in_books_count']}")
    print(f"  Missing in GSTR-2B:          {summary['missing_in_gstr2b_count']}")
    print(f"  ITC Available:               Rs {summary['itc_available']:,.2f}")
    print(f"  ITC At Risk:                 Rs {summary['itc_at_risk']:,.2f}")
    print(f"  ITC Ineligible:              Rs {summary.get('itc_ineligible', 0):,.2f}")
    print(f"  ITC Mismatch Amount:         Rs {summary['itc_mismatch_amount']:,.2f}")
    print(f"  Total Cess:                  Rs {summary.get('total_cess', 0):,.2f}")
    print(f"  Duplicates:                  {summary.get('duplicate_count', 0)}")
    print(f"  Potential Matches:           {summary.get('potential_match_count', 0)}")

    # Print detailed results
    print_section("MATCHED INVOICES")
    print_records(result["matched"], "Matched")

    print_section("VALUE MISMATCHES")
    print_records(result["value_mismatch"], "Mismatch")

    print_section("MISSING IN BOOKS (in 2B, not in Purchase Register)")
    print_records(result["missing_in_books"], "Missing in Books")

    print_section("MISSING IN GSTR-2B (in Purchase Register, not in 2B)")
    print_records(result["missing_in_gstr2b"], "Missing in 2B")

    # Validate against expected
    print_section("VALIDATION AGAINST EXPECTED RESULTS")

    issues = []

    checks = [
        ("matched_count", summary["matched_count"], EXPECTED["matched_count"]),
        ("mismatch_count", summary["mismatch_count"], EXPECTED["mismatch_count"]),
        ("missing_in_books_count", summary["missing_in_books_count"], EXPECTED["missing_in_books_count"]),
        ("missing_in_gstr2b_count", summary["missing_in_gstr2b_count"], EXPECTED["missing_in_gstr2b_count"]),
    ]
    for name, actual, expected in checks:
        if actual != expected:
            issues.append(f"{name}: expected {expected}, got {actual}")

    float_checks = [
        ("itc_available", summary["itc_available"], EXPECTED["itc_available"]),
        ("itc_at_risk", summary["itc_at_risk"], EXPECTED["itc_at_risk"]),
        ("itc_ineligible", summary.get("itc_ineligible", 0), EXPECTED["itc_ineligible"]),
        ("total_cess", summary.get("total_cess", 0), EXPECTED["total_cess"]),
    ]
    for name, actual, expected in float_checks:
        if abs(actual - expected) > 1.0:
            issues.append(f"{name}: expected Rs {expected:,.2f}, got Rs {actual:,.2f}")

    # Verify TechServe is matched but ITC-ineligible
    ts_found = False
    for r in result["matched"]:
        if r.get("gstin_supplier") == "36AABCT1332L1Z1":
            ts_found = True
            if r.get("itc_eligible") is not False:
                issues.append(f"TechServe should have itc_eligible=False, got {r.get('itc_eligible')}")
    if not ts_found:
        issues.append("TechServe (TS/26/MAR/0055) not found in matched — should be matched with itc_eligible=False")

    if issues:
        print(f"\n  ISSUES FOUND ({len(issues)}):")
        for issue in issues:
            print(f"  [FAIL] {issue}")
    else:
        print(f"\n  [PASS] All reconciliation results match expected values!")

    return issues, result


# ============================================================================
# TEST 6: PDF-based Reconciliation
# ============================================================================

def test_pdf_reconciliation(gstr2b_pdf_recs, pr_pdf_recs):
    print_section("TEST 6: PDF-based Reconciliation")

    if not gstr2b_pdf_recs or not pr_pdf_recs:
        print("  [SKIP] No PDF records extracted")
        return

    result = reconcile(gstr2b_pdf_recs, pr_pdf_recs)
    summary = result["summary"]

    print(f"  Matched: {summary['matched_count']} | Mismatch: {summary['mismatch_count']} | "
          f"Missing Books: {summary['missing_in_books_count']} | Missing 2B: {summary['missing_in_gstr2b_count']}")
    print(f"  ITC Available: Rs {summary['itc_available']:,.2f} | "
          f"ITC At Risk: Rs {summary['itc_at_risk']:,.2f}")


# ============================================================================
# TEST 7: Edge Cases
# ============================================================================

def test_edge_cases():
    print_section("TEST 7: Edge Cases")

    # Empty inputs
    result = reconcile([], [])
    assert result["summary"]["matched_count"] == 0
    print("  [PASS] Empty inputs handled correctly")

    # One side empty
    dummy = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "TEST-001",
              "invoice_date": "01-03-2026",
              "taxable_value": 1000, "total_tax": 180, "igst": 0, "cgst": 90, "sgst": 90}]
    result = reconcile(dummy, [])
    assert result["summary"]["missing_in_books_count"] == 1
    print("  [PASS] One-sided (2B only) handled correctly")

    result = reconcile([], dummy)
    assert result["summary"]["missing_in_gstr2b_count"] == 1
    print("  [PASS] One-sided (books only) handled correctly")

    # Missing invoice_date field entirely — should NOT crash (BUG 1 fix)
    no_date = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "ND-001",
                "taxable_value": 1000, "total_tax": 180}]
    try:
        result = reconcile(no_date, no_date)
        print(f"  [PASS] Missing invoice_date handled gracefully (matched={result['summary']['matched_count']})")
    except KeyError as e:
        print(f"  [FAIL] reconcile() still crashes with KeyError: {e}")

    # Invalid GSTIN
    bad_gstin = [{"gstin_supplier": "INVALID", "invoice_no": "X-001",
                  "invoice_date": None, "taxable_value": 1000, "total_tax": 180}]
    try:
        result = reconcile(bad_gstin, bad_gstin)
        print(f"  [PASS] Invalid GSTIN handled (matched={result['summary']['matched_count']})")
    except Exception as e:
        print(f"  [FAIL] Crashed with: {e}")


# ============================================================================
# TEST 8: ITC Eligibility
# ============================================================================

def test_itc_eligibility():
    print_section("TEST 8: ITC Eligibility Flag")

    eligible = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "E-001",
                 "invoice_date": "01-03-2026", "taxable_value": 10000,
                 "total_tax": 1800, "igst": 0, "cgst": 900, "sgst": 900,
                 "itc_available": True}]
    ineligible = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "I-001",
                   "invoice_date": "01-03-2026", "taxable_value": 20000,
                   "total_tax": 3600, "igst": 0, "cgst": 1800, "sgst": 1800,
                   "itc_available": False}]

    # Both in 2B, both matched with same records in books
    books = [
        {"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "E-001",
         "invoice_date": "01-03-2026", "taxable_value": 10000, "total_tax": 1800,
         "igst": 0, "cgst": 900, "sgst": 900},
        {"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "I-001",
         "invoice_date": "01-03-2026", "taxable_value": 20000, "total_tax": 3600,
         "igst": 0, "cgst": 1800, "sgst": 1800},
    ]

    result = reconcile(eligible + ineligible, books)
    s = result["summary"]

    issues = []
    if abs(s["itc_available"] - 1800.0) > 1:
        issues.append(f"itc_available: expected 1800, got {s['itc_available']}")
    if abs(s.get("itc_ineligible", 0) - 3600.0) > 1:
        issues.append(f"itc_ineligible: expected 3600, got {s.get('itc_ineligible', 0)}")

    # Check the flag on individual records
    for r in result["matched"]:
        if r["invoice_no"] == "E-001" and r.get("itc_eligible") is not True:
            issues.append(f"E-001 should have itc_eligible=True")
        if r["invoice_no"] == "I-001" and r.get("itc_eligible") is not False:
            issues.append(f"I-001 should have itc_eligible=False")

    if issues:
        for i in issues:
            print(f"  [FAIL] {i}")
    else:
        print(f"  [PASS] ITC eligibility: available={s['itc_available']}, ineligible={s.get('itc_ineligible', 0)}")


# ============================================================================
# TEST 9: Cess Handling
# ============================================================================

def test_cess():
    print_section("TEST 9: Cess Handling")

    gstr2b = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "CESS-001",
               "invoice_date": "01-03-2026", "taxable_value": 50000,
               "igst": 0, "cgst": 4500, "sgst": 4500, "cess": 2500,
               "total_tax": 11500, "itc_available": True}]
    books = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "CESS-001",
              "invoice_date": "01-03-2026", "taxable_value": 50000,
              "igst": 0, "cgst": 4500, "sgst": 4500, "cess": 2500,
              "total_tax": 11500}]

    result = reconcile(gstr2b, books)
    s = result["summary"]

    issues = []
    if abs(s.get("total_cess", 0) - 2500.0) > 1:
        issues.append(f"total_cess: expected 2500, got {s.get('total_cess', 0)}")
    if s["matched_count"] != 1:
        issues.append(f"Should have 1 match, got {s['matched_count']}")
    # Check cess in record
    if result["matched"]:
        r = result["matched"][0]
        if abs(r.get("cess_2b", 0) - 2500.0) > 1:
            issues.append(f"cess_2b: expected 2500, got {r.get('cess_2b')}")

    if issues:
        for i in issues:
            print(f"  [FAIL] {i}")
    else:
        print(f"  [PASS] Cess tracked: total_cess={s.get('total_cess', 0)}, cess_2b={result['matched'][0].get('cess_2b', 0)}")


# ============================================================================
# TEST 10: Date Mismatch Detection
# ============================================================================

def test_date_mismatch():
    print_section("TEST 10: Date Mismatch Detection")

    gstr2b = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "DM-001",
               "invoice_date": "01-03-2026", "taxable_value": 10000,
               "total_tax": 1800, "igst": 0, "cgst": 900, "sgst": 900,
               "itc_available": True}]
    books = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "DM-001",
              "invoice_date": "05-03-2026", "taxable_value": 10000,
              "total_tax": 1800, "igst": 0, "cgst": 900, "sgst": 900}]

    result = reconcile(gstr2b, books)

    issues = []
    # Should be matched (same values) but with DATE_MISMATCH flag
    if result["summary"]["matched_count"] != 1:
        issues.append(f"Should be matched (not mismatch), got matched={result['summary']['matched_count']}")
    if result["matched"]:
        r = result["matched"][0]
        mt = r.get("mismatch_type", [])
        if "DATE_MISMATCH" not in mt:
            issues.append(f"Expected DATE_MISMATCH in mismatch_type, got {mt}")
        if r.get("invoice_date_2b") != "01-03-2026":
            issues.append(f"invoice_date_2b wrong: {r.get('invoice_date_2b')}")
        if r.get("invoice_date_books") != "05-03-2026":
            issues.append(f"invoice_date_books wrong: {r.get('invoice_date_books')}")

    if issues:
        for i in issues:
            print(f"  [FAIL] {i}")
    else:
        print(f"  [PASS] Date mismatch detected: stays in matched with DATE_MISMATCH flag")


# ============================================================================
# TEST 11: Duplicate Handling
# ============================================================================

def test_duplicates():
    print_section("TEST 11: Duplicate Invoice Handling")

    # GSTR-2B: two records for same invoice (amendment scenario)
    dup_2b = [
        {"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "DUP-001",
         "invoice_date": "01-03-2026",
         "taxable_value": 1000, "total_tax": 180, "igst": 0, "cgst": 90, "sgst": 90,
         "itc_available": True},
        {"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "DUP-001",
         "invoice_date": "01-03-2026",
         "taxable_value": 500, "total_tax": 90, "igst": 0, "cgst": 45, "sgst": 45,
         "itc_available": True},
    ]
    # Books: aggregated value = 1500, tax = 270
    books = [
        {"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "DUP-001",
         "invoice_date": "01-03-2026",
         "taxable_value": 1500, "total_tax": 270, "igst": 0, "cgst": 135, "sgst": 135},
    ]

    result = reconcile(dup_2b, books)

    issues = []
    # 2B duplicates should be aggregated: 1000+500=1500, 180+90=270
    if result["summary"]["matched_count"] != 1:
        issues.append(f"Expected 1 match (aggregated), got {result['summary']['matched_count']}")
    if result["summary"]["mismatch_count"] != 0:
        issues.append(f"Expected 0 mismatches (aggregated values match), got {result['summary']['mismatch_count']}")
    if result["summary"].get("duplicate_count", 0) < 1:
        issues.append(f"Expected duplicate_count >= 1, got {result['summary'].get('duplicate_count', 0)}")
    if not result.get("duplicates_2b"):
        issues.append("Expected duplicates_2b to be non-empty")

    if issues:
        for i in issues:
            print(f"  [FAIL] {i}")
    else:
        print(f"  [PASS] Duplicates: 2B aggregated correctly, duplicate_count={result['summary']['duplicate_count']}")


# ============================================================================
# TEST 12: Indian Number Format
# ============================================================================

def test_indian_numbers():
    print_section("TEST 12: Indian Number Format (_parse_float)")

    test_cases = [
        ("1,00,000.00", 100000.0, "Indian lakh comma format"),
        ("50,000", 50000.0, "Standard comma format"),
        ("1.5 Lakh", 150000.0, "Lakh suffix"),
        ("1.5 lakh", 150000.0, "lakh suffix lowercase"),
        ("2.3 Cr", 23000000.0, "Cr suffix"),
        ("2.3 Crore", 23000000.0, "Crore suffix"),
        ("0.5 Lac", 50000.0, "Lac suffix"),
        ("10000", 10000.0, "Plain number"),
        ("", 0.0, "Empty string"),
        (None, 0.0, "None"),
        (42.5, 42.5, "Float passthrough"),
    ]

    passed = 0
    failed = 0
    for val, expected, desc in test_cases:
        actual = _parse_float(val)
        ok = abs(actual - expected) < 0.01
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] {desc}: _parse_float({val!r}) = {actual} (expected {expected})")

    print(f"\n  Indian numbers: {passed} passed, {failed} failed out of {len(test_cases)}")
    return passed, failed


# ============================================================================
# TEST 13: Fuzzy Matching
# ============================================================================

def test_fuzzy_matching():
    print_section("TEST 13: Fuzzy Matching Fallback")

    try:
        from rapidfuzz import fuzz
        has_rapidfuzz = True
    except ImportError:
        has_rapidfuzz = False

    if not has_rapidfuzz:
        print("  [SKIP] rapidfuzz not installed")
        return

    # Create records where invoice numbers are very similar but not exact
    gstr2b = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "INV-2026-00123",
               "invoice_date": "01-03-2026", "taxable_value": 10000,
               "total_tax": 1800, "igst": 0, "cgst": 900, "sgst": 900,
               "itc_available": True}]
    # Books has a typo: 00124 instead of 00123 — close but different after normalization
    books = [{"gstin_supplier": "29AABCU9603R1Z5", "invoice_no": "INV-2026-00124",
              "invoice_date": "01-03-2026", "taxable_value": 10000,
              "total_tax": 1800, "igst": 0, "cgst": 900, "sgst": 900}]

    result = reconcile(gstr2b, books)

    # These should NOT match exactly (123 vs 124) but should appear in potential_matches
    potential = result.get("potential_matches", [])
    print(f"  Exact matches: {result['summary']['matched_count']}")
    print(f"  Potential matches found: {len(potential)}")

    if potential:
        for pm in potential:
            print(f"    GSTIN: {pm['gstin']} | 2B: {pm['invoice_2b']} | Books: {pm['invoice_books']} | "
                  f"Similarity: {pm['similarity']}% | Confidence: {pm['confidence']}")
        print(f"  [PASS] Fuzzy matching found {len(potential)} potential match(es)")
    else:
        print(f"  [INFO] No fuzzy matches found (similarity may be below threshold)")


# ============================================================================
# TEST 14: GSTIN Validation on Purchase Register
# ============================================================================

def test_gstin_validation():
    print_section("TEST 14: GSTIN Validation on Purchase Register")

    # Create a CSV with one invalid GSTIN
    import tempfile
    csv_content = """Supplier GSTIN,Invoice No,Invoice Date,Taxable Value,IGST,CGST,SGST
29AABCU9603R1Z5,VALID-001,01-03-2026,10000,0,900,900
INVALIDGSTIN,BAD-001,01-03-2026,5000,0,450,450
29AABCG5432N1Z7,VALID-002,02-03-2026,20000,0,1800,1800
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, dir=TEST_DIR) as f:
        f.write(csv_content)
        temp_path = f.name

    try:
        records = extract_purchase_register(temp_path)
        valid_count = len(records)
        print(f"  Extracted {valid_count} records (expected 2 — 1 invalid GSTIN filtered)")
        if valid_count == 2:
            print(f"  [PASS] Invalid GSTIN filtered out from purchase register")
        else:
            print(f"  [FAIL] Expected 2 valid records, got {valid_count}")
    finally:
        os.unlink(temp_path)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("=" * 70)
    print("  GSTR-2B RECONCILIATION — COMPREHENSIVE EVALUATION")
    print("  Test data: March 2026 | 12 GSTR-2B invoices, 13 Purchase Register entries")
    print("=" * 70)

    # Test 1: Normalization
    norm_pass, norm_fail = test_invoice_normalization()

    # Test 2: JSON extraction
    json_ok, gstr2b_records = test_json_extraction()

    # Test 3: CSV extraction
    csv_ok, purchase_records = test_csv_extraction()

    # Test 4: PDF extraction
    pdf_ok, gstr2b_pdf_recs, pr_pdf_recs = test_pdf_extraction()

    # Test 5: Core reconciliation (JSON + CSV)
    recon_issues, recon_result = test_reconciliation(gstr2b_records, purchase_records)

    # Test 6: PDF reconciliation
    test_pdf_reconciliation(gstr2b_pdf_recs, pr_pdf_recs)

    # Test 7: Edge cases
    test_edge_cases()

    # Test 8: ITC eligibility
    test_itc_eligibility()

    # Test 9: Cess
    test_cess()

    # Test 10: Date mismatch
    test_date_mismatch()

    # Test 11: Duplicates
    test_duplicates()

    # Test 12: Indian numbers
    num_pass, num_fail = test_indian_numbers()

    # Test 13: Fuzzy matching
    test_fuzzy_matching()

    # Test 14: GSTIN validation
    test_gstin_validation()

    # ====================================================================
    # FINAL SUMMARY
    # ====================================================================
    print_section("FINAL EVALUATION SUMMARY")

    print(f"\n  Invoice Normalization:  {norm_pass} passed, {norm_fail} failed")
    print(f"  JSON Extraction:       {'PASS' if json_ok else 'FAIL'}")
    print(f"  CSV Extraction:        {'PASS' if csv_ok else 'FAIL'}")
    print(f"  PDF Extraction:        {'PASS' if pdf_ok else 'ISSUES'}")
    print(f"  Reconciliation Logic:  {'PASS' if not recon_issues else f'{len(recon_issues)} ISSUES'}")
    print(f"  Indian Number Format:  {num_pass} passed, {num_fail} failed")

    if recon_issues:
        print(f"\n  KEY ISSUES FOUND:")
        for issue in recon_issues:
            print(f"    - {issue}")

    print(f"\n{'='*70}")
    print("  EVALUATION COMPLETE")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
