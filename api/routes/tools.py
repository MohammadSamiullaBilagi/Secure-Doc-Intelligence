"""Routes for downloadable tools — PDF Redaction Tool.

Hosting strategy:
- The built `.exe` is too large to bundle in the Docker image, so we host it
  on a public GCS bucket and redirect `/redactor/download` there.
- `settings.REDACTOR_PUBLIC_URL` points at the GCS object URL. If empty, we
  fall back to the legacy local-file path (`static/tools/pdf_redactor.exe`)
  for dev convenience, and return 404 if neither is available.
"""

import hashlib
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from db.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tools", tags=["Tools"])

REDACTOR_FILENAME = "pdf_redactor.exe"
MANIFEST_PATH = Path("tools/pdf_redactor/redactor_manifest.json")


def _get_local_redactor_path() -> Path:
    path_str = getattr(settings, "REDACTOR_EXE_PATH", f"static/tools/{REDACTOR_FILENAME}")
    return Path(path_str)


def _load_manifest() -> dict:
    """Load committed manifest with version + sha256 of the hosted .exe."""
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read redactor manifest: %s", exc)
    return {}


@router.get("/redactor/download")
async def download_redactor():
    """Download the PDF Redaction Tool (.exe).

    Prefers a 302 redirect to `settings.REDACTOR_PUBLIC_URL` (GCS); falls
    back to a local FileResponse in dev when no public URL is configured.
    """
    public_url = (settings.REDACTOR_PUBLIC_URL or "").strip()
    if public_url:
        return RedirectResponse(url=public_url, status_code=302)

    exe_path = _get_local_redactor_path()
    if exe_path.exists():
        return FileResponse(
            path=str(exe_path),
            filename=REDACTOR_FILENAME,
            media_type="application/octet-stream",
        )

    raise HTTPException(
        status_code=404,
        detail=(
            "PDF Redaction Tool is not yet available for download. "
            "Please check back later or contact support."
        ),
    )


@router.get("/redactor/info")
async def redactor_info():
    """Returns metadata about the PDF Redaction Tool."""
    public_url = (settings.REDACTOR_PUBLIC_URL or "").strip()
    exe_path = _get_local_redactor_path()
    manifest = _load_manifest()

    available = bool(public_url) or exe_path.exists()

    info = {
        "name": "Legal AI Expert — PDF Redaction Tool",
        "version": manifest.get("version") or settings.REDACTOR_VERSION,
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

    # Merge manifest hash/size if present
    if "sha256" in manifest:
        info["sha256"] = manifest["sha256"]
    if "size_mb" in manifest:
        info["size_mb"] = manifest["size_mb"]

    # Fall back to inspecting the local file if manifest is absent
    if ("sha256" not in info or "size_mb" not in info) and exe_path.exists():
        size_bytes = exe_path.stat().st_size
        info.setdefault("size_mb", round(size_bytes / (1024 * 1024), 1))
        info.setdefault("sha256", hashlib.sha256(exe_path.read_bytes()).hexdigest())

    return info
