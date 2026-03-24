"""Bank Statement Analyzer — extract transactions from text, flag against statutory thresholds."""

import json
import logging
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)

# Regex: lines that start with a date like DD/MM/YYYY or DD-MM-YYYY
_DATE_LINE_RE = re.compile(
    r"^(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4})\s*$"
)
# Indian-format amount: digits with commas like 1,50,000.00 or plain 45000.00
_AMOUNT_RE = re.compile(r"^[\d,]+\.\d{2}$")

# ---------------------------------------------------------------------------
# Mode inference keywords
# ---------------------------------------------------------------------------
_MODE_KEYWORDS = {
    "NEFT": ["NEFT", "NATIONAL ELECTRONIC"],
    "RTGS": ["RTGS"],
    "IMPS": ["IMPS"],
    "UPI": ["UPI", "UNIFIED PAYMENT"],
    "CHEQUE": ["CHQ", "CHEQUE", "CLG", "CLEARING"],
    "ATM": ["ATM", "CASH WDL", "CASH WITHDRAWAL"],
    "AUTO_DEBIT": ["AUTO DEBIT", "SI DEBIT", "NACH", "ECS", "MANDATE"],
    "INTEREST": ["INTEREST", "INT."],
    "CASH_DEPOSIT": ["CASH DEP", "CASH DEPOSIT", "BY CASH", "CASH CR"],
}


def _infer_mode(description: str) -> str:
    """Infer transaction mode from description keywords."""
    upper = (description or "").upper()
    for mode, keywords in _MODE_KEYWORDS.items():
        for kw in keywords:
            if kw in upper:
                return mode
    return "OTHER"


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


def _parse_date(val) -> date | None:
    """Parse a date string into a date object."""
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%b-%Y", "%d %b %Y",
                "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Column aliases for flexible header matching
# ---------------------------------------------------------------------------
_DATE_ALIASES = {"date", "txn date", "transaction date", "value date",
                 "posting date", "txn_date", "trans date", "trans_date"}
_DESC_ALIASES = {"description", "narration", "particulars", "remarks",
                 "details", "transaction description", "narration/description"}
_DEBIT_ALIASES = {"debit", "withdrawal", "debit amount", "dr", "withdrawals",
                  "debit(dr)", "dr amount", "debit amt"}
_CREDIT_ALIASES = {"credit", "deposit", "credit amount", "cr", "deposits",
                   "credit(cr)", "cr amount", "credit amt"}
_BALANCE_ALIASES = {"balance", "closing balance", "running balance",
                    "available balance", "bal", "closing bal"}
_MODE_ALIASES = {"mode", "type", "transaction type", "txn type", "channel"}


def _get_field(row: dict, aliases: set):
    """Find a field value by checking against alias set (case-insensitive)."""
    keys_lower = {k.lower().strip(): k for k in row.keys()}
    for alias in aliases:
        if alias in keys_lower:
            return row[keys_lower[alias]]
    return None


