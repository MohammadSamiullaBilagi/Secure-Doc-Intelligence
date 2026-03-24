"""Bank Statement Analysis endpoints — upload, view results, download PDF report."""

import asyncio
import logging
from datetime import date
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
from db.models.core import User, BankStatementAnalysis
from db.models.billing import CreditActionType
from services.credits_service import CreditsService
from services.storage import get_storage
from services.tabular_export_service import TabularExportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/bank-analysis", tags=["bank-analysis"])

BASE_SESSIONS_DIR = Path("user_sessions")


def _bank_dir(user_id: str) -> Path:
    d = BASE_SESSIONS_DIR / user_id / "bank"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload")
@limiter.limit("5/minute")
async def upload_bank_statement(
    request: Request,
    file: UploadFile = File(..., description="Bank statement PDF"),
    period_from: str = Form(..., description="Start date YYYY-MM-DD"),
    period_to: str = Form(..., description="End date YYYY-MM-DD"),
    client_id: str = Form(None, description="Optional client UUID"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Upload a bank statement PDF for statutory threshold analysis."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Validate dates
    try:
        fy_start = date.fromisoformat(period_from)
        fy_end = date.fromisoformat(period_to)
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    if fy_start >= fy_end:
        raise HTTPException(status_code=400, detail="period_from must be before period_to")

    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Deduct credits
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.BANK_ANALYSIS,
        db,
        description=f"Bank statement analysis: {period_from} to {period_to}",
    )

    # Save file via storage adapter
    storage = get_storage()
    analysis_id = uuid4()
    saved_filename = f"{analysis_id}_{file.filename}"
    storage_key = f"{current_user.id}/bank/{saved_filename}"

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
        raise HTTPException(status_code=400, detail="Could not extract any text from the PDF. It may be scanned/image-based.")

    logger.info(f"Bank statement text extracted: {len(raw_text)} chars from {file.filename}")

    # Extract transactions + analyze (synchronous — fast enough for single file)
    from services.bank_statement_service import BankStatementService
    svc = BankStatementService()

    try:
        transactions = await asyncio.to_thread(svc.extract_transactions, raw_text)
    except Exception as e:
        logger.error(f"Transaction extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Transaction extraction failed: {e}")

    if not transactions:
        logger.warning(f"No transactions extracted from {file.filename} ({len(raw_text)} chars of text)")
        raise HTTPException(status_code=400, detail="Could not extract any transactions from the bank statement. Check PDF format.")

    result_data = await asyncio.to_thread(svc.analyze, transactions, fy_start, fy_end)
    summary = result_data["summary"]

    # Save to DB
    analysis = BankStatementAnalysis(
        id=analysis_id,
        user_id=current_user.id,
        client_id=UUID(client_id) if client_id else None,
        filename=saved_filename,
        period_from=fy_start,
        period_to=fy_end,
        status="completed",
        result_json=result_data,
        total_transactions=summary["total_transactions"],
        total_debit=summary["total_debit"],
        total_credit=summary["total_credit"],
        flags_count=summary["flags_count"],
        high_flags=summary["high_flags"],
    )
    db.add(analysis)
    await db.commit()

    return {
        "analysis_id": str(analysis_id),
        "status": "completed",
        "summary": summary,
        "flags_count": summary["flags_count"],
        "high_flags": summary["high_flags"],
        "medium_flags": summary["medium_flags"],
        "low_flags": summary["low_flags"],
    }


@router.get("/history")
async def get_bank_analysis_history(
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
    client_id: str = Query(None, description="Filter by client UUID"),
):
    """Return past bank statement analyses for the user (paginated)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from uuid import UUID as _UUID
    query = (
        select(BankStatementAnalysis)
        .where(BankStatementAnalysis.user_id == current_user.id)
    )
    if client_id:
        query = query.where(BankStatementAnalysis.client_id == _UUID(client_id))
    query = query.order_by(desc(BankStatementAnalysis.created_at)).limit(limit).offset(offset)

    result = await db.execute(query)
    analyses = result.scalars().all()

    return [
        {
            "analysis_id": str(a.id),
            "filename": a.filename,
            "period_from": a.period_from.isoformat() if a.period_from else None,
            "period_to": a.period_to.isoformat() if a.period_to else None,
            "status": a.status,
            "client_id": str(a.client_id) if a.client_id else None,
            "total_transactions": a.total_transactions,
            "total_debit": a.total_debit,
            "total_credit": a.total_credit,
            "flags_count": a.flags_count,
            "high_flags": a.high_flags,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in analyses
    ]


@router.get("/{analysis_id}/csv")
async def download_bank_csv(
    analysis_id: str,
    sheet: str = Query("Flags", description="Table to export: Flags, Transactions"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download a bank analysis table as CSV."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(BankStatementAnalysis).where(
            BankStatementAnalysis.id == UUID(analysis_id),
            BankStatementAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Bank analysis not found")
    if analysis.status != "completed" or not analysis.result_json:
        raise HTTPException(status_code=400, detail="Analysis is not completed yet")

    tables = _extract_bank_tables(analysis.result_json)
    if sheet not in tables:
        raise HTTPException(status_code=400, detail=f"Invalid sheet '{sheet}'. Available: {', '.join(tables.keys())}")

    headers, rows = tables[sheet]
    csv_buffer = TabularExportService.to_csv(headers, rows)
    safe_sheet = sheet.lower().replace(" ", "_")
    filename = f"bank_{safe_sheet}_{str(analysis.id)[:8]}.csv"
    return StreamingResponse(
        csv_buffer, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{analysis_id}/excel")
async def download_bank_excel(
    analysis_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download all bank analysis tables as multi-sheet Excel."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(BankStatementAnalysis).where(
            BankStatementAnalysis.id == UUID(analysis_id),
            BankStatementAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Bank analysis not found")
    if analysis.status != "completed" or not analysis.result_json:
        raise HTTPException(status_code=400, detail="Analysis is not completed yet")

    tables = _extract_bank_tables(analysis.result_json)
    excel_buffer = TabularExportService.to_excel(tables)
    filename = f"bank_analysis_{str(analysis.id)[:8]}.xlsx"
    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{analysis_id}")
async def get_bank_analysis(
    analysis_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return full bank analysis result."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(BankStatementAnalysis).where(
            BankStatementAnalysis.id == UUID(analysis_id),
            BankStatementAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Bank analysis not found")

    return {
        "analysis_id": str(analysis.id),
        "filename": analysis.filename,
        "period_from": analysis.period_from.isoformat() if analysis.period_from else None,
        "period_to": analysis.period_to.isoformat() if analysis.period_to else None,
        "status": analysis.status,
        "total_transactions": analysis.total_transactions,
        "total_debit": analysis.total_debit,
        "total_credit": analysis.total_credit,
        "flags_count": analysis.flags_count,
        "high_flags": analysis.high_flags,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
        "result": analysis.result_json,
    }


@router.get("/{analysis_id}/report")
async def generate_bank_analysis_report(
    analysis_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a PDF report for the bank analysis."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(BankStatementAnalysis).where(
            BankStatementAnalysis.id == UUID(analysis_id),
            BankStatementAnalysis.user_id == current_user.id,
        )
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Bank analysis not found")

    if analysis.status != "completed" or not analysis.result_json:
        raise HTTPException(status_code=400, detail="Analysis is not completed yet")

    pdf_buffer = await asyncio.to_thread(_generate_bank_analysis_pdf, analysis)

    filename = f"bank_analysis_{analysis.period_from}_{str(analysis.id)[:8]}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# PDF Report Generation
# ---------------------------------------------------------------------------

def _generate_bank_analysis_pdf(analysis: BankStatementAnalysis) -> BytesIO:
    """Build PDF report from bank analysis data using fpdf2."""
    from fpdf import FPDF
    from services.report_service import _sanitize_text

    result = analysis.result_json
    summary = result.get("summary", {})
    flags = result.get("flags", [])
    transactions = result.get("transactions", [])

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.add_page()

    effective_w = pdf.w - pdf.l_margin - pdf.r_margin

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Bank Statement Analysis Report", ln=True, align="C")
    pdf.ln(2)

    # Period
    pdf.set_font("Helvetica", "", 11)
    period_str = f"Period: {analysis.period_from} to {analysis.period_to}"
    pdf.cell(0, 7, _sanitize_text(period_str), ln=True, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, _sanitize_text(f"File: {analysis.filename}"), ln=True, align="C")
    pdf.ln(5)

    # Summary stats
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)

    stats = [
        f"Total Transactions: {summary.get('total_transactions', 0)}",
        f"Total Debits: Rs. {summary.get('total_debit', 0):,.2f}",
        f"Total Credits: Rs. {summary.get('total_credit', 0):,.2f}",
        f"Cash Withdrawals (FY): Rs. {summary.get('cash_debit_total', 0):,.2f}",
        f"Cash Deposits (FY): Rs. {summary.get('cash_credit_total', 0):,.2f}",
        f"Interest Income (FY): Rs. {summary.get('interest_total', 0):,.2f}",
        f"Total Flags: {summary.get('flags_count', 0)} (HIGH: {summary.get('high_flags', 0)}, "
        f"MEDIUM: {summary.get('medium_flags', 0)}, LOW: {summary.get('low_flags', 0)})",
    ]
    for s in stats:
        pdf.cell(0, 6, _sanitize_text(s), ln=True)
    pdf.ln(5)

    # Flags table
    if flags:
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 9, f"Statutory Flags ({len(flags)})", ln=True)
        pdf.set_text_color(0, 0, 0)

        # Table header
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(240, 240, 240)
        col_w = [22, 14, 30, 65, 22, 18]
        headers = ["Category", "Severity", "Section", "Description", "Amount", "Date"]
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 5, h, border=1, fill=True)
        pdf.ln()

        severity_colors = {
            "HIGH": (220, 50, 50),
            "MEDIUM": (200, 150, 0),
            "LOW": (100, 100, 100),
        }

        pdf.set_font("Helvetica", "", 6)
        for flag in flags[:80]:
            cat = str(flag.get("category", ""))[:14]
            sev = flag.get("severity", "")
            section = str(flag.get("section", ""))[:18]
            desc = str(flag.get("description", ""))[:45]
            amt = flag.get("amount", 0)
            dt = str(flag.get("date", "") or "")[:10]

            color = severity_colors.get(sev, (0, 0, 0))
            pdf.set_text_color(*color)
            pdf.cell(col_w[0], 4, _sanitize_text(cat), border=1)
            pdf.cell(col_w[1], 4, _sanitize_text(sev), border=1)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(col_w[2], 4, _sanitize_text(section), border=1)
            pdf.cell(col_w[3], 4, _sanitize_text(desc), border=1)
            pdf.cell(col_w[4], 4, _sanitize_text(f"{amt:,.0f}"), border=1)
            pdf.cell(col_w[5], 4, _sanitize_text(dt), border=1)
            pdf.ln()

        if len(flags) > 80:
            pdf.set_font("Helvetica", "I", 7)
            pdf.cell(0, 5, f"... and {len(flags) - 80} more flags", ln=True)
        pdf.ln(3)

    # Transaction ledger (abbreviated)
    if transactions:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, f"Transaction Ledger ({len(transactions)} entries)", ln=True)

        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(240, 240, 240)
        ledger_cols = [18, 60, 25, 25, 25, 18]
        ledger_headers = ["Date", "Description", "Debit", "Credit", "Balance", "Mode"]
        for i, h in enumerate(ledger_headers):
            pdf.cell(ledger_cols[i], 5, h, border=1, fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 6)
        for txn in transactions[:100]:
            dt = str(txn.get("date", "") or "")[:10]
            desc = str(txn.get("description", ""))[:38]
            debit = txn.get("debit", 0)
            credit = txn.get("credit", 0)
            bal = txn.get("balance", 0)
            mode = str(txn.get("mode", ""))[:10]

            pdf.cell(ledger_cols[0], 4, _sanitize_text(dt), border=1)
            pdf.cell(ledger_cols[1], 4, _sanitize_text(desc), border=1)
            pdf.cell(ledger_cols[2], 4, _sanitize_text(f"{debit:,.0f}" if debit else ""), border=1)
            pdf.cell(ledger_cols[3], 4, _sanitize_text(f"{credit:,.0f}" if credit else ""), border=1)
            pdf.cell(ledger_cols[4], 4, _sanitize_text(f"{bal:,.0f}" if bal else ""), border=1)
            pdf.cell(ledger_cols[5], 4, _sanitize_text(mode), border=1)
            pdf.ln()

        if len(transactions) > 100:
            pdf.set_font("Helvetica", "I", 7)
            pdf.cell(0, 5, f"... and {len(transactions) - 100} more transactions", ln=True)
        pdf.ln(3)

    # Statutory reference footer
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, "Statutory Reference", ln=True)
    pdf.set_font("Helvetica", "", 7)
    refs = [
        "Sec 40A(3): Cash payment > Rs.10,000 to a single person in a day — disallowed as business expense",
        "Sec 269ST: Cash receipt >= Rs.2,00,000 from a single person/day/transaction — penalty u/s 271DA",
        "SFT: Cash deposits/withdrawals >= Rs.10,00,000 in FY in savings account — reported to Income Tax",
        "Sec 194A: Interest > Rs.40,000 (Rs.50,000 for senior citizens) — TDS applicable by bank",
    ]
    for ref in refs:
        pdf.cell(0, 4, _sanitize_text(ref), ln=True)
    pdf.ln(3)

    # Footer
    from datetime import datetime
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

def _extract_bank_tables(result_json: dict) -> dict:
    """Extract all tables from bank analysis result_json for CSV/Excel export."""
    tables = {}

    # Flags
    flags = result_json.get("flags", [])
    headers_f = ["Category", "Severity", "Section", "Description", "Amount", "Date"]
    rows_f = [[
        f.get("category", ""), f.get("severity", ""), f.get("section", ""),
        f.get("description", ""), f.get("amount", 0), f.get("date", ""),
    ] for f in flags]
    tables["Flags"] = (headers_f, rows_f)

    # Transactions
    txns = result_json.get("transactions", [])
    headers_t = ["Date", "Description", "Debit", "Credit", "Balance", "Mode"]
    rows_t = [[
        t.get("date", ""), t.get("description", ""),
        t.get("debit", 0), t.get("credit", 0), t.get("balance", 0), t.get("mode", ""),
    ] for t in txns]
    tables["Transactions"] = (headers_t, rows_t)

    return tables
