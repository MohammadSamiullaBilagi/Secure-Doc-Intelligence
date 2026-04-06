"""GSTR-2B vs Purchase Register reconciliation endpoints."""

import asyncio
import logging
from pathlib import Path
from uuid import uuid4
from typing import Annotated
from io import BytesIO

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.dependencies import get_current_user, require_starter
from api.rate_limit import limiter
from db.database import get_db, AsyncSessionLocal
from db.models.core import User, GSTReconciliation
from db.models.billing import CreditActionType
from services.credits_service import CreditsService
from services.storage import get_storage
from services.tabular_export_service import TabularExportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gst-recon", tags=["gst-reconciliation"])

BASE_SESSIONS_DIR = Path("user_sessions")


def _recon_dir(user_id: str) -> Path:
    d = BASE_SESSIONS_DIR / user_id / "recon"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Background processing
# ---------------------------------------------------------------------------

async def process_reconciliation(recon_id: str):
    """Background task: extract records, reconcile, and store results."""
    from uuid import UUID
    from services.gstr2b_reconciliation_service import (
        extract_gstr2b_records,
        extract_purchase_register,
        reconcile,
    )

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(GSTReconciliation).where(GSTReconciliation.id == UUID(recon_id))
        )
        recon = result.scalar_one_or_none()
        if not recon:
            logger.error(f"GSTReconciliation {recon_id} not found")
            return

        try:
            storage = get_storage()
            gstr2b_key = f"{recon.user_id}/recon/{recon.gstr2b_filename}"
            pr_key = f"{recon.user_id}/recon/{recon.purchase_register_filename}"
            gstr2b_path = str(storage.local_path(gstr2b_key))
            pr_path = str(storage.local_path(pr_key))

            # Run extraction in thread pool (pandas / PyMuPDF can be slow)
            gstr2b_records = await asyncio.to_thread(extract_gstr2b_records, gstr2b_path)
            purchase_records = await asyncio.to_thread(extract_purchase_register, pr_path)

            if not gstr2b_records and not purchase_records:
                recon.status = "error"
                recon.result_json = {"error": "Could not extract any records from the uploaded files. Please check the file formats."}
                await db.commit()
                return

            # Run reconciliation
            result_data = await asyncio.to_thread(reconcile, gstr2b_records, purchase_records)

            summary = result_data["summary"]
            recon.result_json = result_data
            recon.matched_count = summary["matched_count"]
            recon.mismatched_count = summary["mismatch_count"]
            recon.missing_in_books_count = summary["missing_in_books_count"]
            recon.missing_in_gstr2b_count = summary["missing_in_gstr2b_count"]
            recon.total_itc_available = summary["itc_available"]
            recon.total_itc_at_risk = summary["itc_at_risk"]
            recon.total_itc_ineligible = summary.get("itc_ineligible", 0.0)
            recon.total_cess = summary.get("total_cess", 0.0)
            recon.duplicate_count = summary.get("duplicate_count", 0)
            recon.status = "completed"
            await db.commit()

            logger.info(
                f"Reconciliation {recon_id} completed: "
                f"{summary['matched_count']} matched, "
                f"{summary['mismatch_count']} mismatched, "
                f"{summary['missing_in_books_count']} missing in books, "
                f"{summary['missing_in_gstr2b_count']} missing in GSTR-2B"
            )

        except Exception as e:
            logger.error(f"Reconciliation {recon_id} failed: {e}")
            recon.status = "error"
            recon.result_json = {"error": str(e)}
            await db.commit()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload")