class BankStatementService:
    """Extract transactions from bank statement text and flag statutory risks."""

    def extract_transactions(self, raw_text: str) -> list[dict]:
        """Extract transactions from bank statement text using direct text parsing.

        PyMuPDF extracts table cells as separate lines. We detect date lines,
        then collect subsequent non-date, non-amount lines as the description,
        and amount lines as debit/credit/balance values.
        """
        # Step 1: Try direct text parsing (no LLM needed)
        transactions = self._parse_text_direct(raw_text)
        if transactions:
            logger.info(f"BankStatementService: Direct parser extracted {len(transactions)} transactions")
            return transactions

        # Step 2: Fallback to LLM-based extraction if direct parsing yields nothing
        logger.info("BankStatementService: Direct parsing found 0 transactions, trying LLM fallback")
        try:
            from services.document_parser import DocumentParser
            parsed = DocumentParser().parse_document(raw_text)
            if parsed:
                transactions = self._extract_from_parsed(parsed)
                if transactions:
                    logger.info(f"BankStatementService: LLM fallback extracted {len(transactions)} transactions")
                    return transactions
        except Exception as e:
            logger.warning(f"BankStatementService: LLM fallback failed: {e}")

        return []

    def _parse_text_direct(self, raw_text: str) -> list[dict]:
        """Parse bank statement text line-by-line without LLM.

        Strategy: Scan lines for date patterns. Once a date is found, collect
        subsequent lines as description (text) and amounts (numeric) until the
        next date line. Amounts are assigned as debit, credit, balance based
        on position (bank statements typically list them in that order).
        """
        lines = [l.strip() for l in raw_text.split("\n") if l.strip()]

        # First, detect and skip header lines (column names)
        header_keywords = {
            "date", "narration", "description", "particulars", "debit",
            "credit", "balance", "withdrawal", "deposit", "chq", "ref",
        }

        transactions = []
        i = 0
        while i < len(lines):
            line = lines[i]

            # Skip header-like lines
            if line.lower() in header_keywords or all(
                w.lower() in header_keywords for w in line.split()
                if len(w) > 2
            ):
                i += 1
                continue

            # Look for a date line
            dt = _parse_date(line)
            if dt is None:
                i += 1
                continue

            # Found a date — collect subsequent lines until next date
            i += 1
            desc_parts = []
            amounts = []

            while i < len(lines):
                next_line = lines[i]
                # If next line is a date, stop
                if _parse_date(next_line) is not None:
                    break
                # If it's an amount
                cleaned = next_line.replace(",", "").replace(" ", "")
                if _AMOUNT_RE.match(next_line) or (
                    cleaned.replace(".", "", 1).isdigit() and "." in cleaned
                ):
                    amounts.append(_parse_float(next_line))
                elif next_line.lower() not in header_keywords:
                    # It's a description or ref number line
                    # Skip very short lines that look like ref numbers only if we already have description
                    desc_parts.append(next_line)
                i += 1

            # Build transaction from collected data
            # Filter desc_parts: remove footer/disclaimer text
            desc_parts = [
                p for p in desc_parts
                if not any(skip in p.lower() for skip in [
                    "computer-generated", "does not require", "discrepancy",
                    "report any", "within 15 days",
                ])
            ]
            description = " ".join(desc_parts).strip()
            if not amounts:
                continue

            # Skip "OPENING BALANCE" rows — they have only a balance, not a real transaction
            if "OPENING BALANCE" in description.upper() and len(amounts) == 1:
                continue

            # Determine debit/credit/balance from amounts
            # Bank statements typically have: [debit_or_empty, credit_or_empty, balance]
            # Since empty cells don't appear in text, we use position heuristics:
            # - If 1 amount: could be debit or credit (check description for clues)
            # - If 2 amounts: first is debit or credit, second is balance
            # - If 3+ amounts: first=debit, second=credit, third=balance (or debit, balance)
            debit = 0.0
            credit = 0.0
            balance = 0.0

            if len(amounts) == 1:
                # Single amount — use description to guess debit vs credit
                if self._looks_like_credit(description):
                    credit = amounts[0]
                else:
                    debit = amounts[0]
            elif len(amounts) == 2:
                # Two amounts: first is the transaction amount, second is running balance
                balance = amounts[1]
                if self._looks_like_credit(description):
                    credit = amounts[0]
                else:
                    debit = amounts[0]
            else:
                # 3+ amounts — assign positionally
                if self._looks_like_credit(description):
                    credit = amounts[0]
                else:
                    debit = amounts[0]
                balance = amounts[-1]

            if debit == 0.0 and credit == 0.0:
                continue

            mode = _infer_mode(description)
            transactions.append({
                "date": dt.isoformat(),
                "description": description,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "mode": mode,
            })

        return transactions

    def _looks_like_credit(self, description: str) -> bool:
        """Heuristic: does the description suggest an incoming/credit transaction?"""
        upper = (description or "").upper()
        # Check debit keywords FIRST — they take priority when description is ambiguous
        debit_keywords = [
            "ATM", "CASH WDL", "CASH WITHDRAWAL", "PAID", "CHQ PAID",
            "EMI", "AUTO DEBIT", "NACH", "ECS", "SI DEBIT",
            "INSURANCE", "PREMIUM", "ADVANCE", "RENT", "ELECTRICITY",
            "CONTRACTOR", "SUPPLIER", "PROPERTY", "GST PAYMENT",
            "STAFF SALARY", "SIP", "MUTUAL FUND", "TAX",
        ]
        credit_keywords = [
            "BY CASH", "CASH DEP", "CASH DEPOSIT", "CASH CR",
            "INTEREST CREDITED", "INTEREST", "INT.",
            "CAPITAL INFUSION", "RECEIVED", "REFUND",
            "CUSTOMER PAYMENT", "CLIENT PAYMENT", "SHOP COLLECTION",
            "FY CLOSING", "NEFT CR", "DEPOSIT",
        ]
        for kw in debit_keywords:
            if kw in upper:
                return False
        for kw in credit_keywords:
            if kw in upper:
                return True
        return False

    def _extract_from_parsed(self, parsed: dict) -> list[dict]:
        """Extract transactions from LLM-parsed document structure (fallback)."""
        transactions = []
        tables = parsed.get("tables", [])
        for table in tables:
            headers = table.get("header", [])
            rows = table.get("rows", [])
            for row_data in rows:
                if isinstance(row_data, list):
                    row = {headers[i]: row_data[i] for i in range(min(len(headers), len(row_data)))}
                elif isinstance(row_data, dict):
                    row = row_data
                else:
                    continue
                txn = self._row_to_transaction(row)
                if txn:
                    transactions.append(txn)
        for item in parsed.get("line_items", []):
            txn = self._row_to_transaction(item)
            if txn:
                transactions.append(txn)
        return transactions

    def _row_to_transaction(self, row: dict) -> dict | None:
        """Convert a row dict to a standardized transaction dict."""
        desc = str(_get_field(row, _DESC_ALIASES) or "").strip()
        debit = _parse_float(_get_field(row, _DEBIT_ALIASES))
        credit = _parse_float(_get_field(row, _CREDIT_ALIASES))
        balance = _parse_float(_get_field(row, _BALANCE_ALIASES))
        txn_date = _parse_date(_get_field(row, _DATE_ALIASES))

        # Skip rows with no amounts at all
        if debit == 0.0 and credit == 0.0:
            return None

        mode = str(_get_field(row, _MODE_ALIASES) or "").upper().strip()
        if not mode or mode == "NONE":
            mode = _infer_mode(desc)

        return {
            "date": txn_date.isoformat() if txn_date else None,
            "description": desc,
            "debit": round(debit, 2),
            "credit": round(credit, 2),
            "balance": round(balance, 2),
            "mode": mode,
        }

    def analyze(self, transactions: list[dict], fy_start: date, fy_end: date) -> dict:
        """Run deterministic statutory threshold checks on extracted transactions.

        Pure Python arithmetic — no LLM, no compliance judgments.
        """
        flags: list[dict] = []
        total_debit = 0.0
        total_credit = 0.0
        cash_debit_total = 0.0
        cash_credit_total = 0.0
        interest_total = 0.0
        txn_count = 0

        # For aggregate same-payee-same-day check
        # key: (date, description_normalized) -> total debit
        payee_day_debits: dict[tuple, float] = {}

        for txn in transactions:
            txn_date = _parse_date(txn.get("date"))
            debit = _parse_float(txn.get("debit"))
            credit = _parse_float(txn.get("credit"))
            mode = (txn.get("mode") or "OTHER").upper()
            desc = txn.get("description", "")
            amount = max(debit, credit)

            txn_count += 1
            total_debit += debit
            total_credit += credit

            is_cash_debit = mode in ("ATM", "CASH_DEPOSIT") or "CASH" in desc.upper()
            is_cash_credit = mode == "CASH_DEPOSIT" or "CASH DEP" in desc.upper() or "BY CASH" in desc.upper()
            is_interest = mode == "INTEREST"

            if is_cash_debit:
                cash_debit_total += debit
            if is_cash_credit:
                cash_credit_total += credit
            if is_interest:
                interest_total += credit

            # --- Flag 1: Sec 40A(3) — single cash debit > 10,000 ---
            if is_cash_debit and debit > 10_000:
                flags.append({
                    "category": "SEC_40A3_RISK",
                    "severity": "HIGH",
                    "section": "Section 40A(3)",
                    "description": f"Cash payment of Rs.{debit:,.2f} exceeds Rs.10,000 single-transaction limit",
                    "amount": debit,
                    "date": txn.get("date"),
                    "transaction": desc[:100],
                })

            # --- Flag 3: Sec 269ST — cash credit >= 2,00,000 ---
            if is_cash_credit and credit >= 2_00_000:
                flags.append({
                    "category": "SEC_269ST_VIOLATION",
                    "severity": "HIGH",
                    "section": "Section 269ST",
                    "description": f"Cash receipt of Rs.{credit:,.2f} exceeds Rs.2,00,000 limit",
                    "amount": credit,
                    "date": txn.get("date"),
                    "transaction": desc[:100],
                })
            # --- Flag 4: Sec 269ST warning — cash credit >= 1,00,000 ---
            elif is_cash_credit and credit >= 1_00_000:
                flags.append({
                    "category": "SEC_269ST_WARNING",
                    "severity": "MEDIUM",
                    "section": "Section 269ST",
                    "description": f"Cash receipt of Rs.{credit:,.2f} approaching Rs.2,00,000 limit",
                    "amount": credit,
                    "date": txn.get("date"),
                    "transaction": desc[:100],
                })

            # --- Flag 7: Round amount observation ---
            if amount >= 1_00_000 and amount % 50_000 == 0:
                flags.append({
                    "category": "ROUND_AMOUNT_OBSERVATION",
                    "severity": "LOW",
                    "section": "Observation",
                    "description": f"Round amount Rs.{amount:,.2f} (divisible by 50,000)",
                    "amount": amount,
                    "date": txn.get("date"),
                    "transaction": desc[:100],
                })

            # --- Flag 8: Sunday transaction ---
            if txn_date and txn_date.weekday() == 6:  # Sunday
                flags.append({
                    "category": "SUNDAY_TRANSACTION",
                    "severity": "LOW",
                    "section": "Observation",
                    "description": f"Transaction on Sunday ({txn_date.strftime('%d-%b-%Y')})",
                    "amount": amount,
                    "date": txn.get("date"),
                    "transaction": desc[:100],
                })

            # Aggregate for same-payee-same-day check
            if is_cash_debit and debit > 0 and txn.get("date"):
                norm_desc = re.sub(r'\s+', ' ', desc.upper().strip())[:50]
                key = (txn.get("date"), norm_desc)
                payee_day_debits[key] = payee_day_debits.get(key, 0.0) + debit

        # --- Flag 2: Sec 40A(3) aggregate — same payee same day > 10,000 ---
        for (day, payee), total in payee_day_debits.items():
            if total > 10_000:
                # Only flag if it's from multiple transactions (single already flagged above)
                flags.append({
                    "category": "SEC_40A3_AGGREGATE",
                    "severity": "MEDIUM",
                    "section": "Section 40A(3)",
                    "description": f"Aggregate cash payments to same payee on {day}: Rs.{total:,.2f} exceeds Rs.10,000",
                    "amount": total,
                    "date": day,
                    "transaction": payee[:100],
                })

        # --- Flag 5: SFT thresholds — FY cash totals ---
        if cash_debit_total >= 10_00_000:
            flags.append({
                "category": "SFT_CASH_WITHDRAWAL",
                "severity": "HIGH",
                "section": "SFT Reporting",
                "description": f"FY total cash withdrawals Rs.{cash_debit_total:,.2f} >= Rs.10,00,000 — SFT reportable",
                "amount": cash_debit_total,
                "date": None,
                "transaction": "Aggregate FY cash withdrawals",
            })
        elif cash_debit_total >= 5_00_000:
            flags.append({
                "category": "SFT_CASH_WITHDRAWAL_WARNING",
                "severity": "MEDIUM",
                "section": "SFT Reporting",
                "description": f"FY total cash withdrawals Rs.{cash_debit_total:,.2f} approaching SFT threshold of Rs.10,00,000",
                "amount": cash_debit_total,
                "date": None,
                "transaction": "Aggregate FY cash withdrawals",
            })

        if cash_credit_total >= 10_00_000:
            flags.append({
                "category": "SFT_CASH_DEPOSIT",
                "severity": "HIGH",
                "section": "SFT Reporting",
                "description": f"FY total cash deposits Rs.{cash_credit_total:,.2f} >= Rs.10,00,000 — SFT reportable",
                "amount": cash_credit_total,
                "date": None,
                "transaction": "Aggregate FY cash deposits",
            })
        elif cash_credit_total >= 5_00_000:
            flags.append({
                "category": "SFT_CASH_DEPOSIT_WARNING",
                "severity": "MEDIUM",
                "section": "SFT Reporting",
                "description": f"FY total cash deposits Rs.{cash_credit_total:,.2f} approaching SFT threshold of Rs.10,00,000",
                "amount": cash_credit_total,
                "date": None,
                "transaction": "Aggregate FY cash deposits",
            })

        # --- Flag 6: Interest 194A threshold ---
        if interest_total > 40_000:
            flags.append({
                "category": "INTEREST_194A_THRESHOLD",
                "severity": "MEDIUM",
                "section": "Section 194A",
                "description": f"FY interest income Rs.{interest_total:,.2f} exceeds Rs.40,000 TDS threshold",
                "amount": interest_total,
                "date": None,
                "transaction": "Aggregate interest income",
            })

        # Sort flags: HIGH first, then MEDIUM, then LOW
        severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        flags.sort(key=lambda f: severity_order.get(f["severity"], 9))

        summary = {
            "total_transactions": txn_count,
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "cash_debit_total": round(cash_debit_total, 2),
            "cash_credit_total": round(cash_credit_total, 2),
            "interest_total": round(interest_total, 2),
            "fy_period": f"{fy_start.isoformat()} to {fy_end.isoformat()}",
            "flags_count": len(flags),
            "high_flags": sum(1 for f in flags if f["severity"] == "HIGH"),
            "medium_flags": sum(1 for f in flags if f["severity"] == "MEDIUM"),
            "low_flags": sum(1 for f in flags if f["severity"] == "LOW"),
        }

        return {
            "summary": summary,
            "flags": flags,
            "transactions": transactions,
        }
