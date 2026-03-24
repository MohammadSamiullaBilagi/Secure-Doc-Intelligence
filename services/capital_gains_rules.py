"""Budget 2024 Capital Gains Tax Rules — pure Python, no LLM, no I/O.

Covers equity shares, equity MF, balanced funds, debt MF (50AA), gold ETF,
listed bonds/debentures, unlisted shares, and real estate.
Rate determined per-transaction by sale_date (pre/post Budget 2024 cutoff).
"""

from datetime import date
from dateutil.relativedelta import relativedelta

# Budget 2024 (Finance Act 2024) effective date
BUDGET_2024_CUTOFF = date(2024, 7, 23)

# ---------------------------------------------------------------------------
# Tax rate tables — keyed by (asset_type, is_ltcg, is_new_regime)
# ---------------------------------------------------------------------------
TAX_RATES = {
    # ---- Equity shares (listed, STT paid) ----
    "equity_shares": {
        "ltcg_holding_months": 12,
        "old_regime": {
            "ltcg": {"rate": 0.10, "section": "112A", "exemption_limit": 100_000, "indexation": False},
            "stcg": {"rate": 0.15, "section": "111A", "exemption_limit": 0, "indexation": False},
        },
        "new_regime": {
            "ltcg": {"rate": 0.125, "section": "112A", "exemption_limit": 125_000, "indexation": False},
            "stcg": {"rate": 0.20, "section": "111A", "exemption_limit": 0, "indexation": False},
        },
    },
    # ---- Equity mutual funds ----
    "equity_mf": {
        "ltcg_holding_months": 12,
        "old_regime": {
            "ltcg": {"rate": 0.10, "section": "112A", "exemption_limit": 100_000, "indexation": False},
            "stcg": {"rate": 0.15, "section": "111A", "exemption_limit": 0, "indexation": False},
        },
        "new_regime": {
            "ltcg": {"rate": 0.125, "section": "112A", "exemption_limit": 125_000, "indexation": False},
            "stcg": {"rate": 0.20, "section": "111A", "exemption_limit": 0, "indexation": False},
        },
    },
    # ---- Balanced / hybrid funds (equity >= 65%) ----
    "balanced_fund": {
        "ltcg_holding_months": 12,
        "old_regime": {
            "ltcg": {"rate": 0.10, "section": "112A", "exemption_limit": 100_000, "indexation": False},
            "stcg": {"rate": 0.15, "section": "111A", "exemption_limit": 0, "indexation": False},
        },
        "new_regime": {
            "ltcg": {"rate": 0.125, "section": "112A", "exemption_limit": 125_000, "indexation": False},
            "stcg": {"rate": 0.20, "section": "111A", "exemption_limit": 0, "indexation": False},
        },
    },
    # ---- Debt mutual funds (purchased on/after 1-Apr-2023 → Sec 50AA, slab rate) ----
    "debt_mf": {
        "ltcg_holding_months": 36,  # pre-2023 legacy; post-2023 always STCG at slab
        "old_regime": {
            "ltcg": {"rate": 0.20, "section": "112", "exemption_limit": 0, "indexation": True},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
        "new_regime": {
            # Post-Apr-2023 debt MF: no LTCG benefit — taxed at slab via Sec 50AA
            "ltcg": {"rate": None, "section": "50AA", "exemption_limit": 0, "indexation": False},
            "stcg": {"rate": None, "section": "50AA", "exemption_limit": 0, "indexation": False},
        },
    },
    # ---- Gold ETF / Sovereign Gold Bonds ----
    "gold_etf": {
        "ltcg_holding_months": 24,  # reduced from 36 post-Budget 2024
        "old_regime": {
            "ltcg": {"rate": 0.20, "section": "112", "exemption_limit": 0, "indexation": True},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
        "new_regime": {
            "ltcg": {"rate": 0.125, "section": "112", "exemption_limit": 0, "indexation": False},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
    },
    # ---- Listed bonds and debentures ----
    "listed_bonds_debentures": {
        "ltcg_holding_months": 12,
        "old_regime": {
            "ltcg": {"rate": 0.10, "section": "112", "exemption_limit": 0, "indexation": False},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
        "new_regime": {
            "ltcg": {"rate": 0.125, "section": "112", "exemption_limit": 0, "indexation": False},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
    },
    # ---- Unlisted shares ----
    "unlisted_shares": {
        "ltcg_holding_months": 24,
        "old_regime": {
            "ltcg": {"rate": 0.20, "section": "112", "exemption_limit": 0, "indexation": True},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
        "new_regime": {
            "ltcg": {"rate": 0.125, "section": "112", "exemption_limit": 0, "indexation": False},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
    },
    # ---- Real estate / immovable property ----
    "real_estate": {
        "ltcg_holding_months": 24,
        "old_regime": {
            "ltcg": {"rate": 0.20, "section": "112", "exemption_limit": 0, "indexation": True},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
        "new_regime": {
            "ltcg": {"rate": 0.125, "section": "112", "exemption_limit": 0, "indexation": False},
            "stcg": {"rate": None, "section": "slab", "exemption_limit": 0, "indexation": False},
        },
    },
}

# ---------------------------------------------------------------------------
# Asset classification — keyword matching
# ---------------------------------------------------------------------------
_ASSET_KEYWORDS = {
    "equity_shares": [
        "EQUITY", "SHARE", "BSE", "NSE", "LISTED", "SENSEX", "NIFTY",
    ],
    "equity_mf": [
        "EQUITY FUND", "EQUITY MF", "FLEXI CAP", "LARGE CAP", "MID CAP",
        "SMALL CAP", "MULTI CAP", "INDEX FUND", "ELSS", "TAX SAVER",
        "GROWTH FUND", "EQUITY MUTUAL",
    ],
    "balanced_fund": [
        "BALANCED", "HYBRID", "AGGRESSIVE HYBRID", "BALANCED ADVANTAGE",
        "DYNAMIC ASSET", "MULTI ASSET",
    ],
    "debt_mf": [
        "DEBT FUND", "DEBT MF", "LIQUID FUND", "OVERNIGHT FUND",
        "ULTRA SHORT", "SHORT DURATION", "GILT", "CORPORATE BOND",
        "BANKING & PSU", "CREDIT RISK", "MONEY MARKET", "FIXED MATURITY",
        "FMP", "DEBT MUTUAL",
    ],
    "gold_etf": [
        "GOLD ETF", "GOLD FUND", "SOVEREIGN GOLD", "SGB", "GOLD BEES",
        "GOLDBEES", "GOLD MF",
    ],
    "listed_bonds_debentures": [
        "BOND", "DEBENTURE", "NCD", "LISTED BOND", "LISTED DEBENTURE",
    ],
    "unlisted_shares": [
        "UNLISTED", "PRIVATE COMPANY", "PVTLTD", "PVT LTD",
    ],
    "real_estate": [
        "PROPERTY", "REAL ESTATE", "LAND", "FLAT", "HOUSE", "APARTMENT",
        "PLOT", "IMMOVABLE",
    ],
}


def classify_asset(description: str) -> str:
    """Classify an asset description into one of the known asset types.

    Returns one of: equity_shares, equity_mf, balanced_fund, debt_mf,
    gold_etf, listed_bonds_debentures, unlisted_shares, real_estate.
    Defaults to equity_shares if no match (most common in broker PDFs).
    """
    upper = (description or "").upper()

    # Check more specific categories first (longer keyword lists)
    # Order matters: check MF types before generic equity
    for asset_type in [
        "balanced_fund", "debt_mf", "equity_mf", "gold_etf",
        "listed_bonds_debentures", "unlisted_shares", "real_estate",
        "equity_shares",
    ]:
        for kw in _ASSET_KEYWORDS[asset_type]:
            if kw in upper:
                return asset_type

    # Default: broker capital gains statements are mostly equity
    return "equity_shares"


# ---------------------------------------------------------------------------
# Holding period calculation
# ---------------------------------------------------------------------------

def calculate_holding_months(purchase_date: date, sale_date: date) -> int:
    """Calculate holding period in whole months using dateutil.relativedelta."""
    if not purchase_date or not sale_date:
        return 0
    if sale_date < purchase_date:
        return 0
    rd = relativedelta(sale_date, purchase_date)
    return rd.years * 12 + rd.months


# ---------------------------------------------------------------------------
# Tax rate lookup
# ---------------------------------------------------------------------------

def get_tax_rate(asset_type: str, holding_months: int, sale_date: date) -> dict:
    """Determine applicable tax rate for a single transaction.

    Returns:
        {rate, rate_display, section, is_ltcg, exemption_available,
         holding_period_label, indexation}

    Rate is determined by sale_date — transactions sold before Budget 2024
    cutoff (23-Jul-2024) get old rates, on/after get new rates.
    """
    config = TAX_RATES.get(asset_type, TAX_RATES["equity_shares"])
    ltcg_threshold = config["ltcg_holding_months"]
    is_ltcg = holding_months >= ltcg_threshold

    # Determine regime based on sale date
    is_new = sale_date >= BUDGET_2024_CUTOFF if sale_date else True
    regime = config["new_regime"] if is_new else config["old_regime"]
    rate_info = regime["ltcg"] if is_ltcg else regime["stcg"]

    rate = rate_info["rate"]
    section = rate_info["section"]
    exemption_limit = rate_info["exemption_limit"]
    indexation = rate_info.get("indexation", False)

    if rate is not None:
        rate_display = f"{rate * 100:.1f}%"
    else:
        rate_display = "Slab rate"

    holding_label = "LTCG" if is_ltcg else "STCG"

    return {
        "rate": rate,
        "rate_display": rate_display,
        "section": section,
        "is_ltcg": is_ltcg,
        "exemption_available": exemption_limit > 0,
        "exemption_limit": exemption_limit,
        "holding_period_label": holding_label,
        "holding_threshold_months": ltcg_threshold,
        "indexation": indexation,
        "regime": "post_budget_2024" if is_new else "pre_budget_2024",
    }
