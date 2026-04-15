"""Extract counterparty identifiers from bank statement descriptions.

Handles the common narration patterns used by Indian banks:

    NEFT-SBIN0001234-RAJESH KUMAR-ABCD1234
    RTGS/HDFC0000001/ACME TRADERS/INV-12
    IMPS/P2A/1234567890/PRIYA S/HDFC/SELF
    UPI/123456789/swiggy@ybl/PYTM
    ATM-CASH WDL-1234 HDFC BANK MG ROAD
    CHQ 000123 PAID TO ABC ENTERPRISES

Returns a normalized {name, type, handle?, ifsc?} dict. Name is the best
guess at the counterparty (for grouping in round-trip detection / top-N
lists) and will be blank when we cannot confidently extract one.
"""

from __future__ import annotations

import re

_NEFT_RE = re.compile(r"\bNEFT[-/\s]+([A-Z]{4}0[A-Z0-9]{6})[-/\s]+([^/\-]+?)(?:[-/]|$)", re.I)
_RTGS_RE = re.compile(r"\bRTGS[-/\s]+([A-Z]{4}0[A-Z0-9]{6})[-/\s]+([^/\-]+?)(?:[-/]|$)", re.I)
_IMPS_RE = re.compile(r"\bIMPS[-/\s]+(?:P2[AM]/)?\d+[-/\s]+([^/\-]+?)(?:[-/]|$)", re.I)
_UPI_HANDLE_RE = re.compile(r"([a-zA-Z0-9._-]+@[a-zA-Z0-9]+)")
_UPI_NAME_RE = re.compile(r"\bUPI[-/\s]+(?:\d+[-/\s]+)?([A-Za-z][A-Za-z0-9 \.]+?)[-/\s]", re.I)
_UPI_PREFIX_RE = re.compile(r"\bUPI\b", re.I)
_CHQ_RE = re.compile(r"\bCHQ(?:UE)?[-\s\.]*(?:NO[-\s\.]*)?(\d+)[-\s/]+(?:PAID[-\s]*TO[-\s]+)?([A-Z][A-Z0-9 &.\-]+)", re.I)
_ATM_RE = re.compile(r"\bATM[-/\s]+(?:CASH[-/\s]*(?:WDL|WITHDRAWAL)[-/\s]+)?(?:\d+\s+)?([A-Z][A-Z0-9 &\-]+)", re.I)
_NACH_RE = re.compile(r"\bNACH[-/\s]+[A-Z0-9]+[-/\s]+([A-Z][A-Z0-9 &\-]+)", re.I)


def _clean(name: str) -> str:
    """Strip junk, collapse whitespace, uppercase for normalisation."""
    if not name:
        return ""
    name = re.sub(r"\s+", " ", name).strip(" -/.")
    # Drop trailing reference numbers
    name = re.sub(r"[-/]\s*[A-Z0-9]{6,}$", "", name).strip()
    return name.upper()


def extract_counterparty(description: str) -> dict:
    """Return {name, type, handle?, ifsc?, raw} for a transaction description.

    `type` ∈ {NEFT, RTGS, IMPS, UPI, CHEQUE, ATM, NACH, UNKNOWN}. `name` is
    empty string when no confident match.
    """
    desc = description or ""

    m = _NEFT_RE.search(desc)
    if m:
        return {"name": _clean(m.group(2)), "type": "NEFT", "ifsc": m.group(1).upper(), "raw": desc}

    m = _RTGS_RE.search(desc)
    if m:
        return {"name": _clean(m.group(2)), "type": "RTGS", "ifsc": m.group(1).upper(), "raw": desc}

    m = _IMPS_RE.search(desc)
    if m:
        return {"name": _clean(m.group(1)), "type": "IMPS", "raw": desc}

    # UPI: look for a handle first, then the name token after UPI/.../
    handle_match = _UPI_HANDLE_RE.search(desc)
    if handle_match:
        handle = handle_match.group(1)
        name_match = _UPI_NAME_RE.search(desc)
        name = _clean(name_match.group(1)) if name_match else _clean(handle.split("@")[0])
        return {"name": name, "type": "UPI", "handle": handle, "raw": desc}

    # UPI without handle — fall back to "UPI-<id>-<name>" style
    if _UPI_PREFIX_RE.search(desc):
        name_match = _UPI_NAME_RE.search(desc)
        if name_match:
            return {"name": _clean(name_match.group(1)), "type": "UPI", "raw": desc}

    m = _CHQ_RE.search(desc)
    if m:
        return {"name": _clean(m.group(2)), "type": "CHEQUE", "cheque_no": m.group(1), "raw": desc}

    m = _NACH_RE.search(desc)
    if m:
        return {"name": _clean(m.group(1)), "type": "NACH", "raw": desc}

    m = _ATM_RE.search(desc)
    if m:
        return {"name": _clean(m.group(1)), "type": "ATM", "raw": desc}

    return {"name": "", "type": "UNKNOWN", "raw": desc}
