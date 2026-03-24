"""Capital Gains Service — LLM extraction + deterministic Schedule CG computation."""

import json
import logging
import re
from datetime import date, datetime

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from services.capital_gains_rules import (
    classify_asset,
    calculate_holding_months,
    get_tax_rate,
)

logger = logging.getLogger(__name__)

MAX_INPUT_CHARS = 12_000


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
# Column aliases for flexible header matching (broker statement columns)
# ---------------------------------------------------------------------------
_ASSET_ALIASES = {"asset", "scrip", "scrip name", "security", "stock", "name",
                  "asset name", "asset_name", "security name", "instrument", "description",
                  "particulars", "share name", "company", "company name", "fund name"}
_ISIN_ALIASES = {"isin", "isin code", "isin no", "isin number"}
_BUY_DATE_ALIASES = {"buy date", "purchase date", "acquisition date", "date of purchase",
                     "date of acquisition", "buy_date", "purchase_date", "acq date",
                     "date of buy"}
_SELL_DATE_ALIASES = {"sell date", "sale date", "date of sale", "transfer date",
                      "sell_date", "sale_date", "date of transfer", "redemption date",
                      "date of sell"}
_QTY_ALIASES = {"quantity", "qty", "units", "no of shares", "shares", "no. of shares",
                "units sold", "quantity sold"}
_BUY_PRICE_ALIASES = {"buy price", "purchase price", "cost price", "acquisition price",
                      "buy rate", "purchase rate", "avg cost", "average cost",
                      "cost per unit", "buy_price", "purchase_price"}
_SELL_PRICE_ALIASES = {"sell price", "sale price", "selling price", "sell rate",
                       "sale rate", "redemption price", "sell_price", "sale_price",
                       "price per unit"}
_BUY_VALUE_ALIASES = {"buy value", "purchase value", "cost value", "total cost",
                      "acquisition value", "buy_value", "purchase_value",
                      "cost of acquisition", "purchase consideration"}
_SELL_VALUE_ALIASES = {"sell value", "sale value", "sale consideration", "sale proceeds",
                       "selling value", "sell_value", "sale_value", "total sale",
                       "redemption value", "sale consideration"}
_GAIN_ALIASES = {"gain", "gain/loss", "profit/loss", "gain loss", "p&l", "pnl",
                 "capital gain", "net gain", "profit", "gain_loss", "capital_gain"}


def _get_field(row: dict, aliases: set):
    """Find a field value by checking against alias set (case-insensitive)."""
    keys_lower = {}
    for k in row.keys():
        low = k.lower().strip()
        keys_lower[low] = k
        normalized = low.replace("_", " ")
        if normalized != low:
            keys_lower[normalized] = k
    for alias in aliases:
        if alias in keys_lower:
            return row[keys_lower[alias]]
    return None


