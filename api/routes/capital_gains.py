"""Capital Gains Analysis endpoints — upload broker PDF, compute Schedule CG, download report."""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4, UUID
from typing import Annotated
from io import BytesIO

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.dependencies import get_current_user, require_starter
from api.rate_limit import limiter
from db.database import get_db
from db.models.core import User, CapitalGainsAnalysis
from db.models.billing import CreditActionType
from services.credits_service import CreditsService
from services.storage import get_storage
from services.tabular_export_service import TabularExportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/capital-gains", tags=["capital-gains"])

BASE_SESSIONS_DIR = Path("user_sessions")

_FY_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")


def _cg_dir(user_id: str) -> Path:
    d = BASE_SESSIONS_DIR / user_id / "capital_gains"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_fy(fy: str) -> str:
    """Validate FY format like '2025-26'. Returns the FY string or raises."""
    m = _FY_PATTERN.match(fy)
    if not m:
        raise HTTPException(status_code=400, detail="FY must be in format YYYY-YY (e.g. 2025-26)")
    start_year = int(m.group(1))
    end_part = int(m.group(2))
    expected_end = (start_year + 1) % 100
    if end_part != expected_end:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid FY: {fy}. Second part should be {expected_end:02d}",
        )
    return fy


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/analyze")
@limiter.limit("5/minute")
async def analyze_capital_gains(
    request: Request,
    file: UploadFile = File(..., description="Broker capital gains PDF"),
    fy: str = Form(..., description="Financial year e.g. 2025-26"),
    client_id: str = Form(None, description="Optional client UUID"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Upload a broker capital gains statement PDF for Schedule CG computation."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    fy = _validate_fy(fy)

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Deduct credits
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.CAPITAL_GAINS_ANALYSIS,
        db,
        description=f"Capital gains analysis: FY {fy}",
    )

    # Save file via storage adapter
    storage = get_storage()
    analysis_id = uuid4()
    saved_filename = f"{analysis_id}_{file.filename}"
    storage_key = f"{current_user.id}/capital_gains/{saved_filename}"

    content = await file.read()
    storage.save(storage_key, content)

    # Extract text from PDF via PyMuPDF (needs local path)
    try:
        import pymupdf
        file_path = storage.local_path(storage_key)
        doc = pymupdf.open(str(file_path))
        raw_text = ""
        for page in doc:
            raw_text += page.get_text()
        doc.close()
    except Exception as e:
        logger.error(f"PDF text extraction failed: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to extract text from PDF: {e}")

    if not raw_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Could not extract any text from the PDF. It may be scanned/image-based.",
        )

    # Extract transactions + compute Schedule CG
    from services.capital_gains_service import CapitalGainsService
    svc = CapitalGainsService()

    try:
        transactions = await asyncio.to_thread(svc.extract_transactions, raw_text)
    except Exception as e:
        logger.error(f"Capital gains extraction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Transaction extraction failed: {e}")

    if not transactions:
        raise HTTPException(
            status_code=400,
            detail="Could not extract any capital gains transactions from the PDF. Check PDF format.",
        )

    result_data = await asyncio.to_thread(svc.compute_schedule_cg, transactions, fy)
    totals = result_data["totals"]
    itr_vals = result_data["itr_schedule_cg_values"]
    recon = result_data["reconciliation"]

    # Save to DB
    analysis = CapitalGainsAnalysis(
        id=analysis_id,
        user_id=current_user.id,
        client_id=UUID(client_id) if client_id else None,
        filename=saved_filename,
        fy=fy,
        status="completed",
        result_json=result_data,
        total_transactions=totals["total_transactions"],
        total_gain_loss=totals["total_gain_loss"],
        total_estimated_tax=totals["total_estimated_tax"],
        ltcg_equity_taxable=itr_vals["B5_ltcg_112A_taxable"],
        stcg_equity_net=itr_vals["B4_stcg_111A"],
        exemption_112a=itr_vals["B5_ltcg_112A_exempt"],
        reconciliation_warnings=len(recon["warnings"]),
    )
    db.add(analysis)
    await db.commit()

    return {
        "analysis_id": str(analysis_id),
        "status": "completed",
        "fy": fy,
        "total_transactions": totals["total_transactions"],
        "total_gain_loss": totals["total_gain_loss"],
        "total_estimated_tax": totals["total_estimated_tax"],
        "ltcg_equity_taxable": itr_vals["B5_ltcg_112A_taxable"],
        "stcg_equity_net": itr_vals["B4_stcg_111A"],
        "exemption_112a": itr_vals["B5_ltcg_112A_exempt"],
        "reconciliation_warnings": len(recon["warnings"]),
    }


