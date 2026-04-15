"""Higher-order detectors layered on top of the deterministic flag rules.

These run after transactions have been enriched with category + counterparty
and produce CA-focused hints:

- STRUCTURING_SUSPECTED    — multiple cash withdrawals just below 10K same day
- ROUND_TRIP_SUSPECTED     — same counterparty appears debit↔credit within 7d
- TDS_NOT_DEDUCTED_HINT    — interest credits cross §194A threshold
- HIGH_VALUE_NON_WORKING_DAY — >1L txn on Sunday / 2nd/4th Sat / holiday
- MONTHLY_SPIKE            — monthly debit > 2× trailing-3-month avg
- PERSONAL_IN_BUSINESS_HINT — PERSONAL category found (CA to confirm nature)
- DRAWINGS_EXCESS_HINT     — PERSONAL > 30% of total debits (proprietorship hint)
- GST_REMITTANCE_VISIBLE   — GST payment observed; cross-check with GST recon
- ADVANCE_TAX_PAID         — TAX payment observed; cross-check Schedule IT

None of these are hard violations — they are review prompts for the CA. The
`severity` field reflects this: HIGH = likely regulatory exposure, MEDIUM =
meaningful anomaly worth checking, LOW = informational.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable

from services.bank_enrichment.holidays import is_non_working_day


_DATE_FORMATS = (
    "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y",
    "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y",
)


def _parse_date(val) -> date | None:
    if not val:
        return None
    if isinstance(val, date):
        return val
    s = str(val).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _flag(category: str, severity: str, section: str, description: str, **kwargs) -> dict:
    out = {
        "category": category,
        "severity": severity,
        "section": section,
        "description": description,
    }
    out.update(kwargs)
    return out


def detect_structuring(transactions: list[dict]) -> list[dict]:
    """≥3 cash debits between 9,000 and 9,999 on the same day → structuring suspect."""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for txn in transactions:
        debit = float(txn.get("debit") or 0)
        if 9_000 <= debit <= 9_999.99:
            category = txn.get("category", "")
            if category == "CASH_MOVEMENT" or "CASH" in (txn.get("description") or "").upper():
                buckets[txn.get("date") or ""].append(txn)

    flags: list[dict] = []
    for day, rows in buckets.items():
        if len(rows) >= 3:
            total = sum(float(r.get("debit") or 0) for r in rows)
            flags.append(_flag(
                "STRUCTURING_SUSPECTED",
                "HIGH",
                "Prevention of Money Laundering Act / Rule 114E",
                f"{len(rows)} cash withdrawals of Rs.9,000–9,999 on {day} totalling Rs.{total:,.2f} — pattern suggests structuring to avoid reporting thresholds.",
                amount=total,
                date=day,
                transaction=f"{len(rows)} txns",
            ))
    return flags


def detect_round_trip(transactions: list[dict]) -> list[dict]:
    """Same counterparty appears as both debit and credit within 7 days.

    We use the enriched `counterparty.name`; UNKNOWN counterparties are
    skipped to avoid false positives.
    """
    debits: dict[str, list[tuple[date, float, dict]]] = defaultdict(list)
    credits: dict[str, list[tuple[date, float, dict]]] = defaultdict(list)

    for txn in transactions:
        cp = (txn.get("counterparty") or {})
        name = (cp.get("name") or "").strip()
        if not name:
            continue
        d = _parse_date(txn.get("date"))
        if not d:
            continue
        debit = float(txn.get("debit") or 0)
        credit = float(txn.get("credit") or 0)
        if debit > 0:
            debits[name].append((d, debit, txn))
        if credit > 0:
            credits[name].append((d, credit, txn))

    flags: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for name in debits:
        if name not in credits:
            continue
        for d1, amt1, t1 in debits[name]:
            for d2, amt2, t2 in credits[name]:
                if abs((d1 - d2).days) <= 7 and amt1 > 10_000:
                    # within 5% tolerance
                    if abs(amt1 - amt2) / max(amt1, amt2) <= 0.05:
                        key = (name, t1.get("date", ""), t2.get("date", ""))
                        if key in seen:
                            continue
                        seen.add(key)
                        flags.append(_flag(
                            "ROUND_TRIP_SUSPECTED",
                            "MEDIUM",
                            "Observation",
                            f"Possible round-trip with {name}: debit Rs.{amt1:,.2f} on {t1.get('date')} and credit Rs.{amt2:,.2f} on {t2.get('date')}.",
                            amount=amt1,
                            date=t1.get("date"),
                            transaction=name[:100],
                        ))
    return flags


def detect_tds_hint(transactions: list[dict], interest_total: float) -> list[dict]:
    """If aggregate interest income > 40K, hint that bank should have deducted TDS.

    This is a HINT for the CA to cross-check Form 26AS — we cannot verify
    TDS deduction from the statement alone. §194A threshold is 40K for
    non-senior citizens, 50K for senior citizens.
    """
    if interest_total <= 40_000:
        return []
    return [_flag(
        "TDS_NOT_DEDUCTED_HINT",
        "MEDIUM",
        "Section 194A",
        f"Aggregate interest income Rs.{interest_total:,.2f} exceeds Rs.40,000 §194A threshold — verify TDS deduction in Form 26AS.",
        amount=interest_total,
        date=None,
        transaction="Aggregate interest income",
    )]


def detect_non_working_day_high_value(transactions: list[dict]) -> list[dict]:
    """Any debit or credit > 1L on a Sunday / 2nd-4th Sat / declared holiday."""
    flags: list[dict] = []
    for txn in transactions:
        d = _parse_date(txn.get("date"))
        if not d or not is_non_working_day(d):
            continue
        amount = max(float(txn.get("debit") or 0), float(txn.get("credit") or 0))
        if amount < 1_00_000:
            continue
        flags.append(_flag(
            "HIGH_VALUE_NON_WORKING_DAY",
            "MEDIUM",
            "Observation",
            f"High-value transaction of Rs.{amount:,.2f} on a non-working day ({d.strftime('%A, %d-%b-%Y')}).",
            amount=amount,
            date=txn.get("date"),
            transaction=(txn.get("description") or "")[:100],
        ))
    return flags


def detect_monthly_spike(monthly_summary: dict) -> list[dict]:
    """Any month where total debit > 2× trailing-3-month avg."""
    if len(monthly_summary) < 4:
        return []
    sorted_months = sorted(monthly_summary.keys())
    flags: list[dict] = []
    for i in range(3, len(sorted_months)):
        window = sorted_months[i - 3:i]
        current = sorted_months[i]
        window_avg = sum(monthly_summary[m]["debit"] for m in window) / 3.0
        current_debit = monthly_summary[current]["debit"]
        if window_avg > 0 and current_debit > 2 * window_avg:
            flags.append(_flag(
                "MONTHLY_SPIKE",
                "LOW",
                "Trend Analysis",
                f"{current} total debit Rs.{current_debit:,.2f} is {current_debit / window_avg:.1f}× the trailing 3-month average of Rs.{window_avg:,.2f}.",
                amount=current_debit,
                date=f"{current}-01",
                transaction=f"Month {current}",
            ))
    return flags


def detect_personal_hints(transactions: list[dict], total_debit: float) -> list[dict]:
    """Flag presence of PERSONAL_EXPENSE and whether it dominates (drawings hint)."""
    personal = [t for t in transactions if t.get("category") == "PERSONAL_EXPENSE"]
    if not personal:
        return []

    personal_total = sum(float(t.get("debit") or 0) for t in personal)
    flags: list[dict] = []

    flags.append(_flag(
        "PERSONAL_IN_BUSINESS_HINT",
        "LOW",
        "Books of Account",
        f"{len(personal)} personal-expense-pattern transactions totalling Rs.{personal_total:,.2f} observed — if this is a business account, reclassify to drawings / disallow in P&L.",
        amount=personal_total,
        date=None,
        transaction=f"{len(personal)} txns",
    ))

    if total_debit > 0 and personal_total / total_debit > 0.30:
        flags.append(_flag(
            "DRAWINGS_EXCESS_HINT",
            "MEDIUM",
            "Books of Account",
            f"Personal-pattern transactions are {personal_total / total_debit * 100:.1f}% of total debits — for a proprietorship this may warrant review of drawings vs business expense classification.",
            amount=personal_total,
            date=None,
            transaction="Drawings review",
        ))
    return flags


def detect_cross_reference_hints(transactions: list[dict]) -> list[dict]:
    """Surface GST / advance tax payments so the CA can reconcile with other filings."""
    flags: list[dict] = []

    gst_total = sum(float(t.get("debit") or 0) for t in transactions if t.get("category") == "GST_PAYMENT")
    if gst_total > 0:
        flags.append(_flag(
            "GST_REMITTANCE_VISIBLE",
            "LOW",
            "Cross-Reference",
            f"GST payments totalling Rs.{gst_total:,.2f} observed in the statement — cross-check with GSTR-3B cash ledger and PMT-06 challans.",
            amount=gst_total,
            date=None,
            transaction="GST challans",
        ))

    tax_total = sum(float(t.get("debit") or 0) for t in transactions if t.get("category") == "TAX_PAYMENT")
    if tax_total > 0:
        flags.append(_flag(
            "ADVANCE_TAX_PAID",
            "LOW",
            "Cross-Reference",
            f"Income-tax payments totalling Rs.{tax_total:,.2f} observed — cross-check with Schedule IT of the ITR and Form 26AS tax-paid section.",
            amount=tax_total,
            date=None,
            transaction="IT challans",
        ))

    tds_total = sum(float(t.get("debit") or 0) for t in transactions if t.get("category") == "TDS_PAYMENT")
    if tds_total > 0:
        flags.append(_flag(
            "TDS_REMITTANCE_VISIBLE",
            "LOW",
            "Cross-Reference",
            f"TDS/TCS payments totalling Rs.{tds_total:,.2f} observed — cross-check with Form 24Q/26Q and TRACES.",
            amount=tds_total,
            date=None,
            transaction="TDS challans",
        ))
    return flags


def run_detectors(
    transactions: list[dict],
    monthly_summary: dict,
    interest_total: float,
    total_debit: float,
) -> list[dict]:
    """Run all enrichment detectors and return their combined flag list."""
    flags: list[dict] = []
    flags.extend(detect_structuring(transactions))
    flags.extend(detect_round_trip(transactions))
    flags.extend(detect_tds_hint(transactions, interest_total))
    flags.extend(detect_non_working_day_high_value(transactions))
    flags.extend(detect_monthly_spike(monthly_summary))
    flags.extend(detect_personal_hints(transactions, total_debit))
    flags.extend(detect_cross_reference_hints(transactions))
    return flags
