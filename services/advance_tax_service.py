"""Advance Tax & Section 234 Interest Calculator — pure arithmetic, no LLM."""

import logging
import math
from datetime import date, datetime

logger = logging.getLogger(__name__)

# Advance tax instalment schedule per Section 211 of IT Act
ADVANCE_TAX_SCHEDULE = {
    "15_jun": {"cumulative_pct": 0.15, "label": "Q1 (Jun 15)", "month": 6, "day": 15},
    "15_sep": {"cumulative_pct": 0.45, "label": "Q2 (Sep 15)", "month": 9, "day": 15},
    "15_dec": {"cumulative_pct": 0.75, "label": "Q3 (Dec 15)", "month": 12, "day": 15},
    "15_mar": {"cumulative_pct": 1.00, "label": "Q4 (Mar 15)", "month": 3, "day": 15},
}


def _parse_date(val) -> date | None:
    """Parse YYYY-MM-DD string to date."""
    if not val:
        return None
    s = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _months_between(d1: date, d2: date) -> int:
    """Ceiling of month difference between d1 and d2 (d2 > d1). Minimum 0."""
    if d2 <= d1:
        return 0
    months = (d2.year - d1.year) * 12 + (d2.month - d1.month)
    if d2.day > d1.day:
        months += 1
    return max(months, 0)


def _build_due_date(start_year: int, month: int, day: int) -> date:
    """Build instalment due date from FY start year."""
    # Jun, Sep, Dec fall in start_year; Mar falls in start_year + 1
    year = start_year if month >= 4 else start_year + 1
    return date(year, month, day)


