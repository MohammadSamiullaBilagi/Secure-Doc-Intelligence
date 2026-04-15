"""Bank statement enrichment: categorization, counterparty, holidays, detectors.

Layered on top of the deterministic flag pipeline in `bank_statement_service.py`
to produce CA-ready output: monthly trends, category breakdowns, counterparty
summaries, and statutory-compliance hints beyond raw threshold flags.
"""

from services.bank_enrichment.categorizer import categorize
from services.bank_enrichment.counterparty import extract_counterparty
from services.bank_enrichment.holidays import is_bank_holiday, is_non_working_day
from services.bank_enrichment.detectors import run_detectors

__all__ = [
    "categorize",
    "extract_counterparty",
    "is_bank_holiday",
    "is_non_working_day",
    "run_detectors",
]
