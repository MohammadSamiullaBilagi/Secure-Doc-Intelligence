"""GSTR-9 Annual Return Pre-Filing Reconciliation - GSTR-1 vs GSTR-3B vs Books."""

import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 12_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _month_key(month_str: str) -> str:
    """Normalize a month string to YYYY-MM format.

    Handles: "Apr 2025", "April 2025", "04/2025", "2025-04", "Apr-25", etc.
    """
    if not month_str:
        return "unknown"
    s = str(month_str).strip()

    # Already YYYY-MM
    if re.match(r"^\d{4}-\d{2}$", s):
        return s

    # MM/YYYY or MM-YYYY
    m = re.match(r"^(\d{1,2})[/\-](\d{4})$", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"

    # Month-name patterns
    month_names = {
        "jan": "01", "january": "01", "feb": "02", "february": "02",
        "mar": "03", "march": "03", "apr": "04", "april": "04",
        "may": "05", "jun": "06", "june": "06", "jul": "07", "july": "07",
        "aug": "08", "august": "08", "sep": "09", "september": "09",
        "oct": "10", "october": "10", "nov": "11", "november": "11",
        "dec": "12", "december": "12",
    }

    # "Apr 2025" / "April-2025" / "Apr-25"
    m = re.match(r"^([A-Za-z]+)[\s\-]+(\d{2,4})$", s)
    if m:
        mon = month_names.get(m.group(1).lower())
        year = m.group(2)
        if len(year) == 2:
            year = "20" + year
        if mon:
            return f"{year}-{mon}"

    # "2025 Apr"
    m = re.match(r"^(\d{4})[\s\-]+([A-Za-z]+)$", s)
    if m:
        mon = month_names.get(m.group(2).lower())
        if mon:
            return f"{m.group(1)}-{mon}"

    return s.lower().replace(" ", "-")


def _severity(diff: float, base: float) -> str:
    """Classify severity by percentage of base."""
    if base == 0:
        return "HIGH" if abs(diff) > 100 else "LOW"
    pct = abs(diff) / abs(base) * 100
    if pct > 5:
        return "HIGH"
    elif pct > 1:
        return "MEDIUM"
    return "LOW"


def _robust_json_parse(text: str) -> dict:
    """Try multiple strategies to extract valid JSON from LLM output."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        stripped = "\n".join(lines)
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

    return {}


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

class GSTR9ReconciliationService:
    """Parses GSTR-1 and GSTR-3B PDFs via direct text extraction, then reconciles deterministically."""

    def parse_monthly_data(self, raw_text: str, return_type: str) -> dict:
        """Extract monthly GST data from raw PDF text using direct text parsing.

        Args:
            raw_text: Extracted text from PDF.
            return_type: "gstr1" or "gstr3b".

        Returns:
            Dict with standardized monthly fields.
        """
        # Try direct text parsing first
        if return_type == "gstr1":
            result = self._parse_gstr1_text(raw_text)
        else:
            result = self._parse_gstr3b_text(raw_text)

        if result and "error" not in result:
            logger.info(f"GSTR-9 direct parser ({return_type}): month={result.get('month')}")
            return result

        # Fallback to LLM if direct parsing fails
        logger.info(f"GSTR-9 direct parser ({return_type}) returned no data, trying LLM fallback")
        try:
            return self._parse_via_llm(raw_text, return_type)
        except Exception as e:
            logger.warning(f"GSTR-9 LLM fallback ({return_type}) failed: {e}")
            return {"error": str(e), "month": "unknown"}

    def _extract_gstin(self, text: str) -> str:
        """Extract GSTIN from text."""
        m = re.search(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z][Z][0-9A-Z])\b", text)
        return m.group(1) if m else ""

    def _extract_tax_period(self, text: str) -> str:
        """Extract tax period/month from text."""
        # "Tax Period: Apr 2025" or "Period: Apr 2025"
        m = re.search(r"(?:Tax\s*)?Period[:\s]+([A-Za-z]+\s*\d{4})", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # "Period: 04/2025"
        m = re.search(r"Period[:\s]+(\d{2}/\d{4})", text, re.IGNORECASE)
        if m:
            return m.group(1)
        return "unknown"

    def _find_amount_after(self, text: str, label: str) -> float:
        """Find the first amount value on the same line or next line after a label."""
        pattern = re.escape(label) + r"[:\s]*([0-9,]+\.\d{2})"
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return _parse_float(m.group(1))
        return 0.0

    def _extract_amounts_in_section(self, text: str, section_start: str, section_end: str | None = None) -> list[float]:
        """Extract all amounts from a section of text between markers."""
        start_idx = text.find(section_start)
        if start_idx < 0:
            return []
        sub = text[start_idx:]
        if section_end:
            end_idx = sub.find(section_end, len(section_start))
            if end_idx > 0:
                sub = sub[:end_idx]
        amounts = re.findall(r"[\d,]+\.\d{2}", sub)
        return [_parse_float(a) for a in amounts]

    def _parse_gstr1_text(self, text: str) -> dict:
        """Direct text parser for GSTR-1 returns."""
        if "GSTR-1" not in text.upper() and "GSTR1" not in text.upper():
            return {"error": "Not a GSTR-1 document"}

        gstin = self._extract_gstin(text)
        month = self._extract_tax_period(text)

        # Extract from Summary section (most reliable)
        summary_amounts = self._extract_amounts_in_section(
            text, "Summary of Outward Supplies", "Generated from"
        )

        # Try to find the summary row "Total Taxable Outward Supplies"
        total_taxable = 0.0
        igst = 0.0
        cgst = 0.0
        sgst = 0.0
        cess = 0.0
        exempt_nil = 0.0
        cdn = 0.0
        amendments = 0.0

        lines = text.split("\n")
        in_summary = False
        for i, line in enumerate(lines):
            stripped = line.strip()

            if "Summary of Outward Supplies" in stripped:
                in_summary = True
                continue

            if in_summary:
                if "Total Taxable Outward Supplies" in stripped:
                    # Next amounts on following lines are the values
                    vals = self._collect_amounts_after(lines, i)
                    if len(vals) >= 4:
                        total_taxable = vals[0]
                        igst = vals[1]
                        cgst = vals[2]
                        sgst = vals[3]
                        cess = vals[4] if len(vals) > 4 else 0.0

                elif "Credit/Debit Notes" in stripped:
                    vals = self._collect_amounts_after(lines, i)
                    if vals:
                        cdn = vals[0]
                        # Handle negative: check if there's a minus sign in the line
                        if "-" in stripped or (i + 1 < len(lines) and "-" in lines[i + 1]):
                            cdn = -abs(cdn)

                elif "Amendments" in stripped:
                    vals = self._collect_amounts_after(lines, i)
                    if vals:
                        amendments = vals[0]

                elif "Exempt/Nil/Non-GST" in stripped or "Nil Rated" in stripped:
                    vals = self._collect_amounts_after(lines, i)
                    if vals:
                        exempt_nil = vals[0]

        # Fallback: try extracting from B2B + B2C sections
        if total_taxable == 0:
            b2b_amounts = self._extract_amounts_in_section(text, "Table 4", "Table 5")
            b2c_amounts = self._extract_amounts_in_section(text, "Table 5", "Table 8")
            b2b = b2b_amounts[0] if b2b_amounts else 0.0
            b2c = b2c_amounts[0] if b2c_amounts else 0.0
            total_taxable = b2b + b2c

        # Extract exempt from Table 8
        if exempt_nil == 0:
            exempt_amounts = self._extract_amounts_in_section(text, "Table 8", "Summary")
            if exempt_amounts:
                exempt_nil = exempt_amounts[0]

        if total_taxable == 0 and igst == 0 and cgst == 0:
            return {"error": "Could not extract GSTR-1 data"}

        return {
            "month": month,
            "gstin": gstin,
            "b2b_taxable": 0.0,  # Detailed B2B not needed for reconciliation
            "b2c_taxable": 0.0,
            "total_taxable": total_taxable,
            "exempt_nil": exempt_nil,
            "igst": igst,
            "cgst": cgst,
            "sgst": sgst,
            "cess": cess,
            "credit_debit_notes": cdn,
            "amendments": amendments,
        }

    def _parse_gstr3b_text(self, text: str) -> dict:
        """Direct text parser for GSTR-3B returns."""
        if "GSTR-3B" not in text.upper() and "GSTR3B" not in text.upper():
            return {"error": "Not a GSTR-3B document"}

        gstin = self._extract_gstin(text)
        month = self._extract_tax_period(text)

        total_taxable = 0.0
        exempt_nil = 0.0
        igst = 0.0
        cgst = 0.0
        sgst = 0.0
        cess = 0.0
        itc_igst = 0.0
        itc_cgst = 0.0
        itc_sgst = 0.0
        itc_cess = 0.0
        itc_reversed = 0.0
        tax_paid_cash = 0.0
        tax_paid_itc = 0.0

        lines = text.split("\n")

        for i, line in enumerate(lines):
            stripped = line.strip()

            # Table 3.1 - row (a) Outward taxable supplies
            if "(a) Outward taxable supplies" in stripped or "Outward taxable supplies (other than" in stripped:
                vals = self._collect_amounts_after(lines, i)
                if len(vals) >= 5:
                    total_taxable = vals[0]
                    igst = vals[1]
                    cgst = vals[2]
                    sgst = vals[3]
                    cess = vals[4]

            # Table 3.1 - row (c) exempt/nil
            elif "(c) Other outward supplies" in stripped or "nil rated, exempted" in stripped:
                vals = self._collect_amounts_after(lines, i)
                if vals:
                    exempt_nil = vals[0]

            # Table 4 - ITC Available row (A)
            elif "(A) ITC Available" in stripped:
                vals = self._collect_amounts_after(lines, i)
                if len(vals) >= 4:
                    itc_igst = vals[0]
                    itc_cgst = vals[1]
                    itc_sgst = vals[2]
                    itc_cess = vals[3]

            # ITC Reversed
            elif "ITC Reversed (4B)" in stripped or "ITC Reversed:" in stripped:
                vals = self._collect_amounts_after(lines, i)
                if vals:
                    itc_reversed = vals[0]
                # Also try: "ITC Reversed (4B): Rs. 1,600.00"
                m = re.search(r"Rs\.\s*([\d,]+\.\d{2})", stripped)
                if m:
                    itc_reversed = _parse_float(m.group(1))

            # Total Tax Paid through ITC
            elif "Tax Paid through ITC" in stripped:
                m = re.search(r"Rs\.\s*([\d,]+\.\d{2})", stripped)
                if m:
                    tax_paid_itc = _parse_float(m.group(1))

            # Total Tax Paid in Cash
            elif "Tax Paid in Cash" in stripped:
                m = re.search(r"Rs\.\s*([\d,]+\.\d{2})", stripped)
                if m:
                    tax_paid_cash = _parse_float(m.group(1))

        # Fallback for ITC reversed from Table 4 (B) row
        if itc_reversed == 0:
            for i, line in enumerate(lines):
                if "(B) ITC Reversed" in line.strip():
                    vals = self._collect_amounts_after(lines, i)
                    if vals:
                        itc_reversed = sum(vals[:4])  # Sum IGST+CGST+SGST+Cess reversed
                    break

        if total_taxable == 0 and igst == 0 and cgst == 0:
            return {"error": "Could not extract GSTR-3B data"}

        return {
            "month": month,
            "gstin": gstin,
            "total_taxable": total_taxable,
            "exempt_nil": exempt_nil,
            "igst": igst,
            "cgst": cgst,
            "sgst": sgst,
            "cess": cess,
            "itc_igst": itc_igst,
            "itc_cgst": itc_cgst,
            "itc_sgst": itc_sgst,
            "itc_cess": itc_cess,
            "itc_reversed": itc_reversed,
            "tax_paid_cash": tax_paid_cash,
            "tax_paid_itc": tax_paid_itc,
        }

    def _collect_amounts_after(self, lines: list[str], start_idx: int) -> list[float]:
        """Collect numeric amounts from the line at start_idx and subsequent lines until next text label."""
        amounts = []
        # Check current line first
        current = lines[start_idx].strip() if start_idx < len(lines) else ""
        for m in re.finditer(r"-?[\d,]+\.\d{2}", current):
            amounts.append(_parse_float(m.group()))

        # Then check following lines
        for j in range(start_idx + 1, min(start_idx + 8, len(lines))):
            line = lines[j].strip()
            if not line:
                continue
            # Stop if we hit a text label (non-numeric line that isn't just an amount)
            if re.match(r"^-?[\d,]+\.\d{2}$", line):
                amounts.append(_parse_float(line))
            elif re.match(r"^-[\d,]+\.\d{2}$", line):
                amounts.append(_parse_float(line))
            else:
                # Line has text - stop collecting
                break
        return amounts

    def _parse_via_llm(self, raw_text: str, return_type: str) -> dict:
        """Fallback: parse using LLM if direct parsing fails."""
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate

        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=4096,
        ).bind(response_format={"type": "json_object"})

        truncated = raw_text[:MAX_INPUT_CHARS]

        if return_type == "gstr1":
            prompt = ChatPromptTemplate.from_messages([
                ("system",
                 "You are an expert Indian GST data extraction specialist.\n\n"
                 "TASK: Extract GSTR-1 monthly return data from the document text.\n\n"
                 "OUTPUT VALID JSON with these keys:\n"
                 "- month, gstin, b2b_taxable, b2c_taxable, total_taxable, exempt_nil,\n"
                 "  igst, cgst, sgst, cess, credit_debit_notes, amendments\n\n"
                 "Use 0 for missing numeric fields. Return ONLY valid JSON."),
                ("human", "{text}"),
            ])
        else:
            prompt = ChatPromptTemplate.from_messages([
                ("system",
                 "You are an expert Indian GST data extraction specialist.\n\n"
                 "TASK: Extract GSTR-3B monthly return data from the document text.\n\n"
                 "OUTPUT VALID JSON with these keys:\n"
                 "- month, gstin, total_taxable, exempt_nil, igst, cgst, sgst, cess,\n"
                 "  itc_igst, itc_cgst, itc_sgst, itc_cess, itc_reversed, tax_paid_cash, tax_paid_itc\n\n"
                 "Use 0 for missing numeric fields. Return ONLY valid JSON."),
                ("human", "{text}"),
            ])

        result = (prompt | llm).invoke({"text": truncated})
        parsed = _robust_json_parse(result.content)
        if not parsed:
            return {"error": "Failed to parse LLM output", "month": "unknown"}
        return parsed


# ---------------------------------------------------------------------------
# Deterministic reconciliation
# ---------------------------------------------------------------------------

def reconcile(gstr1_months: list[dict], gstr3b_months: list[dict],
              books_turnover: float | None = None) -> dict:
    """Pure Python, deterministic reconciliation of GSTR-1 vs GSTR-3B vs books.

    Returns a dict with: summary, monthly_comparison, tax_reconciliation,
    books_reconciliation, itc_summary, gstr9_tables, action_items.
    """
    # Index by normalized month key
    gstr1_by_month: dict[str, dict] = {}
    for m in gstr1_months:
        key = _month_key(m.get("month", ""))
        gstr1_by_month[key] = m

    gstr3b_by_month: dict[str, dict] = {}
    for m in gstr3b_months:
        key = _month_key(m.get("month", ""))
        gstr3b_by_month[key] = m

    all_month_keys = sorted(set(gstr1_by_month.keys()) | set(gstr3b_by_month.keys()))

    action_items: list[dict] = []
    monthly_comparison: list[dict] = []

    # Accumulators
    gstr1_total_turnover = 0.0
    gstr3b_total_turnover = 0.0
    gstr1_total_exempt = 0.0

    gstr1_igst = 0.0
    gstr1_cgst = 0.0
    gstr1_sgst = 0.0
    gstr1_cess = 0.0

    gstr3b_igst = 0.0
    gstr3b_cgst = 0.0
    gstr3b_sgst = 0.0
    gstr3b_cess = 0.0

    itc_igst = 0.0
    itc_cgst = 0.0
    itc_sgst = 0.0
    itc_cess = 0.0
    itc_reversed = 0.0
    tax_paid_cash = 0.0
    tax_paid_itc = 0.0

    discrepancy_count = 0

    # -----------------------------------------------------------------------
    # Step 1 — Monthly outward supply comparison (GSTR-1 vs GSTR-3B)
    # -----------------------------------------------------------------------
    for mk in all_month_keys:
        g1 = gstr1_by_month.get(mk, {})
        g3 = gstr3b_by_month.get(mk, {})

        g1_turnover = _parse_float(g1.get("total_taxable"))
        g3_turnover = _parse_float(g3.get("total_taxable"))
        turnover_diff = g1_turnover - g3_turnover

        g1_tax = (_parse_float(g1.get("igst")) + _parse_float(g1.get("cgst")) +
                  _parse_float(g1.get("sgst")) + _parse_float(g1.get("cess")))
        g3_tax = (_parse_float(g3.get("igst")) + _parse_float(g3.get("cgst")) +
                  _parse_float(g3.get("sgst")) + _parse_float(g3.get("cess")))
        tax_diff = g1_tax - g3_tax

        sev = "LOW"
        if abs(turnover_diff) > 100 or abs(tax_diff) > 100:
            sev = _severity(turnover_diff, g1_turnover or g3_turnover)

        if mk not in gstr1_by_month:
            sev = "HIGH"
            discrepancy_count += 1
            action_items.append({
                "priority": 1,
                "category": "MISSING_MONTH",
                "description": f"Month {mk} present in GSTR-3B but missing in GSTR-1",
                "financial_impact": g3_turnover,
                "recommendation": "File/amend GSTR-1 for this month or verify data source.",
            })
        elif mk not in gstr3b_by_month:
            sev = "HIGH"
            discrepancy_count += 1
            action_items.append({
                "priority": 1,
                "category": "MISSING_MONTH",
                "description": f"Month {mk} present in GSTR-1 but missing in GSTR-3B",
                "financial_impact": g1_turnover,
                "recommendation": "File/amend GSTR-3B for this month or verify data source.",
            })
        elif abs(turnover_diff) > 100:
            discrepancy_count += 1
            action_items.append({
                "priority": 2 if sev == "HIGH" else 3,
                "category": "TURNOVER_MISMATCH",
                "description": (f"Month {mk}: GSTR-1 turnover Rs.{g1_turnover:,.0f} vs "
                                f"GSTR-3B Rs.{g3_turnover:,.0f} (diff Rs.{turnover_diff:,.0f})"),
                "financial_impact": abs(turnover_diff),
                "recommendation": "Reconcile outward supplies — check amendments, credit/debit notes.",
            })

        monthly_comparison.append({
            "month": mk,
            "gstr1_turnover": round(g1_turnover, 2),
            "gstr3b_turnover": round(g3_turnover, 2),
            "turnover_diff": round(turnover_diff, 2),
            "gstr1_tax": round(g1_tax, 2),
            "gstr3b_tax": round(g3_tax, 2),
            "tax_diff": round(tax_diff, 2),
            "severity": sev,
        })

        # Accumulate
        gstr1_total_turnover += g1_turnover
        gstr3b_total_turnover += g3_turnover
        gstr1_total_exempt += _parse_float(g1.get("exempt_nil"))

        gstr1_igst += _parse_float(g1.get("igst"))
        gstr1_cgst += _parse_float(g1.get("cgst"))
        gstr1_sgst += _parse_float(g1.get("sgst"))
        gstr1_cess += _parse_float(g1.get("cess"))

        gstr3b_igst += _parse_float(g3.get("igst"))
        gstr3b_cgst += _parse_float(g3.get("cgst"))
        gstr3b_sgst += _parse_float(g3.get("sgst"))
        gstr3b_cess += _parse_float(g3.get("cess"))

        itc_igst += _parse_float(g3.get("itc_igst"))
        itc_cgst += _parse_float(g3.get("itc_cgst"))
        itc_sgst += _parse_float(g3.get("itc_sgst"))
        itc_cess += _parse_float(g3.get("itc_cess"))
        itc_reversed += _parse_float(g3.get("itc_reversed"))
        tax_paid_cash += _parse_float(g3.get("tax_paid_cash"))
        tax_paid_itc += _parse_float(g3.get("tax_paid_itc"))

    # -----------------------------------------------------------------------
    # Step 2 — Tax liability reconciliation
    # -----------------------------------------------------------------------
    gstr1_total_tax = gstr1_igst + gstr1_cgst + gstr1_sgst + gstr1_cess
    gstr3b_total_tax = gstr3b_igst + gstr3b_cgst + gstr3b_sgst + gstr3b_cess
    tax_gap = gstr3b_total_tax - gstr1_total_tax  # positive = over-payment in 3B

    tax_reconciliation = {
        "gstr1_igst": round(gstr1_igst, 2),
        "gstr1_cgst": round(gstr1_cgst, 2),
        "gstr1_sgst": round(gstr1_sgst, 2),
        "gstr1_cess": round(gstr1_cess, 2),
        "gstr1_total_tax": round(gstr1_total_tax, 2),
        "gstr3b_igst": round(gstr3b_igst, 2),
        "gstr3b_cgst": round(gstr3b_cgst, 2),
        "gstr3b_sgst": round(gstr3b_sgst, 2),
        "gstr3b_cess": round(gstr3b_cess, 2),
        "gstr3b_total_tax": round(gstr3b_total_tax, 2),
        "igst_diff": round(gstr3b_igst - gstr1_igst, 2),
        "cgst_diff": round(gstr3b_cgst - gstr1_cgst, 2),
        "sgst_diff": round(gstr3b_sgst - gstr1_sgst, 2),
        "cess_diff": round(gstr3b_cess - gstr1_cess, 2),
        "total_tax_gap": round(tax_gap, 2),
        "gap_interpretation": (
            "GSTR-3B shows higher tax paid (over-payment)" if tax_gap > 100
            else "GSTR-1 shows higher liability (under-declaration in 3B)" if tax_gap < -100
            else "Tax liability matches between GSTR-1 and GSTR-3B"
        ),
    }

    if abs(tax_gap) > 100:
        discrepancy_count += 1
        action_items.append({
            "priority": 1 if abs(tax_gap) > gstr1_total_tax * 0.05 else 2,
            "category": "TAX_MISMATCH",
            "description": (f"Annual tax gap: GSTR-1 Rs.{gstr1_total_tax:,.0f} vs "
                            f"GSTR-3B Rs.{gstr3b_total_tax:,.0f} (gap Rs.{tax_gap:,.0f})"),
            "financial_impact": abs(tax_gap),
            "recommendation": "Review tax type breakdowns — check IGST/CGST/SGST individually for mismatches.",
        })

    # -----------------------------------------------------------------------
    # Step 3 — Books vs Returns
    # -----------------------------------------------------------------------
    books_reconciliation = None
    if books_turnover is not None and books_turnover > 0:
        gstr1_total_with_exempt = gstr1_total_turnover + gstr1_total_exempt
        books_vs_gstr1 = books_turnover - gstr1_total_with_exempt
        books_vs_gstr3b = books_turnover - gstr3b_total_turnover

        books_reconciliation = {
            "books_turnover": round(books_turnover, 2),
            "gstr1_total_with_exempt": round(gstr1_total_with_exempt, 2),
            "gstr3b_total_turnover": round(gstr3b_total_turnover, 2),
            "books_vs_gstr1_diff": round(books_vs_gstr1, 2),
            "books_vs_gstr3b_diff": round(books_vs_gstr3b, 2),
            "books_vs_gstr1_severity": _severity(books_vs_gstr1, books_turnover),
            "books_vs_gstr3b_severity": _severity(books_vs_gstr3b, books_turnover),
        }

        if abs(books_vs_gstr1) > 1000 or (books_turnover > 0 and abs(books_vs_gstr1) / books_turnover > 0.01):
            discrepancy_count += 1
            action_items.append({
                "priority": 2,
                "category": "BOOKS_GAP",
                "description": (f"Books turnover Rs.{books_turnover:,.0f} vs GSTR-1 "
                                f"Rs.{gstr1_total_with_exempt:,.0f} (diff Rs.{books_vs_gstr1:,.0f})"),
                "financial_impact": abs(books_vs_gstr1),
                "recommendation": "Reconcile books with GSTR-1 — check for unbilled revenue, advances, or exemptions.",
            })

        if abs(books_vs_gstr3b) > 1000 or (books_turnover > 0 and abs(books_vs_gstr3b) / books_turnover > 0.01):
            discrepancy_count += 1
            action_items.append({
                "priority": 2,
                "category": "BOOKS_GAP",
                "description": (f"Books turnover Rs.{books_turnover:,.0f} vs GSTR-3B "
                                f"Rs.{gstr3b_total_turnover:,.0f} (diff Rs.{books_vs_gstr3b:,.0f})"),
                "financial_impact": abs(books_vs_gstr3b),
                "recommendation": "Reconcile books with GSTR-3B — check for timing differences or missed filings.",
            })

    # -----------------------------------------------------------------------
    # Step 4 — ITC reconciliation
    # -----------------------------------------------------------------------
    total_itc_claimed = itc_igst + itc_cgst + itc_sgst + itc_cess
    net_itc = total_itc_claimed - itc_reversed
    itc_turnover_ratio = (net_itc / gstr3b_total_turnover * 100) if gstr3b_total_turnover > 0 else 0

    itc_summary = {
        "itc_igst": round(itc_igst, 2),
        "itc_cgst": round(itc_cgst, 2),
        "itc_sgst": round(itc_sgst, 2),
        "itc_cess": round(itc_cess, 2),
        "total_itc_claimed": round(total_itc_claimed, 2),
        "itc_reversed": round(itc_reversed, 2),
        "net_itc": round(net_itc, 2),
        "itc_turnover_ratio_pct": round(itc_turnover_ratio, 2),
    }

    if itc_turnover_ratio > 100:
        discrepancy_count += 1
        action_items.append({
            "priority": 1,
            "category": "ITC_EXCESS",
            "description": (f"ITC-to-turnover ratio is {itc_turnover_ratio:.1f}% — "
                            f"Net ITC Rs.{net_itc:,.0f} exceeds total turnover Rs.{gstr3b_total_turnover:,.0f}"),
            "financial_impact": net_itc - gstr3b_total_turnover,
            "recommendation": "Review ITC claims — possible excess claim, duplicate entries, or incorrect turnover reporting.",
        })

    # -----------------------------------------------------------------------
    # Step 5 — GSTR-9 table-wise summary
    # -----------------------------------------------------------------------
    gstr9_tables = {
        "table_4": {
            "description": "Details of advances, inward and outward supplies on which tax is payable",
            "taxable_outward_supplies": round(gstr1_total_turnover, 2),
            "exempt_nil_rated": round(gstr1_total_exempt, 2),
            "total_turnover": round(gstr1_total_turnover + gstr1_total_exempt, 2),
        },
        "table_6": {
            "description": "Details of ITC availed during the financial year",
            "itc_igst": round(itc_igst, 2),
            "itc_cgst": round(itc_cgst, 2),
            "itc_sgst": round(itc_sgst, 2),
            "itc_cess": round(itc_cess, 2),
            "total_itc_availed": round(total_itc_claimed, 2),
            "itc_reversed": round(itc_reversed, 2),
            "net_itc": round(net_itc, 2),
        },
        "table_9": {
            "description": "Details of tax paid as declared in returns filed during the financial year",
            "tax_payable_igst": round(gstr3b_igst, 2),
            "tax_payable_cgst": round(gstr3b_cgst, 2),
            "tax_payable_sgst": round(gstr3b_sgst, 2),
            "tax_payable_cess": round(gstr3b_cess, 2),
            "total_tax_payable": round(gstr3b_total_tax, 2),
            "paid_through_cash": round(tax_paid_cash, 2),
            "paid_through_itc": round(tax_paid_itc, 2),
        },
    }

    # -----------------------------------------------------------------------
    # Step 6 — Action items (sort by financial_impact descending)
    # -----------------------------------------------------------------------
    action_items.sort(key=lambda x: x.get("financial_impact", 0), reverse=True)

    # Determine overall status
    total_turnover_diff = abs(gstr1_total_turnover - gstr3b_total_turnover)
    if discrepancy_count == 0:
        overall_status = "clean"
    elif discrepancy_count <= 2 and total_turnover_diff < gstr1_total_turnover * 0.01:
        overall_status = "minor_issues"
    elif discrepancy_count <= 5:
        overall_status = "needs_attention"
    else:
        overall_status = "critical"

    summary = {
        "fy": gstr1_months[0].get("fy", "") if gstr1_months else "",
        "gstin": gstr1_months[0].get("gstin", "") if gstr1_months else "",
        "gstr1_total_turnover": round(gstr1_total_turnover, 2),
        "gstr3b_total_turnover": round(gstr3b_total_turnover, 2),
        "turnover_diff": round(gstr1_total_turnover - gstr3b_total_turnover, 2),
        "gstr1_total_tax": round(gstr1_total_tax, 2),
        "gstr3b_total_tax": round(gstr3b_total_tax, 2),
        "tax_diff": round(tax_gap, 2),
        "discrepancy_count": discrepancy_count,
        "months_in_gstr1": len(gstr1_months),
        "months_in_gstr3b": len(gstr3b_months),
        "status": overall_status,
    }

    return {
        "summary": summary,
        "monthly_comparison": monthly_comparison,
        "tax_reconciliation": tax_reconciliation,
        "books_reconciliation": books_reconciliation,
        "itc_summary": itc_summary,
        "gstr9_tables": gstr9_tables,
        "action_items": action_items,
    }
