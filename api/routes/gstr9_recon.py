"""GSTR-9 Annual Return Pre-Filing Reconciliation endpoints."""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4, UUID
from typing import Annotated, List

import pymupdf  # PyMuPDF

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.dependencies import get_current_user, require_starter
from api.rate_limit import limiter
from services.tabular_export_service import TabularExportService
from db.database import get_db
from db.models.core import User, GSTR9Reconciliation
from db.models.billing import CreditActionType
from services.credits_service import CreditsService
from services.storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/gstr9-recon", tags=["gstr9-reconciliation"])

BASE_SESSIONS_DIR = Path("user_sessions")
GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z][Z][0-9A-Z]$")
STALE_THRESHOLD = timedelta(minutes=2)


async def _expire_stale_recons(db: AsyncSession, user_id):
    """Mark processing records older than 2 min as error."""
    cutoff = datetime.now(timezone.utc) - STALE_THRESHOLD
    result = await db.execute(
        select(GSTR9Reconciliation).where(
            GSTR9Reconciliation.user_id == user_id,
            GSTR9Reconciliation.status == "processing",
            GSTR9Reconciliation.created_at < cutoff,
        )
    )
    stale = result.scalars().all()
    for r in stale:
        r.status = "error"
        r.result_json = {"error": "Timed out — processing took too long. Please retry."}
    if stale:
        await db.commit()
        logger.info(f"Expired {len(stale)} stale GSTR-9 recon(s) for user {user_id}")


