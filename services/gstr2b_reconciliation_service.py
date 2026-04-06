"""GSTR-2B vs Purchase Register reconciliation — deterministic data matching."""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Regex for valid GSTIN: 2 digits, 5 alpha, 4 digits, 1 alpha, 1 digit, Z, 1 alphanumeric
GSTIN_REGEX = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z0-9]$")

AMOUNT_TOLERANCE = 1.0  # Rs 1 tolerance for rounding differences


def _normalize_invoice_no(inv_no: str) -> str:
    """Normalize an invoice number for matching.

    Uppercases, splits on separators first, strips leading zeros
    from purely numeric segments, then rejoins without separators.
    """
    if not inv_no:
        return ""
    s = inv_no.upper().strip()
    # Split into segments at separator boundaries FIRST
    segments = re.split(r"[\s\-/]+", s)
    normalized = []
    for seg in segments:
        # Within each segment, split by non-digit boundaries and strip zeros
        parts = re.split(r"(\D+)", seg)
        for part in parts:
            if part.isdigit():
                normalized.append(part.lstrip("0") or "0")
            elif part:
                normalized.append(part)
    return "".join(normalized)


def _parse_float(val) -> float:
    """Safely parse a value to float, including Indian lakh/crore suffixes."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace(",", "").strip()
        if not cleaned:
            return 0.0
        # Detect Indian number suffixes
        cleaned_lower = cleaned.lower().strip()
        multiplier = 1
        if re.search(r"(lakhs?|lacs?)$", cleaned_lower):
            cleaned = re.sub(r"\s*(lakhs?|lacs?)$", "", cleaned_lower).strip()
            multiplier = 100_000
        elif re.search(r"(crores?|cr)$", cleaned_lower):
            cleaned = re.sub(r"\s*(crores?|cr)$", "", cleaned_lower).strip()
            multiplier = 1_00_00_000
        else:
            cleaned = cleaned.replace(" ", "")
        return float(cleaned) * multiplier if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


def _parse_date(val) -> str | None:
    """Normalize date string to DD-MM-YYYY format. Returns None if unparseable."""
    if not val:
        return None
    s = str(val).strip()
    if not s:
        return None
    # Try common formats
    import datetime
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            dt = datetime.datetime.strptime(s, fmt)
            return dt.strftime("%d-%m-%Y")
        except ValueError:
            continue
    return s


# ---------------------------------------------------------------------------
# Column name mapping for flexible header matching
# ---------------------------------------------------------------------------
_GSTIN_ALIASES = {"gstin", "supplier gstin", "party gstin", "gstin of supplier",
                  "gstin_supplier", "supplier_gstin", "vendor gstin", "gstin no"}
_INVNO_ALIASES = {"invoice no", "invoice number", "bill no", "inv no",
                  "invoice_no", "bill_no", "inv_no", "voucher no", "document no",
                  "invoice no."}
_INVDATE_ALIASES = {"invoice date", "bill date", "date", "invoice_date",
                    "bill_date", "inv date", "document date"}
_TAXABLE_ALIASES = {"taxable value", "taxable_value", "basic amount",
                    "assessable value", "taxable amt", "taxable amount", "base amount"}
_IGST_ALIASES = {"igst", "integrated tax", "igst amount", "igst_amount"}
_CGST_ALIASES = {"cgst", "central tax", "cgst amount", "cgst_amount"}
_SGST_ALIASES = {"sgst", "state tax", "sgst amount", "sgst_amount", "utgst"}
_CESS_ALIASES = {"cess", "gst cess", "compensation cess", "cess amount", "cess_amount"}


def _find_column(df_columns: list, aliases: set) -> str | None:
    """Find the first matching column from aliases (case-insensitive)."""
    lower_map = {c.lower().strip(): c for c in df_columns}
    for alias in aliases:
        if alias in lower_map:
            return lower_map[alias]
    return None


def _record_from_row(row: dict, source: str) -> dict | None:
    """Build a standardized record dict from a row dict with flexible column names."""
    keys_lower = {k.lower().strip(): k for k in row.keys()}

    def _get(aliases):
        for a in aliases:
            if a in keys_lower:
                return row[keys_lower[a]]
        return None

    gstin = str(_get(_GSTIN_ALIASES) or "").upper().strip()
    inv_no = str(_get(_INVNO_ALIASES) or "").strip()

    if not gstin or not inv_no:
        return None

    igst = _parse_float(_get(_IGST_ALIASES))
    cgst = _parse_float(_get(_CGST_ALIASES))
    sgst = _parse_float(_get(_SGST_ALIASES))
    cess = _parse_float(_get(_CESS_ALIASES))

    return {
        "gstin_supplier": gstin,
        "invoice_no": inv_no,
        "invoice_date": _parse_date(_get(_INVDATE_ALIASES)),
        "taxable_value": _parse_float(_get(_TAXABLE_ALIASES)),
        "igst": igst,
        "cgst": cgst,
        "sgst": sgst,
        "cess": cess,
        "total_tax": igst + cgst + sgst + cess,
        "itc_available": True,
        "source": source,
    }


# ---------------------------------------------------------------------------
# Extraction functions
# ---------------------------------------------------------------------------

def extract_gstr2b_records(file_path: str) -> list[dict]:
    """Extract invoice records from GSTR-2B PDF or JSON file."""
    path = Path(file_path)
    records = []

    if path.suffix.lower() == ".json":
        records = _extract_gstr2b_json(path)
    elif path.suffix.lower() == ".pdf":
        records = _extract_from_pdf(path, source="gstr2b")
    elif path.suffix.lower() in (".csv", ".xlsx", ".xls"):
        records = _extract_from_tabular(path, source="gstr2b")
    else:
        logger.warning(f"Unsupported GSTR-2B file format: {path.suffix}")

    # Validate GSTIN format
    valid = [r for r in records if GSTIN_REGEX.match(r.get("gstin_supplier", ""))]
    logger.info(f"GSTR-2B: Extracted {len(records)} records, {len(valid)} with valid GSTIN")
    return valid


def _extract_gstr2b_json(path: Path) -> list[dict]:
    """Parse GSTR-2B JSON download from GSTN portal."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = []

    # GSTN JSON structure: data.docdata.b2b[] -> each has ctin and inv[]
    doc_data = data
    # Navigate nested structure — handle multiple common formats
    if "data" in doc_data:
        doc_data = doc_data["data"]
    if "docdata" in doc_data:
        doc_data = doc_data["docdata"]

    b2b_list = doc_data.get("b2b", [])
    for supplier in b2b_list:
        ctin = supplier.get("ctin", "")
        for inv in supplier.get("inv", []):
            igst = 0.0
            cgst = 0.0
            sgst = 0.0
            cess = 0.0
            taxable = 0.0
            for item in inv.get("items", []):
                taxable += _parse_float(item.get("txval", 0))
                igst += _parse_float(item.get("igst", 0))
                cgst += _parse_float(item.get("cgst", 0))
                sgst += _parse_float(item.get("sgst", 0))
                cess += _parse_float(item.get("cess", 0))

            records.append({
                "gstin_supplier": ctin.upper().strip(),
                "invoice_no": str(inv.get("inum", "")).strip(),
                "invoice_date": _parse_date(inv.get("dt", "")),
                "taxable_value": taxable,
                "igst": igst,
                "cgst": cgst,
                "sgst": sgst,
                "cess": cess,
                "total_tax": igst + cgst + sgst + cess,
                "itc_available": inv.get("itcavl", "Y") == "Y",
                "is_rcm": inv.get("rev", "N") == "Y",
                "source": "gstr2b",
            })

    return records


