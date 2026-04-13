import shutil
import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)
from typing import Annotated, List
from uuid import uuid4
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.dependencies import get_current_user, require_enterprise
from db.database import get_db
from db.models.core import User, AuditJob
from db.models.billing import CreditActionType
from db.models.clients import Client, ClientDocument
from ingestion import DocumentProcessor
from services.watcher_service import WatcherService
from services.credits_service import CreditsService
from services.audit_log_service import log_audit_event, extract_request_meta
from services.legal_content import get_ai_processing_disclosure
from api.rate_limit import limiter
from config import settings

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])

BASE_SESSIONS_DIR = Path("user_sessions")

def get_session_paths(user_id: str):
    """Namespaces vector databases and files isolated by User UUID."""
    session_dir = BASE_SESSIONS_DIR / str(user_id)
    data_dir = session_dir / "data"
    db_dir = session_dir / "vector_db"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, db_dir

@router.post("/upload")
@limiter.limit("10/minute")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    blueprint_file: str = Form("gst_blueprint.json"),
    client_id: str = Form(None, description="Optional client UUID to link documents to"),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Ingests multiple PDFs, splits them into the ChromaDB vector store, 
    and triggers the background Compliance Orchestrator automatically.
    """
    if not current_user:
        raise HTTPException(status_code=401, detail="Unauthorized")
        
    data_dir, db_dir = get_session_paths(str(current_user.id))
    processed_files = []
    
    # Count PDF files and check/deduct credits upfront
    pdf_files = [f for f in files if f.filename.endswith(".pdf")]
    if not pdf_files:
        raise HTTPException(status_code=400, detail="No PDF files provided")
    
    # Clean up ALL old stale pending AuditJobs for the user before starting new uploads
    # This prevents old scan results from cluttering the pending actions list
    stale_jobs_query = select(AuditJob).where(
        AuditJob.user_id == current_user.id,
        AuditJob.status == "pending"
    )
    stale_result = await db.execute(stale_jobs_query)
    for stale_job in stale_result.scalars().all():
        await db.delete(stale_job)
    
    for file in pdf_files:
        # Deduct 5 credits per scan — raises HTTP 402 if insufficient
        await CreditsService.check_and_deduct(
            current_user.id,
            CreditActionType.DOCUMENT_SCAN,
            db,
            description=f"Audit scan: {file.filename}"
        )
    
    # Validate and resolve client_id if provided
    linked_client = None
    if client_id:
        from uuid import UUID as _UUID
        try:
            parsed_client_id = _UUID(client_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid client_id format")
        client_result = await db.execute(
            select(Client).where(
                Client.id == parsed_client_id,
                Client.ca_user_id == current_user.id,
            )
        )
        linked_client = client_result.scalar_one_or_none()
        if not linked_client:
            raise HTTPException(status_code=404, detail="Client not found")

    file_thread_ids = {}  # filename → unique thread_id for this audit run

    for file in pdf_files:
        file_path = data_dir / file.filename

        # Save uploaded file — write to a temp path first, then atomically replace.
        # This prevents PermissionError on Windows when a previous audit still has the file open.
        temp_path = data_dir / f".{file.filename}.{uuid4()}.tmp"
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Retry the atomic rename up to 5 times (10s total) waiting for any active read lock to clear.
        replaced = False
        for attempt in range(5):
            try:
                import os
                os.replace(str(temp_path), str(file_path))
                replaced = True
                break
            except PermissionError:
                await asyncio.sleep(2)

        if not replaced:
            temp_path.unlink(missing_ok=True)
            logger.warning(
                f"Could not replace {file.filename} (locked by active audit). "
                "Using existing file on disk — ChromaDB data is unchanged."
            )

        processed_files.append(file.filename)

        # Generate a fresh UUID thread_id for every audit run.
        # Using a fixed deterministic id (e.g. user_id+filename) caused LangGraph's
        # operator.add reducer to accumulate results from previous runs, doubling results.
        thread_id = str(uuid4())
        file_thread_ids[file.filename] = thread_id

        # Clean up any old AuditJob for the same doc to avoid duplicates
        old_jobs_query = select(AuditJob).where(
            AuditJob.user_id == current_user.id,
            AuditJob.document_name == file.filename,
        )
        old_jobs_result = await db.execute(old_jobs_query)
        for old_job in old_jobs_result.scalars().all():
            await db.delete(old_job)

        # Create fresh AuditJob tracking record
        new_job = AuditJob(
            user_id=current_user.id,
            document_name=file.filename,
            status="pending",
            langgraph_thread_id=thread_id,
            client_id=linked_client.id if linked_client else None,
        )
        db.add(new_job)
        await db.flush()

        # Create ClientDocument link if client is specified
        if linked_client:
            client_doc = ClientDocument(
                client_id=linked_client.id,
                audit_job_id=new_job.id,
                document_name=file.filename,
            )
            db.add(client_doc)

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Database err: {e}")

    # 2. Extract and embed text synchronously in the pipeline
    processor = DocumentProcessor(data_dir=str(data_dir), db_dir=str(db_dir))
    docs = processor.extract_text_from_pdfs()

    if docs:
        try:
            processor.create_vector_store(docs)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Vector store creation failed: {e}. Please retry the upload.")

    # 3. Trigger LangGraph via background task so API responds instantly.
    # Pass the pre-generated UUID thread_id so each run is isolated in the checkpointer.
    for filename in processed_files:
        background_tasks.add_task(
            WatcherService.run_background_audit,
            session_hash=str(current_user.id),
            filename=filename,
            selected_blueprint_file=blueprint_file,
            user_id=str(current_user.id),
            thread_id=file_thread_ids[filename],
        )

    # Audit log for document uploads
    ip, ua = extract_request_meta(request)
    for filename in processed_files:
        await log_audit_event(
            db, current_user.id, "document_upload",
            resource_type="document", resource_id=filename,
            ip_address=ip, user_agent=ua,
        )
    await db.commit()

    disclosure = get_ai_processing_disclosure()
    return {
        "message": f"Successfully ingested {len(processed_files)} documents.",
        "documents": processed_files,
        "thread_ids": [file_thread_ids[fn] for fn in processed_files],
        "client_id": str(linked_client.id) if linked_client else None,
        "status": "Processing in background",
        "ai_processing_disclosure": disclosure["short"],
    }


@router.post("/bulk-upload")
@limiter.limit("5/minute")
async def bulk_upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    client_names: str = Form(..., description="Comma-separated client names, one per file"),
    blueprint_file: str = Form("gst_blueprint.json"),
    current_user: Annotated[User, Depends(require_enterprise)] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Bulk upload multiple PDFs with client tagging. Requires Enterprise plan.
    Each file is associated with a client by name (get-or-create).
    """

    pdf_files = [f for f in files if f.filename.endswith(".pdf")]
    if not pdf_files:
        raise HTTPException(status_code=400, detail="No PDF files provided")

    names = [n.strip() for n in client_names.split(",") if n.strip()]
    if len(names) != len(pdf_files):
        raise HTTPException(
            status_code=400,
            detail=f"Number of client names ({len(names)}) must match number of PDF files ({len(pdf_files)})"
        )

    # Check total credit cost upfront
    total_cost = 5 * len(pdf_files)
    from services.credits_service import CreditsService as CS
    sub = await CS.get_or_create_subscription(current_user.id, db)
    if sub.credits_balance < total_cost:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "Insufficient credits for bulk upload",
                "required": total_cost,
                "balance": sub.credits_balance,
                "files": len(pdf_files),
            }
        )

    data_dir, db_dir = get_session_paths(str(current_user.id))
    results = []
    file_thread_ids = {}
    client_cache = {}  # name -> Client, avoids duplicate creation within batch

    for file, client_name in zip(pdf_files, names):
        # Deduct credits per file
        await CreditsService.check_and_deduct(
            current_user.id,
            CreditActionType.DOCUMENT_SCAN,
            db,
            description=f"Bulk scan: {file.filename} (client: {client_name})"
        )

        # Get or create client (with in-batch dedup)
        if client_name in client_cache:
            client = client_cache[client_name]
        else:
            client_result = await db.execute(
                select(Client).where(
                    Client.ca_user_id == current_user.id,
                    Client.name == client_name,
                )
            )
            client = client_result.scalar_one_or_none()
            if not client:
                client = Client(ca_user_id=current_user.id, name=client_name)
                db.add(client)
                await db.flush()
            client_cache[client_name] = client

        # Save file
        file_path = data_dir / file.filename
        temp_path = data_dir / f".{file.filename}.{uuid4()}.tmp"
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        replaced = False
        for attempt in range(5):
            try:
                import os
                os.replace(str(temp_path), str(file_path))
                replaced = True
                break
            except PermissionError:
                await asyncio.sleep(2)

        if not replaced:
            temp_path.unlink(missing_ok=True)

        thread_id = str(uuid4())
        file_thread_ids[file.filename] = thread_id

        # Create AuditJob with client_id
        new_job = AuditJob(
            user_id=current_user.id,
            document_name=file.filename,
            status="pending",
            langgraph_thread_id=thread_id,
            client_id=client.id,
        )
        db.add(new_job)
        await db.flush()

        # Create ClientDocument link
        client_doc = ClientDocument(
            client_id=client.id,
            audit_job_id=new_job.id,
            document_name=file.filename,
        )
        db.add(client_doc)

        results.append({
            "file_name": file.filename,
            "client_name": client_name,
            "thread_id": thread_id,
            "status": "queued",
        })

    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    # Ingest all files into vector store
    processor = DocumentProcessor(data_dir=str(data_dir), db_dir=str(db_dir))
    docs = processor.extract_text_from_pdfs()
    if docs:
        try:
            processor.create_vector_store(docs)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Vector store creation failed: {e}")

    # Trigger background audits
    for item in results:
        background_tasks.add_task(
            WatcherService.run_background_audit,
            session_hash=str(current_user.id),
            filename=item["file_name"],
            selected_blueprint_file=blueprint_file,
            user_id=str(current_user.id),
            thread_id=item["thread_id"],
        )

    return {"results": results}
