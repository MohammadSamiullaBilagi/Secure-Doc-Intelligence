"""Routes for downloadable tools — PDF Redaction Tool."""

import hashlib
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from db.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])

REDACTOR_FILENAME = "pdf_redactor.exe"


def _get_redactor_path() -> Path:
    path_str = getattr(settings, "REDACTOR_EXE_PATH", f"static/tools/{REDACTOR_FILENAME}")
    return Path(path_str)


@router.get("/redactor/download")
async def download_redactor():
    """Download the PDF Redaction Tool (.exe)."""
    exe_path = _get_redactor_path()
    if not exe_path.exists():
        raise HTTPException(
            status_code=404,
            detail=(
                "PDF Redaction Tool is not yet available for download. "
                "Please check back later or contact support."
            ),
        )
    return FileResponse(
        path=str(exe_path),
        filename=REDACTOR_FILENAME,
        media_type="application/octet-stream",
    )


@router.get("/redactor/info")
async def redactor_info():
    """Returns metadata about the PDF Redaction Tool."""
    exe_path = _get_redactor_path()
    available = exe_path.exists()

    info = {
        "name": "Legal AI Expert — PDF Redaction Tool",
        "version": "1.0.0",
        "available": available,
        "filename": REDACTOR_FILENAME,
        "download_url": "/api/v1/tools/redactor/download",
        "description": (
            "A standalone desktop tool for permanently redacting sensitive information "
            "(PAN, Aadhaar, names, bank account numbers) from PDF documents before uploading "
            "to Legal AI Expert. Uses PyMuPDF's true redaction — removes underlying text data, "
            "not just visual overlay. Same technology used by law firms and government agencies."
        ),
        "redaction_guide": {
            "what_to_redact": [
                "PAN numbers (e.g., ABCDE1234F)",
                "Aadhaar numbers (12-digit)",
                "Personal names and signatures",
                "Bank account numbers",
                "Personal addresses",
                "Phone numbers",
            ],
            "what_NOT_to_redact": [
                "GSTIN — needed for GST reconciliation",
                "Dates — needed for all analysis features",
                "Amounts and figures — needed for financial analysis",
                "Invoice numbers — needed for matching",
                "Assessment Year / Financial Year references",
                "Tax computation details",
            ],
        },
    }

    if available:
        size_bytes = exe_path.stat().st_size
        info["size_mb"] = round(size_bytes / (1024 * 1024), 1)
        sha256 = hashlib.sha256(exe_path.read_bytes()).hexdigest()
        info["sha256"] = sha256

    return info