@limiter.limit("5/minute")
async def upload_reconciliation(
    request: Request,
    background_tasks: BackgroundTasks,
    period: str = Form(..., description="Tax period in YYYY-MM format"),
    gstr2b_file: UploadFile = File(..., description="GSTR-2B file (PDF/JSON/CSV/Excel)"),
    purchase_register_file: UploadFile = File(..., description="Purchase register file (PDF/CSV/Excel)"),
    client_id: str = Form(None, description="Optional client UUID"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Upload GSTR-2B and purchase register files for reconciliation."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Validate period format
    import re
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", period):
        raise HTTPException(status_code=400, detail="Period must be in YYYY-MM format (e.g. 2025-12)")

    # Deduct credits
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.GSTR_RECON,
        db,
        description=f"GSTR-2B reconciliation: {period}",
    )

    # Save files via storage adapter
    storage = get_storage()
    recon_id = uuid4()

    gstr2b_fname = f"{recon_id}_gstr2b_{gstr2b_file.filename}"
    pr_fname = f"{recon_id}_pr_{purchase_register_file.filename}"

    gstr2b_key = f"{current_user.id}/recon/{gstr2b_fname}"
    pr_key = f"{current_user.id}/recon/{pr_fname}"

    gstr2b_content = await gstr2b_file.read()
    storage.save(gstr2b_key, gstr2b_content)

    pr_content = await purchase_register_file.read()
    storage.save(pr_key, pr_content)

    # Create DB record
    from uuid import UUID
    recon = GSTReconciliation(
        id=recon_id,
        user_id=current_user.id,
        client_id=UUID(client_id) if client_id else None,
        period=period,
        status="processing",
        gstr2b_filename=gstr2b_fname,
        purchase_register_filename=pr_fname,
    )
    db.add(recon)
    await db.commit()

    # Launch background processing
    background_tasks.add_task(process_reconciliation, str(recon_id))

    return {
        "recon_id": str(recon_id),
        "status": "processing",
        "message": f"Reconciliation started for period {period}. Check status at GET /api/v1/gst-recon/{recon_id}",
    }


@router.get("/history")
async def get_reconciliation_history(
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
    client_id: str = Query(None, description="Filter by client UUID"),
):
    """Return past reconciliations for the user (paginated)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from uuid import UUID as _UUID
    query = (
        select(GSTReconciliation)
        .where(GSTReconciliation.user_id == current_user.id)
    )
    if client_id:
        query = query.where(GSTReconciliation.client_id == _UUID(client_id))
    query = query.order_by(desc(GSTReconciliation.created_at)).limit(limit).offset(offset)

    result = await db.execute(query)
    recons = result.scalars().all()

    return [
        {
            "recon_id": str(r.id),
            "period": r.period,
            "status": r.status,
            "client_id": str(r.client_id) if r.client_id else None,
            "gstr2b_filename": r.gstr2b_filename,
            "purchase_register_filename": r.purchase_register_filename,
            "matched_count": r.matched_count,
            "mismatched_count": r.mismatched_count,
            "missing_in_books_count": r.missing_in_books_count,
            "missing_in_gstr2b_count": r.missing_in_gstr2b_count,
            "total_itc_available": r.total_itc_available,
            "total_itc_at_risk": r.total_itc_at_risk,
            "total_itc_ineligible": getattr(r, "total_itc_ineligible", 0.0),
            "total_cess": getattr(r, "total_cess", 0.0),
            "duplicate_count": getattr(r, "duplicate_count", 0),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recons
    ]


@router.get("/{recon_id}/csv")
async def download_recon_csv(
    recon_id: str,
    sheet: str = Query("Value Mismatches", description="Table to export: Matched, Value Mismatches, Missing In Books, Missing In GSTR-2B"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download a single reconciliation table as CSV."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from uuid import UUID
    result = await db.execute(
        select(GSTReconciliation).where(
            GSTReconciliation.id == UUID(recon_id),
            GSTReconciliation.user_id == current_user.id,
        )
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=404, detail="Reconciliation not found")

    if recon.status != "completed" or not recon.result_json:
        raise HTTPException(status_code=400, detail="Reconciliation is not completed yet")

    tables = _extract_gst_recon_tables(recon.result_json)
    if sheet not in tables:
        available = list(tables.keys())
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sheet name '{sheet}'. Available sheets: {available}",
        )

    headers, rows = tables[sheet]
    csv_buffer = TabularExportService.to_csv(headers, rows)

    safe_sheet = sheet.replace(" ", "_").lower()
    filename = f"gstr2b_recon_{recon.period}_{safe_sheet}_{str(recon.id)[:8]}.csv"
    return StreamingResponse(
        csv_buffer,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{recon_id}/excel")
async def download_recon_excel(
    recon_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download all reconciliation tables as a multi-sheet Excel workbook."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from uuid import UUID
    result = await db.execute(
        select(GSTReconciliation).where(
            GSTReconciliation.id == UUID(recon_id),
            GSTReconciliation.user_id == current_user.id,
        )
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=404, detail="Reconciliation not found")

    if recon.status != "completed" or not recon.result_json:
        raise HTTPException(status_code=400, detail="Reconciliation is not completed yet")

    tables = _extract_gst_recon_tables(recon.result_json)
    excel_buffer = TabularExportService.to_excel(tables)

    filename = f"gstr2b_recon_{recon.period}_{str(recon.id)[:8]}.xlsx"
    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{recon_id}")
async def get_reconciliation(
    recon_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return reconciliation result (full data when completed)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from uuid import UUID
    result = await db.execute(
        select(GSTReconciliation).where(
            GSTReconciliation.id == UUID(recon_id),
            GSTReconciliation.user_id == current_user.id,
        )
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=404, detail="Reconciliation not found")

    response = {
        "recon_id": str(recon.id),
        "period": recon.period,
        "status": recon.status,
        "gstr2b_filename": recon.gstr2b_filename,
        "purchase_register_filename": recon.purchase_register_filename,
        "matched_count": recon.matched_count,
        "mismatched_count": recon.mismatched_count,
        "missing_in_books_count": recon.missing_in_books_count,
        "missing_in_gstr2b_count": recon.missing_in_gstr2b_count,
        "total_itc_available": recon.total_itc_available,
        "total_itc_at_risk": recon.total_itc_at_risk,
        "total_itc_ineligible": getattr(recon, "total_itc_ineligible", 0.0),
        "total_cess": getattr(recon, "total_cess", 0.0),
        "duplicate_count": getattr(recon, "duplicate_count", 0),
        "created_at": recon.created_at.isoformat() if recon.created_at else None,
    }

    if recon.status == "completed":
        response["result"] = recon.result_json
    elif recon.status == "error":
        response["error"] = recon.result_json.get("error", "Unknown error") if recon.result_json else "Unknown error"
    else:
        response["message"] = "Reconciliation is still processing. Please check back shortly."

    return response


@router.post("/{recon_id}/report")
async def generate_recon_report(
    recon_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate a PDF reconciliation report."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    from uuid import UUID
    result = await db.execute(
        select(GSTReconciliation).where(
            GSTReconciliation.id == UUID(recon_id),
            GSTReconciliation.user_id == current_user.id,
        )
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=404, detail="Reconciliation not found")

    if recon.status != "completed" or not recon.result_json:
        raise HTTPException(status_code=400, detail="Reconciliation is not completed yet")

    # Generate PDF
    pdf_buffer = await asyncio.to_thread(
        _generate_recon_pdf, recon, current_user, db
    )

    filename = f"gstr2b_recon_{recon.period}_{str(recon.id)[:8]}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _extract_gst_recon_tables(result_json: dict) -> dict:
    """Extract all tables from GST recon result_json for CSV/Excel export."""
    tables = {}

    # Matched invoices
    matched = result_json.get("matched", [])
    headers = ["GSTIN", "Invoice No", "Invoice Date (2B)", "Invoice Date (Books)",
               "Taxable Value", "Total Tax", "Cess", "ITC Eligible", "Remark"]
    rows = []
    for r in matched:
        rows.append([
            r.get("gstin_supplier", ""),
            r.get("invoice_no", ""),
            r.get("invoice_date_2b", r.get("invoice_date", "")),
            r.get("invoice_date_books", ""),
            r.get("taxable_value", r.get("taxable_value_2b", 0)),
            r.get("total_tax", r.get("total_tax_2b", 0)),
            r.get("cess_2b", r.get("cess", 0)),
            "Yes" if r.get("itc_eligible", True) else "No",
            r.get("remark", ""),
        ])
    tables["Matched"] = (headers, rows)

    # Value mismatches
    mismatches = result_json.get("value_mismatch", [])
    headers_mm = ["GSTIN", "Invoice No", "Taxable 2B", "Taxable Books",
                  "Tax 2B", "Tax Books", "Cess 2B", "Cess Books", "ITC Eligible", "Mismatch Type"]
    rows_mm = []
    for r in mismatches:
        rows_mm.append([
            r.get("gstin_supplier", ""),
            r.get("invoice_no", ""),
            r.get("taxable_value_2b", 0),
            r.get("taxable_value_books", 0),
            r.get("total_tax_2b", 0),
            r.get("total_tax_books", 0),
            r.get("cess_2b", 0),
            r.get("cess_books", 0),
            "Yes" if r.get("itc_eligible", True) else "No",
            ", ".join(r.get("mismatch_type", [])) if isinstance(r.get("mismatch_type"), list) else str(r.get("mismatch_type", "")),
        ])
    tables["Value Mismatches"] = (headers_mm, rows_mm)

    # Missing in books — records use plain keys (invoice_date, taxable_value, total_tax)
    missing_books = result_json.get("missing_in_books", [])
    headers_mb = ["GSTIN", "Invoice No", "Invoice Date", "Taxable Value", "Total Tax", "Cess", "ITC Eligible"]
    rows_mb = [[
        r.get("gstin_supplier", ""),
        r.get("invoice_no", ""),
        r.get("invoice_date", ""),
        r.get("taxable_value", 0),
        r.get("total_tax", 0),
        r.get("cess", 0),
        "Yes" if r.get("itc_eligible", True) else "No",
    ] for r in missing_books]
    tables["Missing In Books"] = (headers_mb, rows_mb)

    # Missing in GSTR-2B — records use plain keys
    missing_gstr2b = result_json.get("missing_in_gstr2b", [])
    headers_mg = ["GSTIN", "Invoice No", "Invoice Date", "Taxable Value", "Total Tax", "Cess"]
    rows_mg = [[
        r.get("gstin_supplier", ""),
        r.get("invoice_no", ""),
        r.get("invoice_date", ""),
        r.get("taxable_value", 0),
        r.get("total_tax", 0),
        r.get("cess", 0),
    ] for r in missing_gstr2b]
    tables["Missing In GSTR-2B"] = (headers_mg, rows_mg)

    # Potential matches (fuzzy matching)
    potential = result_json.get("potential_matches", [])
    if potential:
        headers_pm = ["GSTIN", "Invoice (GSTR-2B)", "Invoice (Books)", "Similarity %", "Confidence"]
        rows_pm = [[
            r.get("gstin", ""),
            r.get("invoice_2b", ""),
            r.get("invoice_books", ""),
            r.get("similarity", 0),
            r.get("confidence", ""),
        ] for r in potential]
        tables["Potential Matches"] = (headers_pm, rows_pm)

    # Duplicates
    dupes_2b = result_json.get("duplicates_2b", [])
    dupes_books = result_json.get("duplicates_books", [])
    if dupes_2b or dupes_books:
        headers_d = ["Source", "GSTIN", "Invoice No", "Action", "Taxable Value"]
        rows_d = []
        for d in dupes_2b:
            rows_d.append(["GSTR-2B", d.get("gstin", ""), d.get("invoice_no", ""),
                          d.get("action", ""), d.get("taxable_value", 0)])
        for d in dupes_books:
            rows_d.append(["Purchase Register", d.get("gstin", ""), d.get("invoice_no", ""),
                          d.get("action", ""), d.get("taxable_value", 0)])
        tables["Duplicates"] = (headers_d, rows_d)

    return tables


def _generate_recon_pdf(recon: GSTReconciliation, user, db) -> BytesIO:
    """Build PDF report from reconciliation data using fpdf2."""
    from fpdf import FPDF
    from services.report_service import _sanitize_text

    result = recon.result_json
    summary = result.get("summary", {})

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.add_page()

    effective_w = pdf.w - pdf.l_margin - pdf.r_margin

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "GSTR-2B vs Purchase Register Reconciliation", ln=True, align="C")
    pdf.ln(2)

    # Period
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _sanitize_text(f"Tax Period: {recon.period}"), ln=True, align="C")
    pdf.ln(5)

    # Summary stats
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)

    stats = [
        f"Total invoices in GSTR-2B: {summary.get('total_invoices_gstr2b', 0)}",
        f"Total invoices in books: {summary.get('total_invoices_books', 0)}",
        f"Matched: {summary.get('matched_count', 0)}",
        f"Mismatched: {summary.get('mismatch_count', 0)}",
        f"Missing in books: {summary.get('missing_in_books_count', 0)}",
        f"Missing in GSTR-2B: {summary.get('missing_in_gstr2b_count', 0)}",
        f"ITC Available: Rs. {summary.get('itc_available', 0):,.2f}",
        f"ITC At Risk: Rs. {summary.get('itc_at_risk', 0):,.2f}",
        f"ITC Ineligible: Rs. {summary.get('itc_ineligible', 0):,.2f}",
        f"ITC Mismatch Amount: Rs. {summary.get('itc_mismatch_amount', 0):,.2f}",
        f"Total Cess: Rs. {summary.get('total_cess', 0):,.2f}",
        f"Duplicates Found: {summary.get('duplicate_count', 0)}",
        f"Potential Matches (Fuzzy): {summary.get('potential_match_count', 0)}",
    ]
    for s in stats:
        pdf.cell(0, 6, _sanitize_text(s), ln=True)
    pdf.ln(5)

    # Helper to render a table section
    def _render_section(title: str, records: list, color: tuple):
        if not records:
            return
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*color)
        pdf.cell(0, 9, _sanitize_text(title), ln=True)
        pdf.set_text_color(0, 0, 0)

        # Table header
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(240, 240, 240)
        col_w = [35, 30, 22, 30, 25, 38]
        headers = ["GSTIN", "Invoice No", "Date", "Taxable Val", "Total Tax", "Remark"]
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 5, h, border=1, fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 6)
        for rec in records[:50]:  # Limit to 50 per section to avoid huge PDFs
            gstin = str(rec.get("gstin_supplier", ""))[:15]
            inv = str(rec.get("invoice_no", ""))[:15]
            date = str(rec.get("invoice_date", rec.get("invoice_date_2b", "")))[:10]
            taxable = rec.get("taxable_value", rec.get("taxable_value_2b", 0))
            tax = rec.get("total_tax", rec.get("total_tax_2b", 0))
            remark = str(rec.get("remark", ", ".join(rec.get("mismatch_type", []))))[:25]

            pdf.cell(col_w[0], 4, _sanitize_text(gstin), border=1)
            pdf.cell(col_w[1], 4, _sanitize_text(inv), border=1)
            pdf.cell(col_w[2], 4, _sanitize_text(date), border=1)
            pdf.cell(col_w[3], 4, _sanitize_text(f"{taxable:,.0f}"), border=1)
            pdf.cell(col_w[4], 4, _sanitize_text(f"{tax:,.0f}"), border=1)
            pdf.cell(col_w[5], 4, _sanitize_text(remark), border=1)
            pdf.ln()

        if len(records) > 50:
            pdf.set_font("Helvetica", "I", 7)
            pdf.cell(0, 5, f"... and {len(records) - 50} more records (see full JSON export)", ln=True)
        pdf.ln(3)

    _render_section(f"Matched Invoices ({summary.get('matched_count', 0)})",
                    result.get("matched", []), (0, 128, 0))
    _render_section(f"Value Mismatches ({summary.get('mismatch_count', 0)})",
                    result.get("value_mismatch", []), (200, 100, 0))
    _render_section(f"Missing in Books ({summary.get('missing_in_books_count', 0)})",
                    result.get("missing_in_books", []), (100, 100, 180))
    _render_section(f"Missing in GSTR-2B - ITC AT RISK ({summary.get('missing_in_gstr2b_count', 0)})",
                    result.get("missing_in_gstr2b", []), (200, 0, 0))

    # Potential matches (fuzzy)
    potential = result.get("potential_matches", [])
    if potential:
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(128, 0, 128)
        pdf.cell(0, 9, _sanitize_text(f"Potential Matches - Review Suggested ({len(potential)})"), ln=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(240, 240, 240)
        pm_cols = [35, 40, 40, 25, 25]
        pm_headers = ["GSTIN", "Invoice (2B)", "Invoice (Books)", "Similarity", "Confidence"]
        for i, h in enumerate(pm_headers):
            pdf.cell(pm_cols[i], 5, h, border=1, fill=True)
        pdf.ln()
        pdf.set_font("Helvetica", "", 6)
        for pm in potential[:20]:
            pdf.cell(pm_cols[0], 4, _sanitize_text(str(pm.get("gstin", ""))[:15]), border=1)
            pdf.cell(pm_cols[1], 4, _sanitize_text(str(pm.get("invoice_2b", ""))[:20]), border=1)
            pdf.cell(pm_cols[2], 4, _sanitize_text(str(pm.get("invoice_books", ""))[:20]), border=1)
            pdf.cell(pm_cols[3], 4, _sanitize_text(f"{pm.get('similarity', 0)}%"), border=1)
            pdf.cell(pm_cols[4], 4, _sanitize_text(str(pm.get("confidence", ""))), border=1)
            pdf.ln()
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
