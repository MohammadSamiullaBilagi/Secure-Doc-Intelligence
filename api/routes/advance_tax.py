"""Advance Tax & Section 234 Interest Calculator endpoints — form-based, no file upload, no LLM."""

import logging
import re
from datetime import datetime
from uuid import uuid4, UUID
from typing import Annotated
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.dependencies import get_current_user, require_starter
from api.rate_limit import limiter
from db.database import get_db
from db.models.core import User, AdvanceTaxComputation
from db.models.billing import CreditActionType
from services.credits_service import CreditsService
from services.tabular_export_service import TabularExportService
from schemas.advance_tax_schema import (
    AdvanceTaxComputeRequest,
    RemainingInstalmentRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/advance-tax", tags=["advance-tax"])

_FY_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")


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

@router.post("/compute")
@limiter.limit("10/minute")
async def compute_advance_tax(
    request: Request,
    req: AdvanceTaxComputeRequest,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Compute Section 234A/B/C interest on advance tax instalments (2 credits)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    fy = _validate_fy(req.fy)

    if req.estimated_tax <= 0:
        raise HTTPException(status_code=400, detail="Estimated tax must be greater than 0")

    # Deduct credits
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.ADVANCE_TAX_CALC,
        db,
        description=f"Advance tax 234 interest: FY {fy}",
    )

    from services.advance_tax_service import AdvanceTaxService
    svc = AdvanceTaxService()

    instalments = [inst.model_dump() for inst in req.instalments_paid]
    result = svc.compute_234c_interest(
        estimated_tax=req.estimated_tax,
        fy=fy,
        instalments_paid=instalments,
        itr_filing_date=req.itr_filing_date,
        itr_due_date=req.itr_due_date,
    )

    # Save to DB
    computation_id = uuid4()
    computation = AdvanceTaxComputation(
        id=computation_id,
        user_id=current_user.id,
        client_id=UUID(req.client_id) if req.client_id else None,
        fy=fy,
        status="completed",
        estimated_tax=req.estimated_tax,
        total_interest=result["total_interest"],
        interest_234a=result["section_234a"]["interest"],
        interest_234b=result["section_234b"]["interest"],
        interest_234c=result["total_234c_interest"],
        result_json=result,
    )
    db.add(computation)
    await db.commit()

    return {
        "computation_id": str(computation_id),
        "status": "completed",
        "fy": fy,
        "estimated_tax": req.estimated_tax,
        "total_interest": result["total_interest"],
        "interest_234a": result["section_234a"]["interest"],
        "interest_234b": result["section_234b"]["interest"],
        "interest_234c": result["total_234c_interest"],
        "result": result,
        "created_at": computation.created_at.isoformat() if computation.created_at else None,
    }


@router.post("/remaining")
async def compute_remaining_instalments(
    req: RemainingInstalmentRequest,
    current_user: Annotated[User, Depends(require_starter)] = None,
):
    """Forward-looking planner: recommended payments for upcoming instalments (FREE)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    _validate_fy(req.fy)

    if req.estimated_annual_tax <= 0:
        raise HTTPException(status_code=400, detail="Estimated annual tax must be greater than 0")

    from services.advance_tax_service import AdvanceTaxService
    svc = AdvanceTaxService()

    result = svc.compute_remaining_instalment(
        estimated_annual_tax=req.estimated_annual_tax,
        fy=req.fy,
        paid_so_far=req.paid_so_far,
    )
    return result


@router.get("/history")
async def get_advance_tax_history(
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
    client_id: str = Query(None, description="Filter by client UUID"),
):
    """Return past advance tax computations for the user (paginated)."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    query = (
        select(AdvanceTaxComputation)
        .where(AdvanceTaxComputation.user_id == current_user.id)
    )
    if client_id:
        query = query.where(AdvanceTaxComputation.client_id == UUID(client_id))
    query = query.order_by(desc(AdvanceTaxComputation.created_at)).limit(limit).offset(offset)

    result = await db.execute(query)
    computations = result.scalars().all()

    return [
        {
            "computation_id": str(c.id),
            "fy": c.fy,
            "estimated_tax": c.estimated_tax,
            "total_interest": c.total_interest,
            "interest_234a": c.interest_234a,
            "interest_234b": c.interest_234b,
            "interest_234c": c.interest_234c,
            "client_id": str(c.client_id) if c.client_id else None,
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in computations
    ]


@router.get("/{computation_id}/csv")
async def download_advance_tax_csv(
    computation_id: str,
    sheet: str = Query("Instalments", description="Table to export: Instalments, Interest Summary"),
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download an advance tax computation table as CSV."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(AdvanceTaxComputation).where(
            AdvanceTaxComputation.id == UUID(computation_id),
            AdvanceTaxComputation.user_id == current_user.id,
        )
    )
    computation = result.scalar_one_or_none()
    if not computation:
        raise HTTPException(status_code=404, detail="Advance tax computation not found")
    if computation.status != "completed" or not computation.result_json:
        raise HTTPException(status_code=400, detail="Computation is not completed yet")

    tables = _extract_adv_tax_tables(computation.result_json)
    if sheet not in tables:
        raise HTTPException(status_code=400, detail=f"Invalid sheet '{sheet}'. Available: {', '.join(tables.keys())}")

    headers, rows = tables[sheet]
    csv_buffer = TabularExportService.to_csv(headers, rows)
    safe_sheet = sheet.lower().replace(" ", "_")
    filename = f"advance_tax_{safe_sheet}_{computation.fy}_{str(computation.id)[:8]}.csv"
    return StreamingResponse(
        csv_buffer, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{computation_id}/excel")
async def download_advance_tax_excel(
    computation_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Download all advance tax tables as multi-sheet Excel."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(AdvanceTaxComputation).where(
            AdvanceTaxComputation.id == UUID(computation_id),
            AdvanceTaxComputation.user_id == current_user.id,
        )
    )
    computation = result.scalar_one_or_none()
    if not computation:
        raise HTTPException(status_code=404, detail="Advance tax computation not found")
    if computation.status != "completed" or not computation.result_json:
        raise HTTPException(status_code=400, detail="Computation is not completed yet")

    tables = _extract_adv_tax_tables(computation.result_json)
    excel_buffer = TabularExportService.to_excel(tables)
    filename = f"advance_tax_{computation.fy}_{str(computation.id)[:8]}.xlsx"
    return StreamingResponse(
        excel_buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{computation_id}")
async def get_advance_tax_detail(
    computation_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Return full advance tax computation result."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(AdvanceTaxComputation).where(
            AdvanceTaxComputation.id == UUID(computation_id),
            AdvanceTaxComputation.user_id == current_user.id,
        )
    )
    computation = result.scalar_one_or_none()
    if not computation:
        raise HTTPException(status_code=404, detail="Advance tax computation not found")

    return {
        "computation_id": str(computation.id),
        "fy": computation.fy,
        "estimated_tax": computation.estimated_tax,
        "total_interest": computation.total_interest,
        "interest_234a": computation.interest_234a,
        "interest_234b": computation.interest_234b,
        "interest_234c": computation.interest_234c,
        "status": computation.status,
        "created_at": computation.created_at.isoformat() if computation.created_at else None,
        "result": computation.result_json,
    }