class AdvanceTaxService:
    """Compute Section 234A/B/C interest on advance tax instalments."""

    def compute_234c_interest(
        self,
        estimated_tax: float,
        fy: str,
        instalments_paid: list[dict],
        itr_filing_date: str | None = None,
        itr_due_date: str | None = None,
    ) -> dict:
        """Full 234A/B/C interest computation.

        Args:
            estimated_tax: Total estimated tax liability for the FY.
            fy: Financial year string e.g. "2025-26".
            instalments_paid: List of dicts with due_date, paid_amount, paid_date.
            itr_filing_date: Optional ITR filing date (YYYY-MM-DD).
            itr_due_date: Optional ITR due date (default: July 31 of AY).
        """
        start_year = int(fy[:4])
        ay_year = start_year + 1  # Assessment Year

        # Parse all payment entries
        payments = []
        for inst in instalments_paid:
            pd = _parse_date(inst.get("paid_date"))
            payments.append({
                "due_date_str": inst.get("due_date", ""),
                "paid_amount": float(inst.get("paid_amount", 0)),
                "paid_date": pd,
            })

        # --- Section 234C: Per-instalment interest ---
        instalment_results = []
        total_234c = 0.0

        for key, schedule in ADVANCE_TAX_SCHEDULE.items():
            due_dt = _build_due_date(start_year, schedule["month"], schedule["day"])
            required_cumulative = round(estimated_tax * schedule["cumulative_pct"], 2)

            # Sum all payments made on or before the due date
            actual_cumulative = sum(
                p["paid_amount"] for p in payments
                if p["paid_date"] and p["paid_date"] <= due_dt
            )
            actual_cumulative = round(actual_cumulative, 2)

            # Find the specific payment for this instalment (by due_date match)
            inst_payment = next(
                (p for p in payments if p["due_date_str"] == str(due_dt)),
                None,
            )
            paid_amount = inst_payment["paid_amount"] if inst_payment else 0.0
            paid_date_str = str(inst_payment["paid_date"]) if inst_payment and inst_payment["paid_date"] else None

            shortfall = round(max(0, required_cumulative - actual_cumulative), 2)

            # 234C: 1% per month for 3 months
            interest_234c = round(shortfall * 0.01 * 3, 2)
            interest_months = 3

            # March exception: if Q4 shortfall <= 10% of estimated tax, no 234C
            if key == "15_mar" and shortfall <= estimated_tax * 0.10:
                interest_234c = 0.0

            total_234c += interest_234c

            instalment_results.append({
                "instalment": schedule["label"],
                "due_date": str(due_dt),
                "required_cumulative": required_cumulative,
                "actual_cumulative": actual_cumulative,
                "paid_amount": paid_amount,
                "paid_date": paid_date_str,
                "shortfall": shortfall,
                "interest_234c": interest_234c,
                "interest_months": interest_months,
            })

        total_234c = round(total_234c, 2)

        # --- Section 234B: Interest on default in advance tax ---
        total_advance_paid = round(sum(p["paid_amount"] for p in payments), 2)
        threshold_90pct = round(estimated_tax * 0.90, 2)

        filing_dt = _parse_date(itr_filing_date) if itr_filing_date else date.today()
        april_1_ay = date(ay_year, 4, 1)

        section_234b = {"applicable": False, "total_advance_paid": total_advance_paid,
                        "threshold_90pct": threshold_90pct, "shortfall": 0.0,
                        "months": 0, "interest": 0.0}

        if total_advance_paid < threshold_90pct:
            shortfall_b = round(estimated_tax - total_advance_paid, 2)
            months_b = _months_between(april_1_ay, filing_dt)
            interest_b = round(shortfall_b * 0.01 * months_b, 2)
            section_234b = {
                "applicable": True,
                "total_advance_paid": total_advance_paid,
                "threshold_90pct": threshold_90pct,
                "shortfall": shortfall_b,
                "months": months_b,
                "interest": interest_b,
            }

        # --- Section 234A: Interest for late filing ---
        itr_due_dt = _parse_date(itr_due_date) if itr_due_date else date(ay_year, 7, 31)

        section_234a = {"applicable": False, "itr_due_date": str(itr_due_dt),
                        "itr_filing_date": str(filing_dt), "assessed_tax": 0.0,
                        "months": 0, "interest": 0.0}

        if filing_dt > itr_due_dt:
            assessed_tax = round(max(0, estimated_tax - total_advance_paid), 2)
            months_a = _months_between(itr_due_dt, filing_dt)
            interest_a = round(assessed_tax * 0.01 * months_a, 2)
            section_234a = {
                "applicable": True,
                "itr_due_date": str(itr_due_dt),
                "itr_filing_date": str(filing_dt),
                "assessed_tax": assessed_tax,
                "months": months_a,
                "interest": interest_a,
            }

        total_interest = round(
            total_234c + section_234b["interest"] + section_234a["interest"], 2
        )

        # Planning note
        notes = []
        if section_234b["applicable"]:
            if section_234b["months"] == 0:
                notes.append(
                    f"Total advance tax paid (Rs.{total_advance_paid:,.2f}) is below 90% threshold "
                    f"(Rs.{threshold_90pct:,.2f}). 234B shortfall exists but interest period has not started yet "
                    f"(ITR filing date is before Apr 1 of AY). 234B interest will accrue from Apr 1."
                )
            else:
                notes.append(
                    f"Total advance tax paid (Rs.{total_advance_paid:,.2f}) is below 90% threshold "
                    f"(Rs.{threshold_90pct:,.2f}). 234B interest of Rs.{section_234b['interest']:,.2f} applies."
                )
        if section_234a["applicable"]:
            notes.append(
                f"ITR filed after due date. 234A interest of Rs.{section_234a['interest']:,.2f} applies."
            )
        if total_234c > 0:
            notes.append(
                f"Instalment shortfalls attract 234C interest totalling Rs.{total_234c:,.2f}."
            )
        if not notes:
            notes.append("All advance tax instalments are on track. No interest liability.")
        planning_note = " ".join(notes)

        return {
            "estimated_tax": estimated_tax,
            "fy": fy,
            "instalments": instalment_results,
            "total_234c_interest": total_234c,
            "section_234b": section_234b,
            "section_234a": section_234a,
            "total_interest": total_interest,
            "planning_note": planning_note,
        }

    def compute_remaining_instalment(
        self,
        estimated_annual_tax: float,
        fy: str,
        paid_so_far: float = 0.0,
        today: date | None = None,
    ) -> dict:
        """Forward-looking: compute recommended payments for upcoming instalments."""
        start_year = int(fy[:4])
        today = today or date.today()

        remaining = []
        total_remaining = 0.0

        for key, schedule in ADVANCE_TAX_SCHEDULE.items():
            due_dt = _build_due_date(start_year, schedule["month"], schedule["day"])
            if due_dt < today:
                continue

            required_cumulative = round(estimated_annual_tax * schedule["cumulative_pct"], 2)
            recommended = round(max(0, required_cumulative - paid_so_far), 2)
            total_remaining += recommended

            remaining.append({
                "instalment": schedule["label"],
                "due_date": str(due_dt),
                "required_cumulative": required_cumulative,
                "already_paid": paid_so_far,
                "recommended_payment": recommended,
            })

        return {
            "estimated_annual_tax": estimated_annual_tax,
            "paid_so_far": paid_so_far,
            "today": str(today),
            "remaining_instalments": remaining,
            "total_remaining": round(total_remaining, 2),
        }
