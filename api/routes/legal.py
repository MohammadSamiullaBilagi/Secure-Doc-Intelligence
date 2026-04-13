"""DPDPA legal compliance routes — Privacy Policy, ToS, Consent."""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from api.rate_limit import limiter
from db.database import get_db
from db.models.core import User
from schemas.legal import ConsentRequest, ConsentStatusResponse
from services.audit_log_service import log_audit_event, extract_request_meta
from services.legal_content import (
    get_privacy_policy,
    get_terms_of_service,
    get_ai_processing_disclosure,
    CURRENT_CONSENT_VERSION,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/legal", tags=["Legal & Privacy"])


@router.get("/privacy-policy")
async def privacy_policy():
    """Returns the full privacy policy (public, no auth required)."""
    return get_privacy_policy()


@router.get("/terms")
async def terms_of_service():
    """Returns the full Terms of Service (public, no auth required)."""
    return get_terms_of_service()


@router.get("/ai-disclosure")
async def ai_disclosure():
    """Returns the AI processing disclosure text (public)."""
    return get_ai_processing_disclosure()


@router.get("/consent-status", response_model=ConsentStatusResponse)
async def consent_status(
    current_user: Annotated[User, Depends(get_current_user)],
):
    """Check the current user's consent status."""
    return ConsentStatusResponse(
        consent_accepted=current_user.consent_accepted_at is not None,
        consent_version=current_user.consent_version,
        consent_accepted_at=(
            current_user.consent_accepted_at.isoformat()
            if current_user.consent_accepted_at
            else None
        ),
        current_version=CURRENT_CONSENT_VERSION,
    )


@router.post("/consent")
@limiter.limit("10/minute")
async def accept_consent(
    request: Request,
    body: ConsentRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Record or update user's consent acceptance."""
    if not body.accepted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Consent must be accepted (accepted=true).",
        )
    if body.version != CURRENT_CONSENT_VERSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid consent version. Current version is {CURRENT_CONSENT_VERSION}.",
        )

    current_user.consent_accepted_at = datetime.now(timezone.utc)
    current_user.consent_version = body.version

    ip, ua = extract_request_meta(request)
    await log_audit_event(
        db, current_user.id, "consent_update",
        ip_address=ip, user_agent=ua,
        details={"version": body.version},
    )

    await db.commit()
    logger.info(f"Consent recorded for user {current_user.email} (version {body.version})")

    return {
        "message": "Consent recorded successfully",
        "version": body.version,
        "accepted_at": current_user.consent_accepted_at.isoformat(),
    }