@router.get("/{computation_id}/report")
async def generate_advance_tax_report(
    computation_id: str,
    current_user: Annotated[User, Depends(require_starter)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a PDF working note for the advance tax computation."""
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(
        select(AdvanceTaxComputation).where(
            AdvanceTaxComputation.id == UUID(computation_id),
            AdvanceTaxComputation.user_id == current_user.id,
        )
    )
    computation = result.scalar_one_or_none()
    if not computation:
        raise HTTPException(status_code=404, detail="Advance tax computation not found")

    if computation.status != "completed" or not computation.result_json:
        raise HTTPException(status_code=400, detail="Computation is not completed yet")

    pdf_buffer = _generate_advance_tax_pdf(computation)

    filename = f"advance_tax_234_{computation.fy}_{str(computation.id)[:8]}.pdf"
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


# ---------------------------------------------------------------------------
# PDF Report Generation
# ---------------------------------------------------------------------------

def _generate_advance_tax_pdf(computation: AdvanceTaxComputation) -> BytesIO:
    """Build PDF working note from advance tax computation data using fpdf2."""
    from fpdf import FPDF
    from services.report_service import _sanitize_text

    result = computation.result_json
    instalments = result.get("instalments", [])
    s234b = result.get("section_234b", {})
    s234a = result.get("section_234a", {})

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.add_page()

    effective_w = pdf.w - pdf.l_margin - pdf.r_margin

    # --- Section 1: Header ---
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Advance Tax & Section 234 Interest Working Note", ln=True, align="C")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 8, _sanitize_text(f"Financial Year: {computation.fy}"), ln=True, align="C")
    pdf.cell(0, 8, _sanitize_text(f"Estimated Tax Liability: Rs. {computation.estimated_tax:,.2f}"), ln=True, align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, _sanitize_text(
        f"Computed on: {computation.created_at.strftime('%Y-%m-%d') if computation.created_at else 'N/A'}"
    ), ln=True, align="C")
    pdf.ln(5)

    # --- Section 2: Instalment-wise 234C Breakdown ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "1. Section 234C - Interest on Deferment of Advance Tax", ln=True)
    pdf.ln(2)

    if instalments:
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_fill_color(240, 240, 240)
        col_w = [28, 22, 26, 22, 26, 22, 26]
        headers = ["Instalment", "Due Date", "Required Cum.", "Paid", "Actual Cum.", "Shortfall", "234C Interest"]
        for i, h in enumerate(headers):
            pdf.cell(col_w[i], 6, h, border=1, fill=True)
        pdf.ln()

        pdf.set_font("Helvetica", "", 7)
        for inst in instalments:
            pdf.cell(col_w[0], 5, _sanitize_text(inst.get("instalment", "")), border=1)
            pdf.cell(col_w[1], 5, inst.get("due_date", ""), border=1)
            pdf.cell(col_w[2], 5, f"{inst.get('required_cumulative', 0):,.2f}", border=1)
            pdf.cell(col_w[3], 5, f"{inst.get('paid_amount', 0):,.2f}", border=1)
            pdf.cell(col_w[4], 5, f"{inst.get('actual_cumulative', 0):,.2f}", border=1)
            pdf.cell(col_w[5], 5, f"{inst.get('shortfall', 0):,.2f}", border=1)
            pdf.cell(col_w[6], 5, f"{inst.get('interest_234c', 0):,.2f}", border=1)
            pdf.ln()

        # Totals row
        pdf.set_font("Helvetica", "B", 7)
        pdf.cell(sum(col_w[:6]), 5, "Total Section 234C Interest", border=1, fill=True)
        pdf.cell(col_w[6], 5, f"{result.get('total_234c_interest', 0):,.2f}", border=1, fill=True)
        pdf.ln()
    pdf.ln(5)

    # --- Section 3: Section 234B ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "2. Section 234B - Interest on Default in Payment of Advance Tax", ln=True)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)

    if s234b.get("applicable"):
        lines_b = [
            f"Total Advance Tax Paid: Rs. {s234b.get('total_advance_paid', 0):,.2f}",
            f"90% of Estimated Tax (Threshold): Rs. {s234b.get('threshold_90pct', 0):,.2f}",
            f"Shortfall: Rs. {s234b.get('shortfall', 0):,.2f}",
            f"Interest Period: {s234b.get('months', 0)} month(s) (Apr 1 of AY to ITR filing date)",
            f"Interest @ 1% p.m.: Rs. {s234b.get('interest', 0):,.2f}",
        ]
    else:
        lines_b = [
            f"Total Advance Tax Paid: Rs. {s234b.get('total_advance_paid', 0):,.2f}",
            f"90% of Estimated Tax (Threshold): Rs. {s234b.get('threshold_90pct', 0):,.2f}",
            "Result: Advance tax paid >= 90% of estimated tax. Section 234B NOT applicable.",
        ]
    for line in lines_b:
        pdf.cell(0, 7, _sanitize_text(line), ln=True)
    pdf.ln(5)

    # --- Section 4: Section 234A ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "3. Section 234A - Interest for Late Filing of ITR", ln=True)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 10)

    if s234a.get("applicable"):
        lines_a = [
            f"ITR Due Date: {s234a.get('itr_due_date', 'N/A')}",
            f"ITR Filing Date: {s234a.get('itr_filing_date', 'N/A')}",
            f"Assessed Tax (Tax - Advance Tax Paid): Rs. {s234a.get('assessed_tax', 0):,.2f}",
            f"Interest Period: {s234a.get('months', 0)} month(s)",
            f"Interest @ 1% p.m.: Rs. {s234a.get('interest', 0):,.2f}",
        ]
    else:
        lines_a = [
            f"ITR Due Date: {s234a.get('itr_due_date', 'N/A')}",
            f"ITR Filing Date: {s234a.get('itr_filing_date', 'N/A')}",
            "Result: ITR filed on or before due date. Section 234A NOT applicable.",
        ]
    for line in lines_a:
        pdf.cell(0, 7, _sanitize_text(line), ln=True)
    pdf.ln(5)

    # --- Section 5: Total Interest Summary ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "4. Total Interest Summary", ln=True)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 11)

    summary_lines = [
        f"Section 234A Interest: Rs. {s234a.get('interest', 0):,.2f}",
        f"Section 234B Interest: Rs. {s234b.get('interest', 0):,.2f}",
        f"Section 234C Interest: Rs. {result.get('total_234c_interest', 0):,.2f}",
    ]
    for line in summary_lines:
        pdf.cell(0, 8, _sanitize_text(line), ln=True)

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, _sanitize_text(
        f"TOTAL INTEREST LIABILITY: Rs. {result.get('total_interest', 0):,.2f}"
    ), ln=True)
    pdf.ln(3)

    # Planning note
    planning_note = result.get("planning_note", "")
    if planning_note:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 8, "Planning Note", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(effective_w, 5, _sanitize_text(planning_note))
    pdf.ln(5)

    # Disclaimer
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 8, "Disclaimer", ln=True)
    pdf.set_font("Helvetica", "", 7)
    disclaimers = [
        "This working note computes interest u/s 234A, 234B, and 234C based on user-provided data.",
        "Interest is computed at 1% per month (simple interest) as per the Income Tax Act, 1961.",
        "Section 234C March exception: no interest if Q4 shortfall is within 10% of estimated tax.",
        "Section 234B: applicable only if advance tax paid is less than 90% of assessed tax.",
        "Verify all computations with your Chartered Accountant before filing.",
        "This is not professional advice. Consult a qualified CA for compliance.",
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

def _extract_adv_tax_tables(result_json: dict) -> dict:
    """Extract all tables from advance tax result_json for CSV/Excel export."""
    tables = {}

    # Instalments
    instalments = result_json.get("instalments", [])
    headers_i = ["Instalment", "Due Date", "Required Cumulative", "Paid Amount",
                 "Actual Cumulative", "Shortfall", "234C Interest"]
    rows_i = [[
        i.get("instalment", ""), i.get("due_date", ""),
        i.get("required_cumulative", 0), i.get("paid_amount", 0),
        i.get("actual_cumulative", 0), i.get("shortfall", 0), i.get("interest_234c", 0),
    ] for i in instalments]
    tables["Instalments"] = (headers_i, rows_i)

    # Interest Summary
    s234a = result_json.get("section_234a", {})
    s234b = result_json.get("section_234b", {})
    headers_s = ["Section", "Applicable", "Amount", "Details"]
    rows_s = [
        ["234A", "Yes" if s234a.get("applicable") else "No", s234a.get("interest", 0),
         f"{s234a.get('months', 0)} months" if s234a.get("applicable") else "Filed on time"],
        ["234B", "Yes" if s234b.get("applicable") else "No", s234b.get("interest", 0),
         f"Shortfall: {s234b.get('shortfall', 0):,.2f}" if s234b.get("applicable") else "Paid >= 90%"],
        ["234C", "Yes", result_json.get("total_234c_interest", 0), "Instalment-wise deferment"],
        ["TOTAL", "", result_json.get("total_interest", 0), ""],
    ]
    tables["Interest Summary"] = (headers_s, rows_s)

    return tables
