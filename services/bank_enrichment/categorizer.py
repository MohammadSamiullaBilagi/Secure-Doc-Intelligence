"""Rule-based transaction categorization for bank statements.

Each transaction description + amount + direction is classified into a single
category from a fixed taxonomy. Rules are applied in priority order — first
match wins. Confidence is a coarse 0.0–1.0 signal so downstream UI can grey
out low-confidence rows.

The taxonomy is intentionally CA-centric: we distinguish TAX/GST/TDS from
general expenses, salary from drawings, interest income from interest expense,
and supplier payment from customer receipt, because these map directly to
ITR schedules and books of accounts.
"""

from __future__ import annotations

import re
from typing import Tuple

CATEGORY_SALARY = "SALARY"
CATEGORY_RENT = "RENT"
CATEGORY_EMI = "EMI_LOAN_REPAYMENT"
CATEGORY_UTILITIES = "UTILITIES"
CATEGORY_TAX = "TAX_PAYMENT"
CATEGORY_GST = "GST_PAYMENT"
CATEGORY_TDS = "TDS_PAYMENT"
CATEGORY_INSURANCE = "INSURANCE"
CATEGORY_INVESTMENT = "INVESTMENT"
CATEGORY_LOAN_DISBURSAL = "LOAN_DISBURSAL"
CATEGORY_INTEREST_INCOME = "INTEREST_INCOME"
CATEGORY_DIVIDEND = "DIVIDEND_INCOME"
CATEGORY_FD = "FD_FDR"
CATEGORY_SUPPLIER = "SUPPLIER_PAYMENT"
CATEGORY_CUSTOMER = "CUSTOMER_RECEIPT"
CATEGORY_PERSONAL = "PERSONAL_EXPENSE"
CATEGORY_CASH = "CASH_MOVEMENT"
CATEGORY_TRANSFER_SELF = "SELF_TRANSFER"
CATEGORY_FEE_CHARGE = "BANK_CHARGES"
CATEGORY_REFUND = "REFUND"
CATEGORY_OTHER = "OTHER"


