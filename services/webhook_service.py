import logging
import requests
from typing import Dict, Any
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings
from utils.exceptions import WebhookDeliveryError

logger = logging.getLogger(__name__)

class WebhookService:
    @staticmethod
    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.ConnectionError, requests.exceptions.Timeout))
    )
    def dispatch_audit_results(session_hash: str, filename: str, final_state: Dict[str, Any]) -> bool:
        """Transmits the final audit state to an external webhook (e.g., n8n)."""
        webhook_url = settings.n8n_webhook_url
        if not webhook_url:
            logger.warning("Webhook delivery skipped: n8n_webhook_url is not configured.")
            return False

        logger.info(f"Dispatching audit results to webhook for session: {session_hash}")

        remediation = final_state.get("remediation_draft", {})
        
        # ==========================================
        # THE FIX: HTML ENCODING FOR GMAIL
        # ==========================================
        # We grab the human-approved text (which has \n)
        raw_email_body = remediation.get("email_body", "")
        
        # We replace Python newlines with HTML line breaks
        # We also replace spaces with non-breaking spaces for bullet-point indentation
        html_email_body = raw_email_body.replace('\n', '<br>').replace('   -', '&nbsp;&nbsp;&nbsp;-')
        # ==========================================

        payload = {
            "meta": {
                "session_hash": session_hash,
                "document_name": filename,
                "blueprint_used": final_state.get("blueprint", {}).name if hasattr(final_state.get("blueprint"), 'name') else "Unknown"
            },
            "risk_assessment": final_state.get("risk_report", "No report generated."),
            "action_required": remediation.get("requires_action", False),
            "remediation": {
                "recipient": remediation.get("target_recipient_type", ""),
                "subject": remediation.get("email_subject", ""),
                "body_plain": raw_email_body,   # Safe to keep for logs or SMS
                "body_html": html_email_body    # NEW: The HTML version for Gmail
            },
            "violations": [
                res.model_dump() for res in final_state.get("audit_results", []) 
                if not res.is_compliant
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