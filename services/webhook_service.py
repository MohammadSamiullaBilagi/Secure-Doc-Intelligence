import logging
import re
import requests
from typing import Dict, Any
from sqlalchemy import select, create_engine
from sqlalchemy.orm import Session as SyncSession
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from db.config import settings
from db.models.core import UserPreference
from utils.exceptions import WebhookDeliveryError

logger = logging.getLogger(__name__)


def _strip_markdown_webhook(text: str) -> str:
    """Remove markdown formatting for plain-text output."""
    if not text:
        return ""
    # Normalise literal \n sequences (from JSON round-trips) to real newlines
    text = text.replace("\\n", "\n")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}(.+?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.+?)_{1,3}", r"\1", text)
    text = re.sub(r"~~(.+?)~~", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^[*\-+]\s+", "  ", text, flags=re.MULTILINE)
    text = re.sub(r"^(\d+)\.\s+", r"\1. ", text, flags=re.MULTILINE)
    text = re.sub(r"^>\s?", "", text, flags=re.MULTILINE)
    return text


class WebhookService:
    @staticmethod
    def _fetch_user_preferences_sync(user_id: str) -> dict:
        """Synchronous helper to fetch user delivery targets.

        Uses a synchronous SQLite connection to avoid 'event loop already running'
        errors when called from a sync LangGraph node inside an async FastAPI endpoint.
        """
        if not user_id:
            return {"email": None, "whatsapp": None, "tier": "standard"}

        try:
            from uuid import UUID
            # Ensure user_id is a proper UUID object for SQLAlchemy Uuid column comparison
            uid = UUID(user_id) if isinstance(user_id, str) else user_id

            # Build a sync engine from the async DATABASE_URL
            sync_url = settings.sync_database_url
            sync_engine = create_engine(sync_url)

            with SyncSession(sync_engine) as session:
                query = select(UserPreference).where(UserPreference.user_id == uid)
                prefs = session.execute(query).scalar_one_or_none()
                
                if prefs:
                    return {
                        "email": prefs.preferred_email,
                        "whatsapp": prefs.whatsapp_number,
                        "tier": prefs.alert_tier
                    }
        except Exception as e:
            logger.error(f"Failed to fetch user preferences for dispatch: {e}")
                
        return {"email": None, "whatsapp": None, "tier": "standard"}

    @staticmethod
    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout))
    )
    def dispatch_audit_results(session_hash: str, filename: str, final_state: Dict[str, Any]) -> bool:
        """Transmits the final audit state to an external webhook (e.g., n8n)."""
        webhook_url = settings.N8N_WEBHOOK_URL
        if not webhook_url:
            logger.warning("Webhook delivery skipped: N8N_WEBHOOK_URL is not configured.")
            return False

        logger.info(f"Dispatching audit results to webhook for session: {session_hash}")

        remediation = final_state.get("remediation_draft", {})
        
        # Determine the user who triggered this job
        user_id = final_state.get("user_id")
        
        # Use synchronous DB access to avoid event loop conflicts
        user_prefs = WebhookService._fetch_user_preferences_sync(user_id)
        
        # We grab the human-approved text (which may have literal \n and markdown)
        raw_email_body = remediation.get("email_body", "")
        # Normalise literal \n sequences to real newlines
        raw_email_body = raw_email_body.replace("\\n", "\n")

        # Strip markdown for plain-text version
        plain_email_body = _strip_markdown_webhook(raw_email_body)

        # Convert markdown → HTML for rich email rendering
        import markdown as md
        html_email_body = md.markdown(raw_email_body, extensions=["tables", "nl2br"])

        payload = {
            "meta": {
                "session_hash": session_hash,
                "document_name": filename,
                "blueprint_used": final_state.get("blueprint", {}).name if hasattr(final_state.get("blueprint"), 'name') else "Unknown",
                "user_id": user_id
            },
            "dispatch_targets": {
                "email": user_prefs.get("email"),
                "whatsapp": user_prefs.get("whatsapp"),
                "tier": user_prefs.get("tier")
            },
            "risk_assessment": final_state.get("risk_report", "No report generated."),
            "action_required": remediation.get("requires_action", False),
            "remediation": {
                "recipient": remediation.get("target_recipient_type", ""),
                "subject": remediation.get("email_subject", ""),
                "body_plain": plain_email_body,  # Markdown stripped for logs / SMS
                "body_html": html_email_body     # Markdown → HTML for Gmail
            },
            "violations": [
                (res.model_dump() if hasattr(res, 'model_dump') else res)
                for res in final_state.get("audit_results", [])
                if str(getattr(res, 'compliance_status', None) or (res.get('compliance_status', '') if isinstance(res, dict) else '')).upper()
                not in ('COMPLIANT', 'TRUE')
            ]
        }

        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Successfully dispatched payload to webhook. Status Code: {response.status_code}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to dispatch webhook after retries: {e}")
            raise WebhookDeliveryError(f"Webhook dispatch failed: {str(e)}")