def _extract_from_tabular(path: Path, source: str) -> list[dict]:
    """Extract records from CSV or Excel files using pandas."""
    import pandas as pd

    try:
        if path.suffix.lower() == ".csv":
            df = pd.read_csv(path, dtype=str)
        else:
            df = pd.read_excel(path, dtype=str)
    except Exception as e:
        logger.error(f"Failed to read tabular file {path}: {e}")
        return []

    records = []
    for _, row in df.iterrows():
        rec = _record_from_row(row.to_dict(), source)
        if rec:
            records.append(rec)
    return records


def _extract_from_pdf(path: Path, source: str) -> list[dict]:
    """Extract records from a PDF using PyMuPDF table extraction."""
    try:
        import pymupdf  # PyMuPDF
    except ImportError:
        logger.error("PyMuPDF not available for PDF table extraction")
        return []

    records = []
    try:
        doc = pymupdf.open(str(path))
        for page in doc:
            tables = page.find_tables()
            for table in tables:
                data = table.extract()
                if len(data) < 2:
                    continue
                headers = [str(h).strip() if h else "" for h in data[0]]
                for row_cells in data[1:]:
                    row_dict = {}
                    for i, cell in enumerate(row_cells):
                        if i < len(headers):
                            row_dict[headers[i]] = str(cell).strip() if cell else ""
                    rec = _record_from_row(row_dict, source)
                    if rec:
                        records.append(rec)
        doc.close()
    except Exception as e:
        logger.error(f"PDF table extraction failed for {path}: {e}")

    return records