@router.get("/history")
async def get_capital_gains_history(
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
    client_id: str = Query(None, description="Filter by client UUID"),
):
    """Return past capital gains analyses for the user (paginated)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    query = (
        select(CapitalGainsAnalysis)
        .where(CapitalGainsAnalysis.user_id == current_user.id)
    )
    if client_id:
        query = query.where(CapitalGainsAnalysis.client_id == UUID(client_id))
    query = query.order_by(desc(CapitalGainsAnalysis.created_at)).limit(limit).offset(offset)

    result = await db.execute(query)
    analyses = result.scalars().all()

    return [
        {
            "analysis_id": str(a.id),
            "filename": a.filename,
            "fy": a.fy,
            "status": a.status,
            "client_id": str(a.client_id) if a.client_id else None,
            "total_transactions": a.total_transactions,
            "total_gain_loss": a.total_gain_loss,
            "total_estimated_tax": a.total_estimated_tax,
            "ltcg_equity_taxable": a.ltcg_equity_taxable,
            "stcg_equity_net": a.stcg_equity_net,
            "exemption_112a": a.exemption_112a,
            "reconciliation_warnings": a.reconciliation_warnings,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in analyses
    ]


@router.get("/{analysis_id}/csv")
async def download_cg_csv(
    analysis_id: str,
    sheet: str = Query("Transactions", description="Table to export: Transactions, Schedule CG, ITR Values"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download a capital gains analysis table as CSV."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(CapitalGainsAnalysis).where(
            CapitalGainsAnalysis.id == UUID(analysis_id),
            CapitalGainsAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Capital gains analysis not found")
    if analysis.status != "completed" or not analysis.result_json:
        raise HTTPException(status_code=400, detail="Analysis is not completed yet")

    tables = _extract_cg_tables(analysis.result_json)
    if sheet not in tables:
        raise HTTPException(status_code=400, detail=f"Invalid sheet '{sheet}'. Available: {', '.join(tables.keys())}")

    headers, rows = tables[sheet]
    csv_buffer = TabularExportService.to_csv(headers, rows)
    safe_sheet = sheet.lower().replace(" ", "_")
    filename = f"capital_gains_{safe_sheet}_{analysis.fy}_{str(analysis.id)[:8]}.csv"
    return StreamingResponse(
        csv_buffer, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{analysis_id}/excel")
async def download_cg_excel(
    analysis_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download all capital gains tables as multi-sheet Excel."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(CapitalGainsAnalysis).where(
            CapitalGainsAnalysis.id == UUID(analysis_id),
            CapitalGainsAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Capital gains analysis not found")
    if analysis.status != "completed" or not analysis.result_json:
        raise HTTPException(status_code=400, detail="Analysis is not completed yet")

    tables = _extract_cg_tables(analysis.result_json)
    excel_buffer = TabularExportService.to_excel(tables)
    filename = f"capital_gains_{analysis.fy}_{str(analysis.id)[:8]}.xlsx"
    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{analysis_id}")
async def get_capital_gains_analysis(
    analysis_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return full capital gains analysis result."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(CapitalGainsAnalysis).where(
            CapitalGainsAnalysis.id == UUID(analysis_id),
            CapitalGainsAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Capital gains analysis not found")

    return {
        "analysis_id": str(analysis.id),
        "filename": analysis.filename,
        "fy": analysis.fy,
        "status": analysis.status,
        "total_transactions": analysis.total_transactions,
        "total_gain_loss": analysis.total_gain_loss,
        "total_estimated_tax": analysis.total_estimated_tax,
        "ltcg_equity_taxable": analysis.ltcg_equity_taxable,
        "stcg_equity_net": analysis.stcg_equity_net,
        "exemption_112a": analysis.exemption_112a,
        "reconciliation_warnings": analysis.reconciliation_warnings,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "result": analysis.result_json,
    }


@router.get("/{analysis_id}/report")
async def generate_capital_gains_report(
    analysis_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a PDF report for the capital gains analysis."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(CapitalGainsAnalysis).where(
            CapitalGainsAnalysis.id == UUID(analysis_id),
            CapitalGainsAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Capital gains analysis not found")

    if analysis.status != "completed" or not analysis.result_json:
        raise HTTPException(status_code=400, detail="Analysis is not completed yet")

    pdf_buffer = await asyncio.to_thread(_generate_capital_gains_pdf, analysis)

    filename = f"capital_gains_{analysis.fy}_{str(analysis.id)[:8]}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# PDF Report Generation
# ---------------------------------------------------------------------------

def _generate_capital_gains_pdf(analysis: CapitalGainsAnalysis) -> BytesIO:
    """Build PDF report from capital gains analysis data using fpdf2."""
    from fpdf import FPDF
    from services.report_service import _sanitize_text

    result = analysis.result_json
    schedule_cg = result.get("schedule_cg", {})
    totals = result.get("totals", {})
    recon = result.get("reconciliation", {})
    itr_vals = result.get("itr_schedule_cg_values", {})
    transactions = result.get("transactions_detail", [])

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.add_page()

    effective_w = pdf.w - pdf.l_margin - pdf.r_margin

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Capital Gains Analysis Report", ln=True, align="C")
    pdf.ln(2)

    # FY
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, _sanitize_text(f"Financial Year: {analysis.fy}"), ln=True, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, _sanitize_text(f"File: {analysis.filename}"), ln=True, align="C")
    pdf.ln(5)

    # Summary box
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    stats = [
        f"Total Transactions: {totals.get('total_transactions', 0)}",
        f"Total Sale Value: Rs. {totals.get('total_sale_value', 0):,.2f}",
        f"Total Purchase Value: Rs. {totals.get('total_purchase_value', 0):,.2f}",
        f"Net Gain/Loss: Rs. {totals.get('total_gain_loss', 0):,.2f}",
        f"Total Estimated Tax: Rs. {totals.get('total_estimated_tax', 0):,.2f}",
        f"Total Exemptions (Sec 112A): Rs. {totals.get('total_exemptions', 0):,.2f}",
    ]
    for s in stats:
        pdf.cell(0, 6, _sanitize_text(s), ln=True)
    pdf.ln(5)

    # Sec 112A Working
    ltcg_eq = schedule_cg.get("ltcg_equity", {})
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Section 112A - LTCG on Equity (Listed Shares / Equity MF)", ln=True)
    pdf.set_font("Helvetica", "", 10)
    working_112a = [
        f"Gross LTCG: Rs. {ltcg_eq.get('gross_gain', 0):,.2f}",
        f"Losses set off: Rs. {ltcg_eq.get('gross_loss', 0):,.2f}",
        f"Net LTCG: Rs. {ltcg_eq.get('net', 0):,.2f}",
        f"Exemption u/s 112A: Rs. {ltcg_eq.get('exemption', 0):,.2f}",
        f"Taxable LTCG: Rs. {ltcg_eq.get('taxable', 0):,.2f}",
        f"Estimated Tax: Rs. {ltcg_eq.get('tax', 0):,.2f}",
        f"Transactions: {ltcg_eq.get('count', 0)}",
    ]
    for w in working_112a:
        pdf.cell(0, 6, _sanitize_text(w), ln=True)
    pdf.ln(4)

    # Sec 111A Working
    stcg_eq = schedule_cg.get("stcg_equity", {})
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Section 111A - STCG on Equity", ln=True)
    pdf.set_font("Helvetica", "", 10)
    working_111a = [
        f"Gross STCG: Rs. {stcg_eq.get('gross_gain', 0):,.2f}",
        f"Losses: Rs. {stcg_eq.get('gross_loss', 0):,.2f}",
        f"Net STCG: Rs. {stcg_eq.get('net', 0):,.2f}",
        f"Estimated Tax: Rs. {stcg_eq.get('tax', 0):,.2f}",
        f"Transactions: {stcg_eq.get('count', 0)}",
    ]
    for w in working_111a:
        pdf.cell(0, 6, _sanitize_text(w), ln=True)
    pdf.ln(4)

    # Other gains table
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Other Capital Gains", ln=True)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(240, 240, 240)
    other_cols = [45, 20, 25, 25, 25, 25]
    other_headers = ["Category", "Count", "Gross Gain", "Losses", "Net", "Est. Tax"]
    for i, h in enumerate(other_headers):
        pdf.cell(other_cols[i], 6, h, border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for key in ["ltcg_other", "stcg_other", "debt_mf_gains"]:
        b = schedule_cg.get(key, {})
        labels = {"ltcg_other": "LTCG Other (112)", "stcg_other": "STCG Other (Slab)",
                  "debt_mf_gains": "Debt MF (50AA)"}
        pdf.cell(other_cols[0], 5, _sanitize_text(labels.get(key, key)), border=1)
        pdf.cell(other_cols[1], 5, str(b.get("count", 0)), border=1)
        pdf.cell(other_cols[2], 5, f"{b.get('gross_gain', 0):,.0f}", border=1)
        pdf.cell(other_cols[3], 5, f"{b.get('gross_loss', 0):,.0f}", border=1)
        pdf.cell(other_cols[4], 5, f"{b.get('net', 0):,.0f}", border=1)
        pdf.cell(other_cols[5], 5, f"{b.get('tax', 0):,.0f}", border=1)
        pdf.ln()
    pdf.ln(5)

    # Transaction table (up to 100 rows)
    if transactions:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, f"Transaction Detail ({len(transactions)} entries)", ln=True)

        pdf.set_font("Helvetica", "B", 6)
        pdf.set_fill_color(240, 240, 240)
        txn_cols = [35, 18, 18, 18, 18, 18, 18, 18, 12]
        txn_headers = ["Asset", "Buy Date", "Sell Date", "Buy Val", "Sell Val",
                       "Gain/Loss", "Holding", "Tax Rate", "Type"]
        for i, h in enumerate(txn_headers):
            pdf.cell(txn_cols[i], 5, h, border=1, fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 5.5)
        for txn in transactions[:100]:
            gain = txn.get("computed_gain_loss", 0)
            if gain >= 0:
                pdf.set_text_color(0, 100, 0)  # green
            else:
                pdf.set_text_color(200, 0, 0)  # red

            asset = str(txn.get("asset_name", ""))[:22]
            buy_dt = str(txn.get("purchase_date", "") or "")[:10]
            sell_dt = str(txn.get("sale_date", "") or "")[:10]
            buy_v = txn.get("purchase_value", 0)
            sell_v = txn.get("sale_value", 0)
            hold = f"{txn.get('holding_months', 0)}m"
            rate_d = txn.get("tax_info", {}).get("rate_display", "")
            hp_label = txn.get("tax_info", {}).get("holding_period_label", "")

            pdf.cell(txn_cols[0], 4, _sanitize_text(asset), border=1)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(txn_cols[1], 4, _sanitize_text(buy_dt), border=1)
            pdf.cell(txn_cols[2], 4, _sanitize_text(sell_dt), border=1)
            pdf.cell(txn_cols[3], 4, f"{buy_v:,.0f}", border=1)
            pdf.cell(txn_cols[4], 4, f"{sell_v:,.0f}", border=1)

            if gain >= 0:
                pdf.set_text_color(0, 100, 0)
            else:
                pdf.set_text_color(200, 0, 0)
            pdf.cell(txn_cols[5], 4, f"{gain:,.0f}", border=1)
            pdf.set_text_color(0, 0, 0)

            pdf.cell(txn_cols[6], 4, _sanitize_text(hold), border=1)
            pdf.cell(txn_cols[7], 4, _sanitize_text(rate_d), border=1)
            pdf.cell(txn_cols[8], 4, _sanitize_text(hp_label), border=1)
            pdf.ln()

        if len(transactions) > 100:
            pdf.set_font("Helvetica", "I", 7)
            pdf.cell(0, 5, f"... and {len(transactions) - 100} more transactions", ln=True)
        pdf.ln(3)

    # Reconciliation
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Broker Reconciliation", ln=True)
    pdf.set_font("Helvetica", "", 10)
    warnings = recon.get("warnings", [])
    if warnings:
        pdf.set_text_color(200, 150, 0)  # amber
        pdf.cell(0, 6, _sanitize_text(
            f"Checked: {recon.get('total_checked', 0)} | "
            f"Matched: {recon.get('matched', 0)} | "
            f"Warnings: {len(warnings)}"
        ), ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 8)
        for w in warnings[:20]:
            pdf.cell(0, 5, _sanitize_text(
                f"  {w.get('asset', '')}: Computed={w.get('computed', 0):,.2f} "
                f"vs Broker={w.get('broker', 0):,.2f} (diff={w.get('difference', 0):,.2f})"
            ), ln=True)
    else:
        pdf.set_text_color(0, 128, 0)  # green
        checked = recon.get("total_checked", 0)
        if checked > 0:
            pdf.cell(0, 6, _sanitize_text(
                f"All {checked} broker-reported gains matched (within Rs.1 tolerance)"
            ), ln=True)
        else:
            pdf.cell(0, 6, "No broker gain/loss figures available for reconciliation", ln=True)
        pdf.set_text_color(0, 0, 0)
    pdf.ln(5)

    # ITR Schedule CG Values
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "ITR Schedule CG - Ready-to-fill Values", ln=True)
    pdf.set_font("Helvetica", "", 10)
    itr_lines = [
        f"B3 — STCG (Other than 111A): Rs. {itr_vals.get('B3_stcg_other', 0):,.2f}",
        f"B4 — STCG u/s 111A: Rs. {itr_vals.get('B4_stcg_111A', 0):,.2f}",
        f"B5 — LTCG u/s 112A (Gross): Rs. {itr_vals.get('B5_ltcg_112A_gross', 0):,.2f}",
        f"B5 — LTCG u/s 112A (Exempt): Rs. {itr_vals.get('B5_ltcg_112A_exempt', 0):,.2f}",
        f"B5 — LTCG u/s 112A (Taxable): Rs. {itr_vals.get('B5_ltcg_112A_taxable', 0):,.2f}",
        f"B6 — LTCG u/s 112: Rs. {itr_vals.get('B6_ltcg_112', 0):,.2f}",
        f"Debt MF u/s 50AA: Rs. {itr_vals.get('debt_mf_50AA', 0):,.2f}",
    ]
    for line in itr_lines:
        pdf.cell(0, 6, _sanitize_text(line), ln=True)
    pdf.ln(5)

    # Disclaimer + footer
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, "Disclaimer", ln=True)
    pdf.set_font("Helvetica", "", 7)
    disclaimers = [
        "This report is generated based on the data extracted from the uploaded broker statement.",
        "Tax computations use Budget 2024 (Finance Act 2024) rates. Verify with your CA before filing.",
        "Slab-rate items (debt MF, unlisted STCG) are shown at 0% — apply your actual slab rate.",
        "Surcharge, cess (4% health & education), and rebate u/s 87A are NOT included in estimates.",
        "This is not tax advice. Consult a qualified Chartered Accountant for filing.",
    ]
    for d in disclaimers:
        pdf.cell(0, 4, _sanitize_text(d), ln=True)
    pdf.ln(3)

    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 10, _sanitize_text(
        f"Generated by Secure Doc-Intelligence | {datetime.utcnow().strftime('%Y-%m-%d')}"
    ), ln=True, align="C")

    buffer = BytesIO()
    buffer.write(pdf.output())
    buffer.seek(0)
    return buffer


# ---------------------------------------------------------------------------
# Table Extraction (for CSV/Excel export)
# ---------------------------------------------------------------------------

def _extract_cg_tables(result_json: dict) -> dict:
    """Extract all tables from capital gains result_json for CSV/Excel export."""
    tables = {}

    # Transactions detail
    txns = result_json.get("transactions_detail", [])
    headers_t = ["Asset", "ISIN", "Buy Date", "Sell Date", "Qty", "Purchase Value",
                 "Sale Value", "Gain/Loss", "Holding Months", "Tax Rate", "Type"]
    rows_t = [[
        t.get("asset_name", ""), t.get("isin", ""),
        t.get("purchase_date", ""), t.get("sale_date", ""),
        t.get("quantity", 0), t.get("purchase_value", 0), t.get("sale_value", 0),
        t.get("computed_gain_loss", 0), t.get("holding_months", 0),
        t.get("tax_info", {}).get("rate_display", ""),
        t.get("tax_info", {}).get("holding_period_label", ""),
    ] for t in txns]
    tables["Transactions"] = (headers_t, rows_t)

    # Schedule CG summary
    schedule_cg = result_json.get("schedule_cg", {})
    headers_s = ["Category", "Count", "Gross Gain", "Gross Loss", "Net", "Exemption", "Taxable", "Tax"]
    rows_s = []
    labels = {
        "ltcg_equity": "LTCG Equity (112A)",
        "stcg_equity": "STCG Equity (111A)",
        "ltcg_other": "LTCG Other (112)",
        "stcg_other": "STCG Other (Slab)",
        "debt_mf_gains": "Debt MF (50AA)",
    }
    for key, label in labels.items():
        b = schedule_cg.get(key, {})
        rows_s.append([label, b.get("count", 0), b.get("gross_gain", 0), b.get("gross_loss", 0),
                       b.get("net", 0), b.get("exemption", 0), b.get("taxable", 0), b.get("tax", 0)])
    tables["Schedule CG"] = (headers_s, rows_s)

    # ITR Values
    itr = result_json.get("itr_schedule_cg_values", {})
    headers_i = ["Field", "Value"]
    rows_i = [[k, v] for k, v in itr.items()]
    tables["ITR Values"] = (headers_i, rows_i)

    return tables
