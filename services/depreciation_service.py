"""Depreciation Service — LLM extraction + deterministic IT Act / Companies Act computation."""

import json
import logging
from datetime import date, datetime

from services.depreciation_rules import (
    classify_asset_block,
    get_it_block_rate,
    get_ca_useful_life,
)

logger = logging.getLogger(__name__)


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
_DESC_ALIASES = {"description", "asset", "asset name", "asset description",
                 "particulars", "name", "item", "nature of asset", "asset type"}
_DATE_ACQ_ALIASES = {"date acquired", "date of acquisition", "acquisition date",
                     "purchase date", "date of purchase", "date_acquired",
                     "date put to use", "date_of_acquisition", "acq date"}
_DATE_DISP_ALIASES = {"date disposed", "disposal date", "date of disposal",
                      "sale date", "date of sale", "date_disposed",
                      "date_of_disposal", "date sold"}
_COST_ALIASES = {"original cost", "cost", "acquisition cost", "total cost",
                 "gross cost", "original_cost", "purchase value", "purchase price",
                 "actual cost", "cost of acquisition"}
_WDV_ALIASES = {"wdv opening", "wdv", "opening wdv", "written down value",
                "wdv_opening", "opening_wdv", "book value", "wdv as on",
                "opening balance", "wdv at beginning"}
_DISPOSAL_ALIASES = {"disposal proceeds", "sale proceeds", "sale value",
                     "disposal_proceeds", "disposal value", "proceeds",
                     "sale consideration", "selling price"}


def _get_field(row: dict, aliases: set):
    """Find a field value by checking against alias set (case-insensitive)."""
    keys_lower = {k.lower().strip(): k for k in row.keys()}
    for alias in aliases:
        if alias in keys_lower:
            return row[keys_lower[alias]]
    return None