def extract_purchase_register(file_path: str) -> list[dict]:
    """Extract invoice records from purchase register (PDF/Excel/CSV)."""
    path = Path(file_path)
    records = []

    if path.suffix.lower() in (".csv", ".xlsx", ".xls"):
        records = _extract_from_tabular(path, source="purchase_register")
    elif path.suffix.lower() == ".pdf":
        records = _extract_from_pdf(path, source="purchase_register")
    else:
        logger.warning(f"Unsupported purchase register format: {path.suffix}")

    # Validate GSTIN format (same filter as GSTR-2B extraction)
    valid = [r for r in records if GSTIN_REGEX.match(r.get("gstin_supplier", ""))]
    logger.info(f"Purchase Register: Extracted {len(records)} records, {len(valid)} with valid GSTIN from {path.name}")
    return valid


# ---------------------------------------------------------------------------
# Core reconciliation logic
# ---------------------------------------------------------------------------

def reconcile(gstr2b_records: list[dict], purchase_records: list[dict]) -> dict:
    """Core matching logic — pure Python, no LLM.

    Matching key: (normalized gstin_supplier, normalized invoice_no)
    Features: ITC eligibility tracking, cess support, date mismatch detection,
    duplicate handling, fuzzy matching fallback.
    """
    def _make_key(rec: dict) -> tuple:
        gstin = rec.get("gstin_supplier", "").upper().strip()
        inv = _normalize_invoice_no(rec.get("invoice_no", ""))
        return (gstin, inv)

    # --- Build lookup dicts with duplicate detection ---
    gstr2b_map: dict[tuple, dict] = {}
    gstr2b_dupes: list[dict] = []
    for rec in gstr2b_records:
        key = _make_key(rec)
        if key[0] and key[1]:
            if key in gstr2b_map:
                # GSTR-2B duplicate: likely amendment — aggregate values
                existing = gstr2b_map[key]
                existing["taxable_value"] = existing.get("taxable_value", 0) + rec.get("taxable_value", 0)
                existing["igst"] = existing.get("igst", 0) + rec.get("igst", 0)
                existing["cgst"] = existing.get("cgst", 0) + rec.get("cgst", 0)
                existing["sgst"] = existing.get("sgst", 0) + rec.get("sgst", 0)
                existing["cess"] = existing.get("cess", 0) + rec.get("cess", 0)
                existing["total_tax"] = (existing["igst"] + existing["cgst"]
                                         + existing["sgst"] + existing.get("cess", 0))
                gstr2b_dupes.append({
                    "gstin": key[0], "invoice_no": rec.get("invoice_no", ""),
                    "action": "aggregated",
                    "taxable_value": rec.get("taxable_value", 0),
                })
            else:
                gstr2b_map[key] = rec

    purchase_map: dict[tuple, dict] = {}
    purchase_dupes: list[dict] = []
    for rec in purchase_records:
        key = _make_key(rec)
        if key[0] and key[1]:
            if key in purchase_map:
                # Purchase register duplicate: flag as potential data entry error
                purchase_dupes.append({
                    "gstin": key[0], "invoice_no": rec.get("invoice_no", ""),
                    "action": "duplicate_flagged",
                    "taxable_value": rec.get("taxable_value", 0),
                })
            else:
                purchase_map[key] = rec

    all_keys = set(gstr2b_map.keys()) | set(purchase_map.keys())

    matched = []
    value_mismatch = []
    missing_in_books = []
    missing_in_gstr2b = []

    itc_available = 0.0
    itc_at_risk = 0.0
    itc_ineligible = 0.0
    itc_mismatch_amount = 0.0
    total_cess = 0.0

    for key in all_keys:
        in_2b = key in gstr2b_map
        in_pr = key in purchase_map

        if in_2b and in_pr:
            rec_2b = gstr2b_map[key]
            rec_pr = purchase_map[key]

            taxable_2b = rec_2b.get("taxable_value", 0.0)
            taxable_pr = rec_pr.get("taxable_value", 0.0)
            tax_2b = rec_2b.get("total_tax", 0.0)
            tax_pr = rec_pr.get("total_tax", 0.0)
            taxable_diff = abs(taxable_2b - taxable_pr)
            tax_diff = abs(tax_2b - tax_pr)

            date_2b = rec_2b.get("invoice_date") or "N/A"
            date_pr = rec_pr.get("invoice_date") or "N/A"
            itc_eligible = rec_2b.get("itc_available", True)

            combined = {
                "gstin_supplier": rec_2b.get("gstin_supplier", ""),
                "invoice_no": rec_2b.get("invoice_no", ""),
                "invoice_date_2b": date_2b,
                "invoice_date_books": date_pr,
                "taxable_value_2b": taxable_2b,
                "taxable_value_books": taxable_pr,
                "total_tax_2b": tax_2b,
                "total_tax_books": tax_pr,
                "cess_2b": rec_2b.get("cess", 0.0),
                "cess_books": rec_pr.get("cess", 0.0),
                "taxable_diff": round(taxable_diff, 2),
                "tax_diff": round(tax_diff, 2),
                "itc_eligible": itc_eligible,
                # Normalized fields for frontend
                "gstin": rec_2b.get("gstin_supplier", ""),
                "date": date_2b,
                "taxable_value": taxable_2b,
                "total_tax": tax_2b,
            }

            # Detect mismatch types
            mismatch_types = []
            if taxable_diff > AMOUNT_TOLERANCE:
                mismatch_types.append("VALUE_MISMATCH")
            if tax_diff > AMOUNT_TOLERANCE:
                mismatch_types.append("TAX_MISMATCH")
            # Date mismatch is informational — doesn't affect ITC
            if date_2b != "N/A" and date_pr != "N/A" and date_2b != date_pr:
                mismatch_types.append("DATE_MISMATCH")

            has_value_or_tax_mismatch = "VALUE_MISMATCH" in mismatch_types or "TAX_MISMATCH" in mismatch_types

            if has_value_or_tax_mismatch:
                combined["mismatch_type"] = mismatch_types
                combined["remark"] = ", ".join(mismatch_types)
                value_mismatch.append(combined)
                itc_mismatch_amount += abs(tax_2b - tax_pr)
            else:
                combined["mismatch_type"] = mismatch_types  # may contain DATE_MISMATCH
                combined["remark"] = ", ".join(mismatch_types) if mismatch_types else ""
                matched.append(combined)
                if itc_eligible:
                    itc_available += tax_2b
                else:
                    itc_ineligible += tax_2b

            total_cess += rec_2b.get("cess", 0.0)

        elif in_2b and not in_pr:
            rec_2b = gstr2b_map[key]
            tax_2b = rec_2b.get("total_tax", 0.0)
            itc_eligible = rec_2b.get("itc_available", True)
            missing_in_books.append({
                "gstin_supplier": rec_2b.get("gstin_supplier", ""),
                "invoice_no": rec_2b.get("invoice_no", ""),
                "invoice_date": rec_2b.get("invoice_date") or "N/A",
                "taxable_value": rec_2b.get("taxable_value", 0.0),
                "total_tax": tax_2b,
                "cess": rec_2b.get("cess", 0.0),
                "itc_eligible": itc_eligible,
                "remark": "In GSTR-2B but not in purchase register — ITC available but unclaimed",
                # Normalized fields for frontend
                "gstin": rec_2b.get("gstin_supplier", ""),
                "date": rec_2b.get("invoice_date") or "N/A",
            })
            if itc_eligible:
                itc_available += tax_2b
            else:
                itc_ineligible += tax_2b
            total_cess += rec_2b.get("cess", 0.0)

        else:  # in_pr and not in_2b
            rec_pr = purchase_map[key]
            tax_pr = rec_pr.get("total_tax", 0.0)
            missing_in_gstr2b.append({
                "gstin_supplier": rec_pr.get("gstin_supplier", ""),
                "invoice_no": rec_pr.get("invoice_no", ""),
                "invoice_date": rec_pr.get("invoice_date") or "N/A",
                "taxable_value": rec_pr.get("taxable_value", 0.0),
                "total_tax": tax_pr,
                "cess": rec_pr.get("cess", 0.0),
                "remark": "In purchase register but NOT in GSTR-2B — ITC at risk, needs supplier follow-up",
                # Normalized fields for frontend
                "gstin": rec_pr.get("gstin_supplier", ""),
                "date": rec_pr.get("invoice_date") or "N/A",
            })
            itc_at_risk += tax_pr

    # --- Fuzzy matching fallback for unmatched records ---
    potential_matches = _fuzzy_match_unmatched(
        gstr2b_map, purchase_map, missing_in_books, missing_in_gstr2b
    )

    duplicate_count = len(gstr2b_dupes) + len(purchase_dupes)

    return {
        "matched": matched,
        "value_mismatch": value_mismatch,
        "missing_in_books": missing_in_books,
        "missing_in_gstr2b": missing_in_gstr2b,
        "potential_matches": potential_matches,
        "duplicates_2b": gstr2b_dupes,
        "duplicates_books": purchase_dupes,
        "summary": {
            "total_invoices_gstr2b": len(gstr2b_records),
            "total_invoices_books": len(purchase_records),
            "matched_count": len(matched),
            "mismatch_count": len(value_mismatch),
            "missing_in_books_count": len(missing_in_books),
            "missing_in_gstr2b_count": len(missing_in_gstr2b),
            "itc_available": round(itc_available, 2),
            "itc_at_risk": round(itc_at_risk, 2),
            "itc_ineligible": round(itc_ineligible, 2),
            "itc_mismatch_amount": round(itc_mismatch_amount, 2),
            "total_cess": round(total_cess, 2),
            "duplicate_count": duplicate_count,
            "potential_match_count": len(potential_matches),
        },
    }