def _recon_dir(user_id: str) -> Path:
    d = BASE_SESSIONS_DIR / user_id / "gstr9_recon"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _extract_text(file_path: str) -> str:
    """Extract text from a PDF using PyMuPDF."""
    try:
        doc = pymupdf.open(file_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        logger.error(f"Failed to extract text from {file_path}: {e}")
        return ""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/upload")
@limiter.limit("5/minute")
async def upload_gstr9_reconciliation(
    request: Request,
    gstin: str = Form(..., description="GSTIN (15-character)"),
    fy: str = Form(..., description="Financial year in YYYY-YY format (e.g. 2025-26)"),
    books_turnover: float = Form(0.0, description="Annual books turnover (optional)"),
    client_id: str = Form(None, description="Optional client UUID"),
    gstr1_files: List[UploadFile] = File(..., description="GSTR-1 monthly PDFs (up to 12)"),
    gstr3b_files: List[UploadFile] = File(..., description="GSTR-3B monthly PDFs (up to 12)"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Upload GSTR-1 and GSTR-3B PDFs, reconcile synchronously, return results."""
    from services.gstr9_reconciliation_service import GSTR9ReconciliationService, reconcile

    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Expire stale "processing" records before proceeding
    await _expire_stale_recons(db, current_user.id)

    # Validate GSTIN format
    gstin = gstin.upper().strip()
    if not GSTIN_REGEX.match(gstin):
        raise HTTPException(status_code=400, detail="Invalid GSTIN format (must be 15-char alphanumeric)")

    # Validate FY format
    if not re.match(r"^\d{4}-\d{2}$", fy):
        raise HTTPException(status_code=400, detail="FY must be in YYYY-YY format (e.g. 2025-26)")

    # Validate file counts
    if len(gstr1_files) > 12:
        raise HTTPException(status_code=400, detail="Maximum 12 GSTR-1 files allowed (one per month)")
    if len(gstr3b_files) > 12:
        raise HTTPException(status_code=400, detail="Maximum 12 GSTR-3B files allowed (one per month)")
    if len(gstr1_files) + len(gstr3b_files) > 24:
        raise HTTPException(status_code=400, detail="Maximum 24 files total allowed")

    # Validate all files are PDFs
    for f in gstr1_files + gstr3b_files:
        if f.filename and not f.filename.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail=f"Only PDF files are supported. Got: {f.filename}")

    # Deduct credits
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.GSTR9_RECON,
        db,
        description=f"GSTR-9 reconciliation: {gstin} FY {fy}",
    )

    # Save files via storage adapter
    storage = get_storage()
    recon_id = uuid4()

    gstr1_keys = []
    for f in gstr1_files:
        fname = f"{recon_id}_gstr1_{f.filename}"
        key = f"{current_user.id}/gstr9_recon/{fname}"
        content = await f.read()
        storage.save(key, content)
        gstr1_keys.append(key)

    gstr3b_keys = []
    for f in gstr3b_files:
        fname = f"{recon_id}_gstr3b_{f.filename}"
        key = f"{current_user.id}/gstr9_recon/{fname}"
        content = await f.read()
        storage.save(key, content)
        gstr3b_keys.append(key)

    # Create DB record
    recon = GSTR9Reconciliation(
        id=recon_id,
        user_id=current_user.id,
        client_id=UUID(client_id) if client_id else None,
        gstin=gstin,
        fy=fy,
        status="processing",
        books_turnover=books_turnover or 0.0,
    )
    db.add(recon)
    await db.commit()

    # --- Process synchronously (pipeline completes in <1s) ---
    try:
        service = GSTR9ReconciliationService()

        # Resolve local paths from storage keys
        logger.info(f"GSTR-9 Recon {recon_id}: {len(gstr1_keys)} GSTR-1, {len(gstr3b_keys)} GSTR-3B files")

        # Extract text and parse each PDF
        gstr1_months = []
        for key in gstr1_keys:
            fpath = storage.local_path(key)
            if not fpath:
                logger.warning(f"Could not resolve local path for {key}")
                continue
            text = await asyncio.to_thread(_extract_text, str(fpath))
            if text:
                parsed = await asyncio.to_thread(service.parse_monthly_data, text, "gstr1")
                if "error" not in parsed:
                    gstr1_months.append(parsed)
                else:
                    logger.warning(f"GSTR-1 parse error for {key}: {parsed.get('error')}")

        gstr3b_months = []
        for key in gstr3b_keys:
            fpath = storage.local_path(key)
            if not fpath:
                logger.warning(f"Could not resolve local path for {key}")
                continue
            text = await asyncio.to_thread(_extract_text, str(fpath))
            if text:
                parsed = await asyncio.to_thread(service.parse_monthly_data, text, "gstr3b")
                if "error" not in parsed:
                    gstr3b_months.append(parsed)
                else:
                    logger.warning(f"GSTR-3B parse error for {key}: {parsed.get('error')}")

        if not gstr1_months and not gstr3b_months:
            recon.status = "error"
            recon.result_json = {
                "error": "Could not extract data from any uploaded files. Please check the file formats."
            }
            await db.commit()
            return {
                "recon_id": str(recon_id),
                "status": "error",
                "detail": recon.result_json["error"],
            }

        # Run deterministic reconciliation
        books = books_turnover if books_turnover > 0 else None
        result_data = await asyncio.to_thread(reconcile, gstr1_months, gstr3b_months, books)

        # Update DB record
        summary = result_data["summary"]
        recon.gstr1_turnover = summary["gstr1_total_turnover"]
        recon.gstr3b_turnover = summary["gstr3b_total_turnover"]
        recon.gstr1_tax_paid = summary["gstr1_total_tax"]
        recon.gstr3b_tax_paid = summary["gstr3b_total_tax"]
        recon.discrepancy_count = summary["discrepancy_count"]
        recon.result_json = result_data
        recon.status = "completed"
        await db.commit()

        logger.info(
            f"GSTR-9 Recon {recon_id} completed: "
            f"{summary['discrepancy_count']} discrepancies, "
            f"status={summary['status']}"
        )

        return {
            "recon_id": str(recon_id),
            "status": "completed",
            "summary": summary,
            "discrepancy_count": summary["discrepancy_count"],
            "action_items_count": len(result_data.get("action_items", [])),
        }

    except Exception as e:
        logger.error(f"GSTR-9 Recon {recon_id} failed: {e}", exc_info=True)
        recon.status = "error"
        recon.result_json = {"error": str(e)}
        await db.commit()
        return {
            "recon_id": str(recon_id),
            "status": "error",
            "detail": str(e),
        }


@router.get("/history")
async def get_gstr9_history(
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
    client_id: str = Query(None, description="Filter by client UUID"),
):
    """Return past GSTR-9 reconciliations for the user (paginated)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Expire stale "processing" records before returning results
    await _expire_stale_recons(db, current_user.id)

    query = (
        select(GSTR9Reconciliation)
        .where(GSTR9Reconciliation.user_id == current_user.id)
    )
    if client_id:
        query = query.where(GSTR9Reconciliation.client_id == UUID(client_id))
    query = query.order_by(desc(GSTR9Reconciliation.created_at)).limit(limit).offset(offset)

    result = await db.execute(query)
    recons = result.scalars().all()

    return [
        {
            "recon_id": str(r.id),
            "gstin": r.gstin,
            "fy": r.fy,
            "status": r.status,
            "gstr1_turnover": r.gstr1_turnover,
            "gstr3b_turnover": r.gstr3b_turnover,
            "books_turnover": r.books_turnover,
            "discrepancy_count": r.discrepancy_count,
            "client_id": str(r.client_id) if r.client_id else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recons
    ]


@router.get("/{recon_id}/report")
async def generate_gstr9_report(
    recon_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a PDF report for the GSTR-9 reconciliation."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(GSTR9Reconciliation).where(
            GSTR9Reconciliation.id == UUID(recon_id),
            GSTR9Reconciliation.user_id == current_user.id,
        )
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=404, detail="GSTR-9 reconciliation not found")

    if recon.status != "completed" or not recon.result_json:
        raise HTTPException(status_code=400, detail="Reconciliation is not completed yet")

    pdf_buffer = await asyncio.to_thread(_generate_gstr9_pdf, recon)

    filename = f"gstr9_recon_{recon.gstin}_{recon.fy}_{str(recon.id)[:8]}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/{recon_id}/csv")
async def download_gstr9_csv(
    recon_id: str,
    sheet: str = Query("Monthly Comparison", description="Table to export: Monthly Comparison, Tax Reconciliation, ITC Summary, Action Items"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download a specific GSTR-9 reconciliation table as CSV."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(GSTR9Reconciliation).where(
            GSTR9Reconciliation.id == UUID(recon_id),
            GSTR9Reconciliation.user_id == current_user.id,
        )
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=404, detail="GSTR-9 reconciliation not found")
    if recon.status != "completed" or not recon.result_json:
        raise HTTPException(status_code=400, detail="Reconciliation is not completed yet")

    tables = _extract_gstr9_tables(recon.result_json)
    if sheet not in tables:
        raise HTTPException(status_code=400, detail=f"Invalid sheet '{sheet}'. Available: {', '.join(tables.keys())}")

    headers, rows = tables[sheet]
    csv_buffer = TabularExportService.to_csv(headers, rows)
    safe_sheet = sheet.lower().replace(" ", "_")
    filename = f"gstr9_{safe_sheet}_{recon.fy}_{str(recon.id)[:8]}.csv"
    return StreamingResponse(
        csv_buffer, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{recon_id}/excel")
async def download_gstr9_excel(
    recon_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download all GSTR-9 reconciliation tables as multi-sheet Excel."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(GSTR9Reconciliation).where(
            GSTR9Reconciliation.id == UUID(recon_id),
            GSTR9Reconciliation.user_id == current_user.id,
        )
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=404, detail="GSTR-9 reconciliation not found")
    if recon.status != "completed" or not recon.result_json:
        raise HTTPException(status_code=400, detail="Reconciliation is not completed yet")

    tables = _extract_gstr9_tables(recon.result_json)
    excel_buffer = TabularExportService.to_excel(tables)
    filename = f"gstr9_recon_{recon.fy}_{str(recon.id)[:8]}.xlsx"
    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{recon_id}")
async def get_gstr9_reconciliation(
    recon_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return GSTR-9 reconciliation result."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Expire stale "processing" records (including this one if applicable)
    await _expire_stale_recons(db, current_user.id)

    result = await db.execute(
        select(GSTR9Reconciliation).where(
            GSTR9Reconciliation.id == UUID(recon_id),
            GSTR9Reconciliation.user_id == current_user.id,
        )
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=404, detail="GSTR-9 reconciliation not found")

    response = {
        "recon_id": str(recon.id),
        "gstin": recon.gstin,
        "fy": recon.fy,
        "status": recon.status,
        "gstr1_turnover": recon.gstr1_turnover,
        "gstr3b_turnover": recon.gstr3b_turnover,
        "books_turnover": recon.books_turnover,
        "gstr1_tax_paid": recon.gstr1_tax_paid,
        "gstr3b_tax_paid": recon.gstr3b_tax_paid,
        "discrepancy_count": recon.discrepancy_count,
        "created_at": recon.created_at.isoformat() if recon.created_at else None,
    }

    if recon.status == "completed":
        response["result"] = recon.result_json
    elif recon.status == "error":
        response["error"] = recon.result_json.get("error", "Unknown error") if recon.result_json else "Unknown error"
    else:
        response["message"] = "GSTR-9 reconciliation is still processing. Please check back shortly."

    return response


# ---------------------------------------------------------------------------
# Table Extraction (for CSV/Excel export)
# ---------------------------------------------------------------------------

def _extract_gstr9_tables(result_json: dict) -> dict:
    """Extract all tables from GSTR-9 recon result_json for CSV/Excel export."""
    tables = {}

    # Monthly Comparison
    monthly = result_json.get("monthly_comparison", [])
    headers_m = ["Month", "GSTR1 Turnover", "GSTR3B Turnover", "Turnover Diff",
                 "GSTR1 Tax", "GSTR3B Tax", "Tax Diff", "Severity"]
    rows_m = [[
        m.get("month", ""),
        m.get("gstr1_turnover", 0), m.get("gstr3b_turnover", 0), m.get("turnover_diff", 0),
        m.get("gstr1_tax", 0), m.get("gstr3b_tax", 0), m.get("tax_diff", 0),
        m.get("severity", ""),
    ] for m in monthly]
    tables["Monthly Comparison"] = (headers_m, rows_m)

    # Tax Reconciliation (flat-key structure from reconcile())
    tax_recon = result_json.get("tax_reconciliation", {})
    headers_t = ["Tax Type", "GSTR-1 Amount", "GSTR-3B Amount", "Difference"]
    rows_t = []
    for tax_type in ["igst", "cgst", "sgst", "cess"]:
        rows_t.append([
            tax_type.upper(),
            tax_recon.get(f"gstr1_{tax_type}", 0),
            tax_recon.get(f"gstr3b_{tax_type}", 0),
            tax_recon.get(f"{tax_type}_diff", 0),
        ])
    # Total row
    rows_t.append([
        "TOTAL",
        tax_recon.get("gstr1_total_tax", 0),
        tax_recon.get("gstr3b_total_tax", 0),
        tax_recon.get("total_tax_gap", 0),
    ])
    tables["Tax Reconciliation"] = (headers_t, rows_t)

    # ITC Summary
    itc = result_json.get("itc_summary", {})
    if itc:
        headers_i = ["Item", "Value"]
        rows_i = [[k.replace("_", " ").title(), v] for k, v in itc.items()]
        tables["ITC Summary"] = (headers_i, rows_i)

    # Action Items
    actions = result_json.get("action_items", [])
    headers_a = ["Priority", "Category", "Description", "Financial Impact", "Recommendation"]
    rows_a = [[
        a.get("priority", ""),
        a.get("category", ""),
        a.get("description", ""),
        a.get("financial_impact", a.get("impact", "")),
        a.get("recommendation", a.get("action", "")),
    ] for a in actions]
    tables["Action Items"] = (headers_a, rows_a)

    return tables


# ---------------------------------------------------------------------------
# PDF Report Generation
# ---------------------------------------------------------------------------

def _generate_gstr9_pdf(recon: GSTR9Reconciliation) -> BytesIO:
    """Build PDF report from GSTR-9 reconciliation data using fpdf2."""
    from fpdf import FPDF
    from services.report_service import _sanitize_text

    result = recon.result_json
    summary = result.get("summary", {})
    monthly = result.get("monthly_comparison", [])
    tax_recon = result.get("tax_reconciliation", {})
    itc = result.get("itc_summary", {})
    actions = result.get("action_items", [])

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.add_page()

    effective_w = pdf.w - pdf.l_margin - pdf.r_margin

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "GSTR-9 Annual Return Pre-Filing Reconciliation", ln=True, align="C")
    pdf.ln(2)

    # Header
    pdf.set_font("Helvetica", "", 11)
    pdf.cell(0, 7, _sanitize_text(f"GSTIN: {recon.gstin}"), ln=True, align="C")
    pdf.cell(0, 7, _sanitize_text(f"Financial Year: {recon.fy}"), ln=True, align="C")
    if recon.books_turnover:
        pdf.cell(0, 7, _sanitize_text(f"Books Turnover: Rs. {recon.books_turnover:,.2f}"), ln=True, align="C")
    pdf.ln(5)

    # Summary stats
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "Summary", ln=True)
    pdf.set_font("Helvetica", "", 10)
    stats = [
        f"GSTR-1 Total Turnover: Rs. {summary.get('gstr1_total_turnover', 0):,.2f}",
        f"GSTR-3B Total Turnover: Rs. {summary.get('gstr3b_total_turnover', 0):,.2f}",
        f"Turnover Difference: Rs. {summary.get('turnover_diff', 0):,.2f}",
        f"GSTR-1 Total Tax: Rs. {summary.get('gstr1_total_tax', 0):,.2f}",
        f"GSTR-3B Total Tax: Rs. {summary.get('gstr3b_total_tax', 0):,.2f}",
        f"Tax Difference: Rs. {summary.get('tax_diff', 0):,.2f}",
        f"Discrepancies: {summary.get('discrepancy_count', 0)}",
        f"Months Analyzed: {summary.get('months_analyzed', 0)}",
        f"Status: {summary.get('status', 'N/A')}",
    ]
    for s in stats:
        pdf.cell(0, 6, _sanitize_text(s), ln=True)
    pdf.ln(5)

    # Monthly Comparison Table
    if monthly:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, "Monthly Comparison", ln=True)

        pdf.set_font("Helvetica", "B", 6.5)
        pdf.set_fill_color(240, 240, 240)
        col_w = [18, 22, 22, 22, 22, 22, 22, 18]
        headers = ["Month", "GSTR1 TO", "GSTR3B TO", "TO Diff", "GSTR1 Tax", "GSTR3B Tax", "Tax Diff", "Severity"]
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 5, h, border=1, fill=True)
        pdf.ln()

        severity_colors = {
            "matched": (0, 128, 0),
            "minor": (200, 150, 0),
            "major": (200, 0, 0),
        }

        pdf.set_font("Helvetica", "", 6)
        for m in monthly:
            month = str(m.get("month", ""))[:10]
            sev = str(m.get("severity", "")).lower()
            color = severity_colors.get(sev, (0, 0, 0))

            pdf.cell(col_w[0], 4, _sanitize_text(month), border=1)
            pdf.cell(col_w[1], 4, f"{m.get('gstr1_turnover', 0):,.0f}", border=1)
            pdf.cell(col_w[2], 4, f"{m.get('gstr3b_turnover', 0):,.0f}", border=1)
            pdf.cell(col_w[3], 4, f"{m.get('turnover_diff', 0):,.0f}", border=1)
            pdf.cell(col_w[4], 4, f"{m.get('gstr1_tax', 0):,.0f}", border=1)
            pdf.cell(col_w[5], 4, f"{m.get('gstr3b_tax', 0):,.0f}", border=1)
            pdf.cell(col_w[6], 4, f"{m.get('tax_diff', 0):,.0f}", border=1)
            pdf.set_text_color(*color)
            pdf.cell(col_w[7], 4, _sanitize_text(sev.upper()), border=1)
            pdf.set_text_color(0, 0, 0)
            pdf.ln()
        pdf.ln(5)

    # Tax Reconciliation (flat-key structure)
    if tax_recon:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, "Tax Reconciliation", ln=True)
        pdf.set_font("Helvetica", "", 10)
        for tax_type in ["igst", "cgst", "sgst", "cess"]:
            gstr1_val = tax_recon.get(f"gstr1_{tax_type}", 0)
            gstr3b_val = tax_recon.get(f"gstr3b_{tax_type}", 0)
            diff = tax_recon.get(f"{tax_type}_diff", 0)
            pdf.cell(0, 6, _sanitize_text(
                f"{tax_type.upper()}: GSTR-1 Rs. {gstr1_val:,.2f} | GSTR-3B Rs. {gstr3b_val:,.2f} | Diff Rs. {diff:,.2f}"
            ), ln=True)
        # Total row
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, _sanitize_text(
            f"TOTAL: GSTR-1 Rs. {tax_recon.get('gstr1_total_tax', 0):,.2f} | "
            f"GSTR-3B Rs. {tax_recon.get('gstr3b_total_tax', 0):,.2f} | "
            f"Gap Rs. {tax_recon.get('total_tax_gap', 0):,.2f}"
        ), ln=True)
        pdf.set_font("Helvetica", "", 10)
        gap_text = tax_recon.get("gap_interpretation", "")
        if gap_text:
            pdf.cell(0, 6, _sanitize_text(f"Interpretation: {gap_text}"), ln=True)
        pdf.ln(5)

    # ITC Summary
    if itc:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, "ITC Summary", ln=True)
        pdf.set_font("Helvetica", "", 10)
        for key, val in itc.items():
            label = key.replace("_", " ").title()
            if isinstance(val, (int, float)):
                pdf.cell(0, 6, _sanitize_text(f"{label}: Rs. {val:,.2f}"), ln=True)
            else:
                pdf.cell(0, 6, _sanitize_text(f"{label}: {val}"), ln=True)
        pdf.ln(5)

    # Action Items
    if actions:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, f"Action Items ({len(actions)})", ln=True)

        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(240, 240, 240)
        act_cols = [16, 25, 55, 30, 44]
        act_headers = ["Priority", "Category", "Description", "Impact", "Recommendation"]
        for i, h in enumerate(act_headers):
            pdf.cell(act_cols[i], 5, h, border=1, fill=True)
        pdf.ln()

        priority_colors = {"HIGH": (220, 50, 50), "MEDIUM": (200, 150, 0), "LOW": (100, 100, 100)}

        pdf.set_font("Helvetica", "", 6)
        for a in actions[:50]:
            priority = str(a.get("priority", "")).upper()
            color = priority_colors.get(priority, (0, 0, 0))

            pdf.set_text_color(*color)
            pdf.cell(act_cols[0], 4, _sanitize_text(priority), border=1)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(act_cols[1], 4, _sanitize_text(str(a.get("category", ""))[:16]), border=1)
            pdf.cell(act_cols[2], 4, _sanitize_text(str(a.get("description", ""))[:38]), border=1)
            impact = a.get("financial_impact", a.get("impact", ""))
            pdf.cell(act_cols[3], 4, _sanitize_text(str(impact)[:20]), border=1)
            rec = a.get("recommendation", a.get("action", ""))
            pdf.cell(act_cols[4], 4, _sanitize_text(str(rec)[:30]), border=1)
            pdf.ln()

        if len(actions) > 50:
            pdf.set_font("Helvetica", "I", 7)
            pdf.cell(0, 5, f"... and {len(actions) - 50} more action items", ln=True)
        pdf.ln(3)

    # Footer
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 10, _sanitize_text(
        f"Generated by Secure Doc-Intelligence | {datetime.utcnow().strftime('%Y-%m-%d')}"
    ), ln=True, align="C")

    buffer = BytesIO()
    buffer.write(pdf.output())
    buffer.seek(0)
    return buffer
