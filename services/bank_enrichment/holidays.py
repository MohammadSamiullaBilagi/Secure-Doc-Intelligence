"""Indian bank holiday awareness — FY2025-26 and FY2026-27.

Used to flag high-value transactions on non-working days (Sunday, 2nd/4th
Saturday, or a declared bank holiday). The list is curated from the RBI
holiday calendar for each state (we use the PAN-India list; state-specific
holidays are deliberately omitted to avoid false positives).
"""

from __future__ import annotations

from datetime import date

# (year, month, day, label) — PAN-India RBI holidays only
_HOLIDAYS: set[tuple[int, int, int]] = {
    # FY 2025-26
    (2025, 4, 14),  # Dr. B.R. Ambedkar Jayanti
    (2025, 4, 18),  # Good Friday
    (2025, 5, 1),   # Maharashtra Day / Labour Day
    (2025, 8, 15),  # Independence Day
    (2025, 10, 2),  # Gandhi Jayanti
    (2025, 10, 20), # Diwali (Lakshmi Pujan)
    (2025, 11, 5),  # Guru Nanak Jayanti
    (2025, 12, 25), # Christmas

    # FY 2026-27
    (2026, 1, 26),  # Republic Day
    (2026, 3, 3),   # Holi
    (2026, 4, 3),   # Good Friday
    (2026, 4, 14),  # Dr. B.R. Ambedkar Jayanti
    (2026, 5, 1),   # Maharashtra Day / Labour Day
    (2026, 8, 15),  # Independence Day
    (2026, 10, 2),  # Gandhi Jayanti
    (2026, 11, 9),  # Diwali (Lakshmi Pujan)
    (2026, 11, 24), # Guru Nanak Jayanti
    (2026, 12, 25), # Christmas
}


def is_bank_holiday(d: date) -> bool:
    """Return True if `d` is a declared PAN-India bank holiday."""
    return (d.year, d.month, d.day) in _HOLIDAYS


def _is_second_or_fourth_saturday(d: date) -> bool:
    if d.weekday() != 5:  # not Saturday
        return False
    nth = (d.day - 1) // 7 + 1
    return nth in (2, 4)


def is_non_working_day(d: date) -> bool:
    """Return True if `d` is a Sunday, 2nd/4th Saturday, or declared holiday."""
    if d.weekday() == 6:  # Sunday
        return True
    if _is_second_or_fourth_saturday(d):
        return True
    return is_bank_holiday(d)