def _fuzzy_match_unmatched(
    gstr2b_map: dict, purchase_map: dict,
    missing_in_books: list, missing_in_gstr2b: list,
) -> list[dict]:
    """Second-pass fuzzy matching for unmatched records with same GSTIN."""
    potential_matches = []
    try:
        from rapidfuzz import fuzz
    except ImportError:
        logger.info("rapidfuzz not installed — skipping fuzzy matching")
        return potential_matches

    # Collect unmatched keys
    unmatched_2b_keys = {
        (_normalize_invoice_no(r.get("invoice_no", "")), r.get("gstin_supplier", "").upper(), r.get("invoice_no", ""))
        for r in missing_in_books
    }
    unmatched_pr_keys = {
        (_normalize_invoice_no(r.get("invoice_no", "")), r.get("gstin_supplier", "").upper(), r.get("invoice_no", ""))
        for r in missing_in_gstr2b
    }

    for norm_2b, gstin_2b, raw_2b in unmatched_2b_keys:
        for norm_pr, gstin_pr, raw_pr in unmatched_pr_keys:
            if gstin_2b != gstin_pr:
                continue
            similarity = fuzz.ratio(norm_2b, norm_pr)
            if similarity >= 80:
                potential_matches.append({
                    "gstin": gstin_2b,
                    "invoice_2b": raw_2b,
                    "invoice_books": raw_pr,
                    "similarity": similarity,
                    "confidence": "high" if similarity >= 90 else "medium",
                })

    return potential_matches
