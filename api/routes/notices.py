import shutil
import logging
from pathlib import Path
from uuid import uuid4, UUID

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Annotated, List, Optional

from api.dependencies import require_professional, get_current_user
from api.rate_limit import limiter
from db.database import get_db
from db.models.core import User, UserPreference
from db.models.notices import NoticeJob
from db.models.clients import Client
from db.models.billing import CreditActionType
from services.credits_service import CreditsService
from services.notice_service import NoticeService
from services.report_service import ReportService
from services.email_service import EmailService
from services.storage import get_storage
from ingestion import DocumentProcessor
from db.models.core import Blueprint as BlueprintModel
from schemas.notice_schema import (
    NoticeUploadResponse, NoticeDetailResponse, NoticeListItem,
    NoticeApproveRequest, NoticeRegenerateRequest,
    NOTICE_TYPE_DISPLAY, VALID_NOTICE_TYPES, CUSTOM_NOTICE_TYPE,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notices", tags=["notices"])

BASE_SESSIONS_DIR = Path("user_sessions")


def _get_notice_paths(user_id: str):
    """Get session paths for a user's notice processing."""
    session_dir = BASE_SESSIONS_DIR / str(user_id)
    data_dir = session_dir / "data"
    db_dir = session_dir / "vector_db"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, db_dir


@router.post("/upload", response_model=NoticeUploadResponse)
@limiter.limit("5/minute")
async def upload_notice(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(require_professional)],
    db: AsyncSession = Depends(get_db),
    notice_file: UploadFile = File(...),
    notice_type: str = Form(...),
    client_id: Optional[str] = Form(None),
    notice_blueprint_id: Optional[str] = Form(None),
    supporting_files: List[UploadFile] = File(default=[]),
):
    """Upload a notice PDF + optional supporting docs. Triggers background draft generation."""
    # Resolve notice type: custom blueprint or system type
    resolved_blueprint_name = None
    if notice_blueprint_id:
        # Custom blueprint mode — validate it exists and user has access
        bp_result = await db.execute(
            select(BlueprintModel).where(
                BlueprintModel.id == UUID(notice_blueprint_id),
                BlueprintModel.category == "notice",
                (BlueprintModel.user_id == current_user.id) | (BlueprintModel.user_id.is_(None)),
            )
        )
        bp = bp_result.scalar_one_or_none()
        if not bp:
            raise HTTPException(400, "Custom notice blueprint not found or access denied")
        notice_type = CUSTOM_NOTICE_TYPE
        resolved_blueprint_name = bp.name
    elif notice_type not in VALID_NOTICE_TYPES:
        raise HTTPException(400, f"Invalid notice_type. Must be one of: {', '.join(VALID_NOTICE_TYPES)}")

    # Deduct credits
    display_name = resolved_blueprint_name or NOTICE_TYPE_DISPLAY.get(notice_type, notice_type)
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.NOTICE_REPLY,
        db,
        description=f"Notice reply: {display_name}",
    )

    data_dir, db_dir = _get_notice_paths(str(current_user.id))
    storage = get_storage()

    # Save notice file via storage adapter
    notice_filename = notice_file.filename or "notice.pdf"
    notice_key = f"{current_user.id}/data/{notice_filename}"
    notice_content = await notice_file.read()
    storage.save(notice_key, notice_content)
    # Ensure local copy exists for DocumentProcessor ingestion
    storage.local_path(notice_key)

    # Save supporting files via storage adapter
    supporting_doc_names = []
    for sf in supporting_files:
        if sf.filename:
            sf_key = f"{current_user.id}/data/{sf.filename}"
            sf_content = await sf.read()
            storage.save(sf_key, sf_content)
            # Ensure local copy exists for DocumentProcessor ingestion
            storage.local_path(sf_key)
            supporting_doc_names.append(sf.filename)

    # Ingest all files into vector store (append, don't wipe existing embeddings)
    try:
        from langchain_openai import OpenAIEmbeddings
        from langchain_community.vectorstores import Chroma

        processor = DocumentProcessor(data_dir=str(data_dir), db_dir=str(db_dir))
        target_files = [notice_filename] + supporting_doc_names
        docs = processor.extract_text_from_pdfs(only_files=target_files)
        if docs:
            chunks = processor.text_splitter.split_documents(docs)
            for i, chunk in enumerate(chunks):
                chunk.metadata["chunk_id"] = f"notice_chunk_{i}"
                chunk.metadata["document_id"] = chunk.metadata.get("source", "unknown")
            embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
            Chroma.from_documents(
                documents=chunks,
                embedding=embeddings,
                persist_directory=str(db_dir),
            )
            logger.info(f"Ingested {len(chunks)} chunks from {len(docs)} notice pages")
        else:
            logger.warning(f"No text extracted from notice files: {target_files}")
    except Exception as e:
        logger.error(f"Failed to ingest notice files: {e}")

    # Create NoticeJob
    job_id = uuid4()
    thread_id = f"notice-{current_user.id}-{job_id}"

    parsed_client_id = None
    if client_id:
        try:
            from uuid import UUID
            parsed_client_id = UUID(client_id)
        except ValueError:
            pass

    notice_job = NoticeJob(
        id=job_id,
        user_id=current_user.id,
        client_id=parsed_client_id,
        notice_type=notice_type,
        notice_document_name=notice_filename,
        supporting_documents=supporting_doc_names,
        status="uploaded",
        langgraph_thread_id=thread_id,
        notice_blueprint_id=UUID(notice_blueprint_id) if notice_blueprint_id else None,
        notice_blueprint_name=resolved_blueprint_name,
    )
    db.add(notice_job)
    await db.commit()

    # Launch background processing
    background_tasks.add_task(
        NoticeService.process_notice,
        str(job_id),
        str(db_dir),
        str(data_dir),
        thread_id,
    )

    return NoticeUploadResponse(
        notice_job_id=str(job_id),
        status="uploaded",
        message=f"Notice uploaded. Draft generation started. Track via thread_id: {thread_id}",
    )