# Priority-ordered rules. Each entry: (regex, category, direction_filter)
# direction_filter: "debit", "credit", or None (either).
_RULES: list[tuple[re.Pattern, str, str | None]] = [
    # Tax / statutory — highest priority so "SELF ASSESSMENT TAX" doesn't fall through to PERSONAL
    (re.compile(r"\b(advance\s*tax|self\s*assessment|self-assessment|income\s*tax|it\s*challan|challan\s*280)\b", re.I), CATEGORY_TAX, "debit"),
    (re.compile(r"\b(gstn|gstin|gst\s*payment|gst\s*challan|igst|cgst|sgst|gstpmt|pmt[-\s]?06)\b", re.I), CATEGORY_GST, "debit"),
    (re.compile(r"\b(tds|tcs|194[a-z]?|challan\s*281|traces)\b", re.I), CATEGORY_TDS, "debit"),

    # Loans & EMI
    (re.compile(r"\b(emi|loan\s*repay|hl\s*repay|home\s*loan|car\s*loan|personal\s*loan|mortgage|equated)\b", re.I), CATEGORY_EMI, "debit"),
    (re.compile(r"\b(loan\s*disbur|disbursement|loan\s*credit|loan\s*cr)\b", re.I), CATEGORY_LOAN_DISBURSAL, "credit"),

    # Investment & income
    (re.compile(r"\b(mutual\s*fund|sip|nippon|uti|sbi\s*mf|hdfc\s*mf|icici\s*mf|axis\s*mf|franklin|aditya\s*birla\s*mf)\b", re.I), CATEGORY_INVESTMENT, "debit"),
    (re.compile(r"\b(fd\s*creation|fdr|fixed\s*deposit|term\s*deposit)\b", re.I), CATEGORY_FD, None),
    (re.compile(r"\b(dividend|div\s*cr|div\s*credit)\b", re.I), CATEGORY_DIVIDEND, "credit"),
    (re.compile(r"\b(interest\s*cr|int\s*credited|int\s*cr|saving\s*int|int\.?\s*pd\s*till|interest\s*on)\b", re.I), CATEGORY_INTEREST_INCOME, "credit"),

    # Salary — credit side keywords
    (re.compile(r"\b(salary|sal\s*cr|sal\s*credit|stipend|payroll|sal[.:/-])\b", re.I), CATEGORY_SALARY, "credit"),
    # Salary — debit side (employer paying out)
    (re.compile(r"\b(staff\s*salary|payroll\s*debit|salary\s*payment)\b", re.I), CATEGORY_SALARY, "debit"),

    # Rent
    (re.compile(r"\brent\b", re.I), CATEGORY_RENT, None),

    # Utilities
    (re.compile(r"\b(electricity|bescom|tangedco|bses|mseb|adani\s*electric|torrent\s*power)\b", re.I), CATEGORY_UTILITIES, "debit"),
    (re.compile(r"\b(water\s*bill|bwssb|jal\s*board|kwa)\b", re.I), CATEGORY_UTILITIES, "debit"),
    (re.compile(r"\b(gas\s*bill|indraprastha\s*gas|mahanagar\s*gas|ignl|gail)\b", re.I), CATEGORY_UTILITIES, "debit"),
    (re.compile(r"\b(airtel|jio|vi\s*|vodafone|bsnl|tata\s*sky|dish\s*tv|d2h|hathway|act\s*fiber)\b", re.I), CATEGORY_UTILITIES, "debit"),

    # Insurance
    (re.compile(r"\b(lic|licofindia|insurance|premium|policy|hdfc\s*ergo|bajaj\s*allianz|icici\s*lomb|star\s*health|hdfc\s*life|max\s*life)\b", re.I), CATEGORY_INSURANCE, "debit"),

    # Refund / reversal
    (re.compile(r"\b(refund|rev\b|reversal|chargeback|refd)\b", re.I), CATEGORY_REFUND, "credit"),

    # Bank charges & fees
    (re.compile(r"\b(charges|chg|sms\s*charges|sms\s*chg|min\s*bal|service\s*charge|annual\s*fee|folio\s*chg|amc\s*chg|maint\s*chg|penalty|late\s*fee|gst\s*on|gst\s*chg)\b", re.I), CATEGORY_FEE_CHARGE, "debit"),

    # Personal / lifestyle — low priority, catches consumer spend
    (re.compile(r"\b(swiggy|zomato|amazon|flipkart|myntra|bigbasket|blinkit|zepto|uber|ola|pvr|bookmyshow|netflix|hotstar|spotify|apple\.com|google\s*play)\b", re.I), CATEGORY_PERSONAL, "debit"),

    # Cash movement (ATM / cash deposit)
    (re.compile(r"\b(atm|cash\s*wdl|cash\s*withdrawal|cash\s*dep|cash\s*deposit|by\s*cash|cash\s*cr|cash\s*dr|nwd|cwdr)\b", re.I), CATEGORY_CASH, None),

    # Self transfer
    (re.compile(r"\b(self|own\s*a/?c|to\s*own|inter\s*account|transfer\s*to\s*self|ot[sr]\b)\b", re.I), CATEGORY_TRANSFER_SELF, None),
]

# Keywords that hint at supplier vs customer (applied after the above rules
# only for NEFT/IMPS/UPI/RTGS rows that did not match a higher-priority rule).
_SUPPLIER_HINTS = re.compile(r"\b(enterprise|traders|trading|pvt\s*ltd|private\s*limited|industries|corporation|corp|agencies|suppliers|wholesaler|distributor|srl|llc)\b", re.I)
_CUSTOMER_HINTS = re.compile(r"\b(invoice|inv\s*no|bill\s*no|against\s*bill|on\s*account|receipt|receivable)\b", re.I)


def categorize(description: str, amount: float, is_credit: bool) -> Tuple[str, float]:
    """Classify a single transaction.

    Returns (category, confidence). Confidence is a coarse signal: 0.9 for a
    direct regex hit, 0.6 for a heuristic fall-back, 0.3 for OTHER.
    """
    desc = description or ""
    direction = "credit" if is_credit else "debit"

    for pattern, category, direction_filter in _RULES:
        if direction_filter and direction_filter != direction:
            continue
        if pattern.search(desc):
            return category, 0.9

    # Fall-back: NEFT/IMPS/RTGS rows — try supplier vs customer heuristic
    if re.search(r"\b(neft|imps|rtgs|upi)\b", desc, re.I):
        if is_credit:
            if _CUSTOMER_HINTS.search(desc) or _SUPPLIER_HINTS.search(desc):
                return CATEGORY_CUSTOMER, 0.6
            return CATEGORY_CUSTOMER, 0.5
        else:
            if _SUPPLIER_HINTS.search(desc):
                return CATEGORY_SUPPLIER, 0.7
            return CATEGORY_SUPPLIER, 0.5

    return CATEGORY_OTHER, 0.3