class DepreciationService:
    """Extract fixed asset register via LLM and compute depreciation schedules."""

    def extract_asset_register(self, raw_text: str) -> list[dict]:
        """Use LLM to extract fixed asset register into structured JSON."""
        from services.llm_config import get_json_llm

        llm = get_json_llm(heavy=True)

        truncated = raw_text[:100000]  # Gemini handles much larger context

        prompt = f"""Extract the fixed asset register from this document into a JSON object.

Return a JSON object with key "assets" containing an array. Each asset should have:
- description: string (name/description of the asset)
- date_acquired: string (date of purchase/acquisition, DD-MM-YYYY format)
- date_disposed: string or null (date of disposal/sale if any)
- original_cost: number (original purchase cost)
- wdv_opening: number or null (written down value at start of year, if available)
- disposal_proceeds: number or null (sale proceeds if disposed)

If no assets found, return {{"assets": []}}.

Document text:
{truncated}"""

        response = llm.invoke(prompt)
        try:
            data = json.loads(response.content)
        except json.JSONDecodeError:
            logger.error("Failed to parse LLM response as JSON for asset register")
            return []

        raw_assets = data.get("assets", [])
        if not raw_assets:
            return []

        assets = []
        for item in raw_assets:
            if isinstance(item, dict):
                desc = str(_get_field(item, _DESC_ALIASES) or item.get("description", "")).strip()
                date_acq = _parse_date(_get_field(item, _DATE_ACQ_ALIASES) or item.get("date_acquired"))
                date_disp = _parse_date(_get_field(item, _DATE_DISP_ALIASES) or item.get("date_disposed"))
                cost = _parse_float(_get_field(item, _COST_ALIASES) or item.get("original_cost"))
                wdv = _parse_float(_get_field(item, _WDV_ALIASES) or item.get("wdv_opening"))
                disposal = _parse_float(_get_field(item, _DISPOSAL_ALIASES) or item.get("disposal_proceeds"))

                if cost <= 0 and wdv <= 0:
                    continue

                block_key = classify_asset_block(desc)
                assets.append({
                    "description": desc,
                    "block_key": block_key,
                    "date_acquired": date_acq.isoformat() if date_acq else None,
                    "date_disposed": date_disp.isoformat() if date_disp else None,
                    "cost": cost,
                    "wdv_opening": wdv,
                    "disposal_proceeds": disposal,
                })

        logger.info(f"DepreciationService: Extracted {len(assets)} assets")
        return assets

    def compute_it_act_depreciation(self, assets: list[dict], fy_start: date, fy_end: date) -> dict:
        """Compute IT Act WDV block depreciation (Section 32).

        Implements:
        - Block grouping by asset category
        - Half-year rule: assets acquired after Oct 3 of FY get 50% depreciation
        - Disposal handling: excess over block value = STCG
        - Terminal depreciation when block value goes to zero
        """
        half_year_cutoff = date(fy_start.year, 10, 3)

        # Group assets by block_key
        blocks: dict[str, dict] = {}
        for asset in assets:
            bk = asset["block_key"]
            if bk not in blocks:
                rate = get_it_block_rate(bk)
                blocks[bk] = {
                    "rate": rate,
                    "opening_wdv": 0.0,
                    "additions": 0.0,
                    "half_year_additions": 0.0,
                    "disposals": 0.0,
                    "assets": [],
                }
            block = blocks[bk]
            block["assets"].append(asset)

            date_acq = _parse_date(asset.get("date_acquired"))
            date_disp = _parse_date(asset.get("date_disposed"))
            cost = asset.get("cost", 0.0)
            wdv = asset.get("wdv_opening", 0.0)
            disposal = asset.get("disposal_proceeds", 0.0)

            # Opening WDV
            if wdv > 0:
                block["opening_wdv"] += wdv
            elif date_acq and date_acq < fy_start:
                # Asset acquired before FY, use cost as proxy if no WDV given
                block["opening_wdv"] += cost

            # Additions during FY
            if date_acq and fy_start <= date_acq <= fy_end:
                block["additions"] += cost
                # Half-year rule check
                if date_acq > half_year_cutoff:
                    block["half_year_additions"] += cost

            # Disposals during FY
            if date_disp and fy_start <= date_disp <= fy_end:
                block["disposals"] += disposal

        # Compute depreciation per block
        total_depreciation = 0.0
        total_capital_gains = 0.0
        total_terminal_depreciation = 0.0

        for bk, block in blocks.items():
            rate = block["rate"]
            opening = block["opening_wdv"]
            additions = block["additions"]
            half_year_add = block["half_year_additions"]
            disposals = block["disposals"]

            net_block = opening + additions - disposals

            depreciation = 0.0
            capital_gain = 0.0
            terminal_depreciation = 0.0

            if net_block > 0:
                # Full rate on (net_block - half_year_additions)
                full_dep_base = net_block - half_year_add
                half_dep_base = half_year_add

                dep_full = max(0, full_dep_base) * rate
                dep_half = half_dep_base * rate * 0.5

                depreciation = round(dep_full + dep_half, 2)
                # Depreciation cannot exceed net block
                depreciation = min(depreciation, net_block)
            elif net_block < 0:
                # Block value negative = disposal exceeds block → STCG
                capital_gain = round(abs(net_block), 2)
            else:
                # net_block == 0 — if there were assets and disposals exhausted block
                if opening > 0 and disposals > 0:
                    terminal_depreciation = 0.0  # block fully set off

            closing_wdv = round(max(0, net_block - depreciation), 2)

            block["net_block"] = round(net_block, 2)
            block["depreciation"] = depreciation
            block["closing_wdv"] = closing_wdv
            block["capital_gain"] = capital_gain
            block["terminal_depreciation"] = terminal_depreciation

            total_depreciation += depreciation
            total_capital_gains += capital_gain
            total_terminal_depreciation += terminal_depreciation

        # Build serializable result (strip asset objects for summary)
        blocks_summary = {}
        for bk, block in blocks.items():
            blocks_summary[bk] = {
                "rate": block["rate"],
                "opening_wdv": round(block["opening_wdv"], 2),
                "additions": round(block["additions"], 2),
                "half_year_additions": round(block["half_year_additions"], 2),
                "disposals": round(block["disposals"], 2),
                "net_block": block["net_block"],
                "depreciation": block["depreciation"],
                "closing_wdv": block["closing_wdv"],
                "capital_gain": block["capital_gain"],
                "terminal_depreciation": block["terminal_depreciation"],
                "asset_count": len(block["assets"]),
            }

        return {
            "blocks": blocks_summary,
            "total_depreciation": round(total_depreciation, 2),
            "total_capital_gains": round(total_capital_gains, 2),
            "total_terminal_depreciation": round(total_terminal_depreciation, 2),
        }

    def compute_companies_act_depreciation(self, assets: list[dict], fy_start: date, fy_end: date) -> dict:
        """Compute Companies Act 2013 SLM depreciation per Schedule II.

        Per-asset basis:
        - Residual value = 5% of cost
        - Annual depreciation = (cost - residual) / useful_life
        - Proportionate for partial year (days held / 365)
        - Capped at (cost - residual) accumulated
        """
        fy_days = (fy_end - fy_start).days + 1
        asset_results = []
        total_depreciation = 0.0
        total_nbv = 0.0

        for asset in assets:
            cost = asset.get("cost", 0.0)
            if cost <= 0:
                continue

            block_key = asset.get("block_key", "plant_machinery_general")
            useful_life = get_ca_useful_life(block_key)
            residual = round(cost * 0.05, 2)
            depreciable = cost - residual
            annual_dep = round(depreciable / useful_life, 2) if useful_life > 0 else 0.0

            date_acq = _parse_date(asset.get("date_acquired"))
            date_disp = _parse_date(asset.get("date_disposed"))

            # Determine days held in FY
            hold_start = max(date_acq, fy_start) if date_acq else fy_start
            hold_end = min(date_disp, fy_end) if (date_disp and date_disp <= fy_end) else fy_end
            days_held = max(0, (hold_end - hold_start).days + 1) if hold_start <= hold_end else 0

            # Proportionate depreciation
            fy_dep = round(annual_dep * (days_held / fy_days), 2) if fy_days > 0 else 0.0

            # Estimate accumulated depreciation (simplified: years since acquisition)
            if date_acq and date_acq < fy_start:
                years_held = (fy_start - date_acq).days / 365.25
                accumulated_prior = min(round(annual_dep * years_held, 2), depreciable)
            else:
                accumulated_prior = 0.0

            # Cap: accumulated + fy_dep cannot exceed depreciable amount
            if accumulated_prior + fy_dep > depreciable:
                fy_dep = max(0, round(depreciable - accumulated_prior, 2))

            accumulated_total = round(accumulated_prior + fy_dep, 2)
            nbv = round(cost - accumulated_total, 2)
            fully_depreciated = accumulated_total >= depreciable

            asset_results.append({
                "description": asset.get("description", ""),
                "block_key": block_key,
                "cost": cost,
                "residual": residual,
                "useful_life": useful_life,
                "annual_dep": annual_dep,
                "days_held_in_fy": days_held,
                "fy_dep": fy_dep,
                "accumulated_prior": accumulated_prior,
                "accumulated_total": accumulated_total,
                "nbv": nbv,
                "fully_depreciated": fully_depreciated,
            })

            total_depreciation += fy_dep
            total_nbv += nbv

        return {
            "assets": asset_results,
            "total_depreciation": round(total_depreciation, 2),
            "total_nbv": round(total_nbv, 2),
        }

    def compute_deferred_tax(self, it_result: dict, ca_result: dict, tax_rate: float = 0.25) -> dict:
        """Compute deferred tax from timing differences between IT Act and Companies Act.

        IT > CA → DTL (Deferred Tax Liability): higher depreciation now, pay tax later
        CA > IT → DTA (Deferred Tax Asset): lower depreciation now, tax benefit later
        """
        it_total = it_result.get("total_depreciation", 0.0)
        ca_total = ca_result.get("total_depreciation", 0.0)

        timing_diff = round(it_total - ca_total, 2)

        if timing_diff > 0:
            deferred_tax_type = "DTL"  # IT depreciation higher
        elif timing_diff < 0:
            deferred_tax_type = "DTA"  # CA depreciation higher
        else:
            deferred_tax_type = "NIL"

        amount = round(abs(timing_diff) * tax_rate, 2)

        # Block-wise comparison
        block_comparison = []
        it_blocks = it_result.get("blocks", {})

        # Aggregate CA depreciation by block_key
        ca_by_block: dict[str, float] = {}
        for asset in ca_result.get("assets", []):
            bk = asset.get("block_key", "plant_machinery_general")
            ca_by_block[bk] = ca_by_block.get(bk, 0.0) + asset.get("fy_dep", 0.0)

        all_blocks = set(it_blocks.keys()) | set(ca_by_block.keys())
        for bk in sorted(all_blocks):
            it_dep = it_blocks.get(bk, {}).get("depreciation", 0.0)
            ca_dep = round(ca_by_block.get(bk, 0.0), 2)
            diff = round(it_dep - ca_dep, 2)
            block_comparison.append({
                "block": bk,
                "it_act_depreciation": it_dep,
                "ca_depreciation": ca_dep,
                "difference": diff,
                "type": "DTL" if diff > 0 else ("DTA" if diff < 0 else "NIL"),
            })

        return {
            "it_act_depreciation": it_total,
            "ca_depreciation": ca_total,
            "timing_difference": timing_diff,
            "tax_rate": tax_rate,
            "deferred_tax_amount": amount,
            "deferred_tax_type": deferred_tax_type,
            "block_wise_comparison": block_comparison,
        }