@router.get("")
async def list_notices(
    current_user: Annotated[User, Depends(require_professional)],
    db: AsyncSession = Depends(get_db),
):
    """List all notice jobs for the current user."""
    from datetime import datetime, timedelta

    result = await db.execute(
        select(NoticeJob)
        .where(NoticeJob.user_id == current_user.id)
        .order_by(NoticeJob.created_at.desc())
    )
    jobs = result.scalars().all()

    # Auto-mark jobs stuck in "extracting" for >10 minutes as error (orphaned jobs)
    stale_threshold = datetime.utcnow() - timedelta(minutes=10)
    any_stale = False
    for j in jobs:
        if j.status == "extracting" and j.updated_at and j.updated_at.replace(tzinfo=None) < stale_threshold:
            j.status = "error"
            any_stale = True
    if any_stale:
        await db.commit()

    return [
        {
            "id": str(j.id),
            "notice_type": j.notice_type,
            "notice_type_display": j.notice_blueprint_name or NOTICE_TYPE_DISPLAY.get(j.notice_type, j.notice_type),
            "notice_document_name": j.notice_document_name,
            "status": j.status,
            "client_id": str(j.client_id) if j.client_id else None,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        }
        for j in jobs
    ]


@router.get("/{notice_id}")
async def get_notice_detail(
    notice_id: str,
    current_user: Annotated[User, Depends(require_professional)],
    db: AsyncSession = Depends(get_db),
):
    """Get full notice job detail including draft reply."""
    result = await db.execute(
        select(NoticeJob).where(
            NoticeJob.id == UUID(notice_id),
            NoticeJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Notice job not found")

    return {
        "id": str(job.id),
        "notice_type": job.notice_type,
        "notice_type_display": job.notice_blueprint_name or NOTICE_TYPE_DISPLAY.get(job.notice_type, job.notice_type),
        "notice_document_name": job.notice_document_name,
        "supporting_documents": job.supporting_documents,
        "status": job.status,
        "extracted_data": job.extracted_data,
        "draft_reply": job.draft_reply,
        "draft_reply_html": job.draft_reply.replace("\n", "<br>") if job.draft_reply else None,
        "final_reply": job.final_reply,
        "final_reply_html": job.final_reply.replace("\n", "<br>") if job.final_reply else None,
        "client_id": str(job.client_id) if job.client_id else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


@router.post("/{notice_id}/approve")
async def approve_notice(
    notice_id: str,
    request: NoticeApproveRequest,
    current_user: Annotated[User, Depends(require_professional)],
    db: AsyncSession = Depends(get_db),
):
    """Approve the draft reply. Optionally provide an edited version."""
    result = await db.execute(
        select(NoticeJob).where(
            NoticeJob.id == UUID(notice_id),
            NoticeJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Notice job not found")

    if job.status not in ("draft_ready", "approved"):
        raise HTTPException(400, f"Cannot approve a notice in '{job.status}' status. Wait for draft to be ready.")

    # Use edited reply if provided, otherwise use the AI draft
    job.final_reply = request.edited_reply if request.edited_reply else job.draft_reply
    job.status = "approved"
    await db.commit()

    # --- Send email to subscriber's preferred email + client email ---
    email_sent = False
    email_error = None

    # Always fetch CA branding & subscriber preferred email
    pref_result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    prefs = pref_result.scalar_one_or_none()
    ca_name = prefs.ca_name if prefs else None
    firm_name = prefs.firm_name if prefs else None
    reply_to = prefs.firm_email if prefs else None
    subscriber_email = (prefs.preferred_email if prefs else None) or current_user.email

    # Build recipient list: subscriber always gets a copy
    recipients = [subscriber_email]

    if job.client_id:
        client_result = await db.execute(
            select(Client).where(Client.id == job.client_id)
        )
        client = client_result.scalar_one_or_none()
        if client and client.email:
            recipients.append(client.email)

    notice_type_display = job.notice_blueprint_name or NOTICE_TYPE_DISPLAY.get(job.notice_type, job.notice_type)

    try:
        email_sent = EmailService.send_notice_reply(
            to=recipients,
            notice_type_display=notice_type_display,
            reply_body=job.final_reply,
            ca_name=ca_name,
            firm_name=firm_name,
            reply_to=reply_to,
        )
        if not email_sent:
            email_error = "SMTP send failed — check server SMTP configuration"
    except Exception as e:
        logger.error(f"Failed to send notice reply email to {recipients}: {e}")
        email_error = str(e)

    return {
        "message": "Notice reply approved and finalized",
        "status": "approved",
        "email_sent": email_sent,
        "email_error": email_error,
    }


@router.post("/{notice_id}/regenerate")
async def regenerate_notice(
    notice_id: str,
    request: NoticeRegenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[User, Depends(require_professional)],
    db: AsyncSession = Depends(get_db),
):
    """Re-generate draft with a different notice type or custom blueprint. Costs 1 credit."""
    # Resolve: custom blueprint or system type
    regen_blueprint_id = request.notice_blueprint_id
    regen_notice_type = request.notice_type
    regen_display_name = None

    if regen_blueprint_id:
        bp_result = await db.execute(
            select(BlueprintModel).where(
                BlueprintModel.id == UUID(regen_blueprint_id),
                BlueprintModel.category == "notice",
                (BlueprintModel.user_id == current_user.id) | (BlueprintModel.user_id.is_(None)),
            )
        )
        bp = bp_result.scalar_one_or_none()
        if not bp:
            raise HTTPException(400, "Custom notice blueprint not found or access denied")
        regen_notice_type = CUSTOM_NOTICE_TYPE
        regen_display_name = bp.name
    elif not regen_notice_type or regen_notice_type not in VALID_NOTICE_TYPES:
        raise HTTPException(400, f"Provide a valid notice_type or notice_blueprint_id. Valid types: {', '.join(VALID_NOTICE_TYPES)}")

    result = await db.execute(
        select(NoticeJob).where(
            NoticeJob.id == UUID(notice_id),
            NoticeJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Notice job not found")

    # Update blueprint name on the job
    job.notice_blueprint_name = regen_display_name
    job.notice_blueprint_id = UUID(regen_blueprint_id) if regen_blueprint_id else None
    await db.commit()

    # Deduct 1 credit for regeneration
    display = regen_display_name or NOTICE_TYPE_DISPLAY.get(regen_notice_type, regen_notice_type)
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.NOTICE_REGENERATE,
        db,
        description=f"Notice regenerate: {display}",
    )

    data_dir, db_dir = _get_notice_paths(str(current_user.id))
    regen_thread_id = job.langgraph_thread_id or f"notice-{current_user.id}-{job.id}"

    background_tasks.add_task(
        NoticeService.regenerate_notice,
        str(job.id),
        regen_notice_type,
        str(db_dir),
        str(data_dir),
        regen_thread_id,
        regen_blueprint_id,
    )

    return {
        "message": "Regeneration started",
        "notice_type": regen_notice_type,
        "notice_type_display": display,
        "status": "extracting",
    }


@router.get("/{notice_id}/pdf")
async def download_notice_pdf(
    notice_id: str,
    current_user: Annotated[User, Depends(require_professional)],
    db: AsyncSession = Depends(get_db),
):
    """Download the finalized notice reply as PDF."""
    result = await db.execute(
        select(NoticeJob).where(
            NoticeJob.id == UUID(notice_id),
            NoticeJob.user_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(404, "Notice job not found")

    if job.status != "approved" or not job.final_reply:
        raise HTTPException(400, "Notice reply must be approved before downloading PDF")

    # Fetch client info
    client_info = None
    if job.client_id:
        client_result = await db.execute(
            select(Client).where(Client.id == job.client_id)
        )
        client = client_result.scalar_one_or_none()
        if client:
            client_info = {"name": client.name, "gstin": client.gstin}

    # Fetch CA branding
    ca_info = None
    pref_result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    prefs = pref_result.scalar_one_or_none()
    if prefs and (prefs.firm_name or prefs.ca_name or prefs.icai_membership_number):
        ca_info = {
            "firm_name": prefs.firm_name,
            "ca_name": prefs.ca_name,
            "icai_membership_number": prefs.icai_membership_number,
            "firm_address": prefs.firm_address,
            "firm_phone": prefs.firm_phone,
            "firm_email": prefs.firm_email,
        }

    notice_type_display = job.notice_blueprint_name or NOTICE_TYPE_DISPLAY.get(job.notice_type, job.notice_type)
    pdf_buffer = ReportService.generate_notice_reply_pdf(
        notice_type_display=notice_type_display,
        reply_text=job.final_reply,
        client_info=client_info,
        ca_info=ca_info,
    )

    safe_name = job.notice_document_name.replace(" ", "_").replace(".pdf", "")
    return StreamingResponse(
        pdf_buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="notice_reply_{safe_name}.pdf"'
        },
    )
