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

    Uppercases, removes spaces/hyphens/slashes, strips leading zeros
    from purely numeric segments.
    """
    if not inv_no:
        return ""
    s = inv_no.upper().strip()
    s = re.sub(r"[\s\-/]", "", s)
    # Strip leading zeros from numeric-only segments
    # Split by non-digit boundaries, strip zeros, rejoin
    parts = re.split(r"(\D+)", s)
    normalized = []
    for part in parts:
        if part.isdigit():
            normalized.append(part.lstrip("0") or "0")
        else:
            normalized.append(part)
    return "".join(normalized)


def _parse_float(val) -> float:
    """Safely parse a value to float."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).replace(",", "").replace(" ", "").strip()
        return float(cleaned) if cleaned else 0.0
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

    return {
        "gstin_supplier": gstin,
        "invoice_no": inv_no,
        "invoice_date": _parse_date(_get(_INVDATE_ALIASES)),
        "taxable_value": _parse_float(_get(_TAXABLE_ALIASES)),
        "igst": igst,
        "cgst": cgst,
        "sgst": sgst,
        "total_tax": igst + cgst + sgst,
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
            taxable = 0.0
            for item in inv.get("items", []):
                taxable += _parse_float(item.get("txval", 0))
                igst += _parse_float(item.get("igst", 0))
                cgst += _parse_float(item.get("cgst", 0))
                sgst += _parse_float(item.get("sgst", 0))

            records.append({
                "gstin_supplier": ctin.upper().strip(),
                "invoice_no": str(inv.get("inum", "")).strip(),
                "invoice_date": _parse_date(inv.get("dt", "")),
                "taxable_value": taxable,
                "igst": igst,
                "cgst": cgst,
                "sgst": sgst,
                "total_tax": igst + cgst + sgst,
                "itc_available": inv.get("itcavl", "Y") == "Y",
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

    logger.info(f"Purchase Register: Extracted {len(records)} records from {path.name}")
    return records


# ---------------------------------------------------------------------------
# Core reconciliation logic
# ---------------------------------------------------------------------------

def reconcile(gstr2b_records: list[dict], purchase_records: list[dict]) -> dict:
    """Core matching logic — pure Python, no LLM.

    Matching key: (normalized gstin_supplier, normalized invoice_no)
    """
    def _make_key(rec: dict) -> tuple:
        gstin = rec.get("gstin_supplier", "").upper().strip()
        inv = _normalize_invoice_no(rec.get("invoice_no", ""))
        return (gstin, inv)

    # Build lookup dicts
    gstr2b_map: dict[tuple, dict] = {}
    for rec in gstr2b_records:
        key = _make_key(rec)
        if key[0] and key[1]:
            gstr2b_map[key] = rec

    purchase_map: dict[tuple, dict] = {}
    for rec in purchase_records:
        key = _make_key(rec)
        if key[0] and key[1]:
            purchase_map[key] = rec

    all_keys = set(gstr2b_map.keys()) | set(purchase_map.keys())

    matched = []
    value_mismatch = []
    missing_in_books = []
    missing_in_gstr2b = []

    itc_available = 0.0
    itc_at_risk = 0.0
    itc_mismatch_amount = 0.0

    for key in all_keys:
        in_2b = key in gstr2b_map
        in_pr = key in purchase_map

        if in_2b and in_pr:
            rec_2b = gstr2b_map[key]
            rec_pr = purchase_map[key]

            taxable_diff = abs(rec_2b["taxable_value"] - rec_pr["taxable_value"])
            tax_diff = abs(rec_2b["total_tax"] - rec_pr["total_tax"])

            combined = {
                "gstin_supplier": rec_2b["gstin_supplier"],
                "invoice_no": rec_2b["invoice_no"],
                "invoice_date_2b": rec_2b["invoice_date"] or "N/A",
                "invoice_date_books": rec_pr["invoice_date"] or "N/A",
                "taxable_value_2b": rec_2b["taxable_value"],
                "taxable_value_books": rec_pr["taxable_value"],
                "total_tax_2b": rec_2b["total_tax"],
                "total_tax_books": rec_pr["total_tax"],
                "taxable_diff": round(taxable_diff, 2),
                "tax_diff": round(tax_diff, 2),
                # Normalized fields for frontend
                "gstin": rec_2b["gstin_supplier"],
                "date": rec_2b["invoice_date"] or "N/A",
                "taxable_value": rec_2b["taxable_value"],
                "total_tax": rec_2b["total_tax"],
            }

            if taxable_diff > AMOUNT_TOLERANCE or tax_diff > AMOUNT_TOLERANCE:
                combined["mismatch_type"] = []
                if taxable_diff > AMOUNT_TOLERANCE:
                    combined["mismatch_type"].append("VALUE_MISMATCH")
                if tax_diff > AMOUNT_TOLERANCE:
                    combined["mismatch_type"].append("TAX_MISMATCH")
                combined["remark"] = ", ".join(combined["mismatch_type"])
                value_mismatch.append(combined)
                itc_mismatch_amount += abs(rec_2b["total_tax"] - rec_pr["total_tax"])
            else:
                combined["remark"] = ""
                matched.append(combined)
                itc_available += rec_2b["total_tax"]

        elif in_2b and not in_pr:
            rec_2b = gstr2b_map[key]
            missing_in_books.append({
                "gstin_supplier": rec_2b["gstin_supplier"],
                "invoice_no": rec_2b["invoice_no"],
                "invoice_date": rec_2b["invoice_date"] or "N/A",
                "taxable_value": rec_2b["taxable_value"],
                "total_tax": rec_2b["total_tax"],
                "remark": "In GSTR-2B but not in purchase register — ITC available but unclaimed",
                # Normalized fields for frontend
                "gstin": rec_2b["gstin_supplier"],
                "date": rec_2b["invoice_date"] or "N/A",
            })
            itc_available += rec_2b["total_tax"]

        else:  # in_pr and not in_2b
            rec_pr = purchase_map[key]
            missing_in_gstr2b.append({
                "gstin_supplier": rec_pr["gstin_supplier"],
                "invoice_no": rec_pr["invoice_no"],
                "invoice_date": rec_pr["invoice_date"] or "N/A",
                "taxable_value": rec_pr["taxable_value"],
                "total_tax": rec_pr["total_tax"],
                "remark": "In purchase register but NOT in GSTR-2B — ITC at risk, needs supplier follow-up",
                # Normalized fields for frontend
                "gstin": rec_pr["gstin_supplier"],
                "date": rec_pr["invoice_date"] or "N/A",
            })
            itc_at_risk += rec_pr["total_tax"]

    return {
        "matched": matched,
        "value_mismatch": value_mismatch,
        "missing_in_books": missing_in_books,
        "missing_in_gstr2b": missing_in_gstr2b,
        "summary": {
            "total_invoices_gstr2b": len(gstr2b_records),
            "total_invoices_books": len(purchase_records),
            "matched_count": len(matched),
            "mismatch_count": len(value_mismatch),
            "missing_in_books_count": len(missing_in_books),
            "missing_in_gstr2b_count": len(missing_in_gstr2b),
            "itc_available": round(itc_available, 2),
            "itc_at_risk": round(itc_at_risk, 2),
            "itc_mismatch_amount": round(itc_mismatch_amount, 2),
        },
    }