class CapitalGainsService:
    """Extract capital gains transactions from broker PDFs and compute Schedule CG."""

    def extract_transactions(self, raw_text: str) -> list[dict]:
        """Use a capital-gains-specific LLM prompt to extract transactions."""

        if len(raw_text) > MAX_INPUT_CHARS:
            logger.info(f"CapitalGainsService: Truncating input from {len(raw_text)} to {MAX_INPUT_CHARS} chars")
            raw_text = raw_text[:MAX_INPUT_CHARS]

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are a capital gains data extraction specialist for Indian tax filings.\n\n"
             "TASK: Read the broker statement / capital gains report and extract EVERY sale "
             "transaction into a JSON array.\n\n"
             "RULES:\n"
             "1. OUTPUT VALID JSON ONLY — no markdown, no explanations.\n"
             "2. Return an object with a single key \"transactions\" containing an array.\n"
             "3. Each transaction object MUST have these keys (use null if missing):\n"
             "   - asset_name: string (scrip/security/fund name)\n"
             "   - isin: string or null\n"
             "   - purchase_date: string in DD-MM-YYYY or DD/MM/YYYY format, or null\n"
             "   - sale_date: string in DD-MM-YYYY or DD/MM/YYYY format, or null\n"
             "   - quantity: number or null\n"
             "   - purchase_price: number (per unit) or null\n"
             "   - sale_price: number (per unit) or null\n"
             "   - purchase_value: number (total cost of acquisition) or null\n"
             "   - sale_value: number (total sale consideration) or null\n"
             "   - gain_loss: number (broker-reported gain/loss) or null\n"
             "4. Extract ALL rows — do not skip any transaction.\n"
             "5. Use numeric values (not strings) for amounts and quantities.\n"
             "6. If the document has totals/summary rows, do NOT include them as transactions.\n"),
            ("human",
             "BROKER STATEMENT TEXT:\n{context}\n\n"
             "Extract all capital gains transactions as JSON now."),
        ])

        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            max_tokens=4096,
        ).bind(response_format={"type": "json_object"})

        try:
            response = (prompt | llm).invoke({"context": raw_text})
            content = response.content

            # Parse JSON
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                # Try extracting JSON substring
                start = content.find("{")
                end = content.rfind("}")
                if start >= 0 and end > start:
                    parsed = json.loads(content[start:end + 1])
                else:
                    logger.error("CapitalGainsService: Failed to parse LLM JSON response")
                    return []

            raw_txns = parsed.get("transactions", [])
            if not raw_txns and isinstance(parsed, list):
                raw_txns = parsed

            logger.info(f"CapitalGainsService: LLM returned {len(raw_txns)} raw transactions")

        except Exception as e:
            logger.error(f"CapitalGainsService: LLM extraction failed: {e}")
            return []

        transactions = []
        for row in raw_txns:
            if not isinstance(row, dict):
                continue
            txn = self._row_to_transaction(row)
            if txn:
                transactions.append(txn)

        logger.info(f"CapitalGainsService: Extracted {len(transactions)} valid transactions")
        return transactions

    def _row_to_transaction(self, row: dict) -> dict | None:
        """Convert a row dict to a standardized capital gains transaction dict."""
        asset_name = str(_get_field(row, _ASSET_ALIASES) or "").strip()
        isin = str(_get_field(row, _ISIN_ALIASES) or "").strip() or None
        purchase_date = _parse_date(_get_field(row, _BUY_DATE_ALIASES))
        sale_date = _parse_date(_get_field(row, _SELL_DATE_ALIASES))
        quantity = _parse_float(_get_field(row, _QTY_ALIASES))
        buy_price = _parse_float(_get_field(row, _BUY_PRICE_ALIASES))
        sell_price = _parse_float(_get_field(row, _SELL_PRICE_ALIASES))
        buy_value = _parse_float(_get_field(row, _BUY_VALUE_ALIASES))
        sell_value = _parse_float(_get_field(row, _SELL_VALUE_ALIASES))
        broker_gain = _get_field(row, _GAIN_ALIASES)

        # Compute values from price * qty if totals missing
        if buy_value == 0.0 and buy_price > 0 and quantity > 0:
            buy_value = round(buy_price * quantity, 2)
        if sell_value == 0.0 and sell_price > 0 and quantity > 0:
            sell_value = round(sell_price * quantity, 2)

        # Skip rows with no meaningful data
        if buy_value == 0.0 and sell_value == 0.0:
            return None

        computed_gain = round(sell_value - buy_value, 2)
        broker_gain_val = _parse_float(broker_gain) if broker_gain is not None else None

        asset_type = classify_asset(asset_name)
        holding_months = calculate_holding_months(purchase_date, sale_date)
        tax_info = get_tax_rate(asset_type, holding_months, sale_date) if sale_date else {}

        return {
            "asset_name": asset_name,
            "isin": isin,
            "asset_type": asset_type,
            "purchase_date": purchase_date.isoformat() if purchase_date else None,
            "sale_date": sale_date.isoformat() if sale_date else None,
            "quantity": quantity,
            "purchase_price": buy_price,
            "sale_price": sell_price,
            "purchase_value": buy_value,
            "sale_value": sell_value,
            "broker_gain_loss": broker_gain_val,
            "computed_gain_loss": computed_gain,
            "holding_months": holding_months,
            "tax_info": tax_info,
        }

    def compute_schedule_cg(self, transactions: list[dict], fy: str) -> dict:
        """Compute ITR Schedule CG buckets from extracted transactions.

        Buckets:
        - ltcg_equity (Sec 112A): equity_shares, equity_mf, balanced_fund with LTCG
        - stcg_equity (Sec 111A): equity_shares, equity_mf, balanced_fund with STCG
        - ltcg_other (Sec 112): gold_etf, listed_bonds, unlisted_shares, real_estate LTCG
        - stcg_other (slab): non-equity STCG
        - debt_mf_gains (Sec 50AA): debt MF post-Apr-2023 (all at slab)
        """
        equity_types = {"equity_shares", "equity_mf", "balanced_fund"}

        buckets = {
            "ltcg_equity": {"section": "112A", "transactions": [], "gross_gain": 0.0,
                            "gross_loss": 0.0, "net": 0.0, "tax": 0.0},
            "stcg_equity": {"section": "111A", "transactions": [], "gross_gain": 0.0,
                            "gross_loss": 0.0, "net": 0.0, "tax": 0.0},
            "ltcg_other": {"section": "112", "transactions": [], "gross_gain": 0.0,
                           "gross_loss": 0.0, "net": 0.0, "tax": 0.0},
            "stcg_other": {"section": "slab", "transactions": [], "gross_gain": 0.0,
                           "gross_loss": 0.0, "net": 0.0, "tax": 0.0},
            "debt_mf_gains": {"section": "50AA", "transactions": [], "gross_gain": 0.0,
                              "gross_loss": 0.0, "net": 0.0, "tax": 0.0},
        }

        total_sale_value = 0.0
        total_purchase_value = 0.0
        recon_checked = 0
        recon_matched = 0
        recon_warnings = []

        for txn in transactions:
            asset_type = txn.get("asset_type", "equity_shares")
            tax_info = txn.get("tax_info", {})
            is_ltcg = tax_info.get("is_ltcg", False)
            section = tax_info.get("section", "")
            gain = txn.get("computed_gain_loss", 0.0)

            total_sale_value += txn.get("sale_value", 0.0)
            total_purchase_value += txn.get("purchase_value", 0.0)

            # Route to correct bucket
            if asset_type == "debt_mf" and section in ("50AA", "slab"):
                bucket_key = "debt_mf_gains"
            elif asset_type in equity_types:
                bucket_key = "ltcg_equity" if is_ltcg else "stcg_equity"
            else:
                bucket_key = "ltcg_other" if is_ltcg else "stcg_other"

            bucket = buckets[bucket_key]
            bucket["transactions"].append(txn)
            if gain >= 0:
                bucket["gross_gain"] += gain
            else:
                bucket["gross_loss"] += gain  # negative

            # Per-transaction tax (for mixed pre/post Budget 2024 rates in same FY)
            rate = tax_info.get("rate")
            if rate is not None and gain > 0:
                # Exemption applied at aggregate level for 112A, not per-txn
                if bucket_key != "ltcg_equity":
                    bucket["tax"] += round(gain * rate, 2)

            # Broker reconciliation
            broker_gl = txn.get("broker_gain_loss")
            if broker_gl is not None:
                recon_checked += 1
                diff = abs(gain - broker_gl)
                if diff <= 1.0:
                    recon_matched += 1
                else:
                    recon_warnings.append({
                        "asset": txn.get("asset_name", ""),
                        "sale_date": txn.get("sale_date"),
                        "computed": gain,
                        "broker": broker_gl,
                        "difference": round(diff, 2),
                    })

        # Finalize net for each bucket
        for key, bucket in buckets.items():
            bucket["net"] = round(bucket["gross_gain"] + bucket["gross_loss"], 2)
            bucket["gross_gain"] = round(bucket["gross_gain"], 2)
            bucket["gross_loss"] = round(abs(bucket["gross_loss"]), 2)
            bucket["count"] = len(bucket["transactions"])

        # Sec 112A exemption — aggregate, NOT per-transaction
        ltcg_eq = buckets["ltcg_equity"]
        gross_gain_112a = ltcg_eq["gross_gain"]
        # Determine exemption limit: use max from transactions (handles mixed old/new regime)
        exemption_limit = 125_000  # Budget 2024 default
        for txn in ltcg_eq["transactions"]:
            ti = txn.get("tax_info", {})
            el = ti.get("exemption_limit", 0)
            if el > 0 and el < exemption_limit:
                exemption_limit = el  # old regime had 100k
        exemption_112a = min(exemption_limit, gross_gain_112a) if gross_gain_112a > 0 else 0.0
        taxable_112a = max(0, gross_gain_112a - exemption_112a)

        # Compute 112A tax — per-transaction rate applied to proportional taxable amount
        if gross_gain_112a > 0 and taxable_112a > 0:
            for txn in ltcg_eq["transactions"]:
                gain = txn.get("computed_gain_loss", 0.0)
                if gain <= 0:
                    continue
                rate = txn.get("tax_info", {}).get("rate")
                if rate is not None:
                    # Proportion of this txn's gain that is taxable after exemption
                    proportion = taxable_112a / gross_gain_112a
                    ltcg_eq["tax"] += round(gain * proportion * rate, 2)
        ltcg_eq["tax"] = round(ltcg_eq["tax"], 2)
        ltcg_eq["exemption"] = round(exemption_112a, 2)
        ltcg_eq["taxable"] = round(taxable_112a, 2)

        total_gain_loss = round(sum(b["net"] for b in buckets.values()), 2)
        total_tax = round(sum(b["tax"] for b in buckets.values()), 2)
        total_exemptions = round(exemption_112a, 2)

        # Strip full transaction lists from bucket summary (keep in transactions_detail)
        schedule_cg = {}
        for key, bucket in buckets.items():
            bucket_out = {k: v for k, v in bucket.items() if k != "transactions"}
            bucket_out["estimated_tax"] = bucket_out.get("tax", 0.0)
            schedule_cg[key] = bucket_out

        return {
            "fy": fy,
            "schedule_cg": schedule_cg,
            "totals": {
                "total_transactions": len(transactions),
                "total_sale_value": round(total_sale_value, 2),
                "total_purchase_value": round(total_purchase_value, 2),
                "total_gain_loss": total_gain_loss,
                "total_estimated_tax": total_tax,
                "total_exemptions": total_exemptions,
            },
            "reconciliation": {
                "total_checked": recon_checked,
                "matched": recon_matched,
                "warnings": recon_warnings,
            },
            "itr_schedule_cg_values": {
                "B5_ltcg_112A_gross": round(gross_gain_112a, 2),
                "B5_ltcg_112A_exempt": round(exemption_112a, 2),
                "B5_ltcg_112A_taxable": round(taxable_112a, 2),
                "B4_stcg_111A": round(buckets["stcg_equity"]["net"], 2),
                "B6_ltcg_112": round(buckets["ltcg_other"]["net"], 2),
                "B3_stcg_other": round(buckets["stcg_other"]["net"], 2),
                "debt_mf_50AA": round(buckets["debt_mf_gains"]["net"], 2),
            },
            "transactions_detail": transactions,
        }
