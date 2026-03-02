import pytest
import requests
from unittest.mock import patch
from services.webhook_service import WebhookService
from utils.exceptions import WebhookDeliveryError

@pytest.fixture
def mock_final_state():
    return {
        "risk_report": "High Risk Found.",
        "remediation_draft": {
            "requires_action": True,
            "target_recipient_type": "Vendor",
            "email_subject": "Fix required",
            "email_body": "Please fix clause X."
        },
        "audit_results": []
    }

@patch("services.webhook_service.settings")
@patch("services.webhook_service.requests.post")
def test_dispatch_audit_results_success(mock_post, mock_settings, mock_final_state):
    # Arrange
    mock_settings.n8n_webhook_url = "http://test-webhook.com"
    mock_response = mock_post.return_value
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None

    # Act
    result = WebhookService.dispatch_audit_results("session_123", "test.pdf", mock_final_state)

    # Assert
    assert result is True
    mock_post.assert_called_once()
    called_args, called_kwargs = mock_post.call_args
    assert called_kwargs["json"]["meta"]["document_name"] == "test.pdf"
    assert called_kwargs["json"]["action_required"] is True

@patch("services.webhook_service.settings")
@patch("services.webhook_service.requests.post")
def test_dispatch_audit_results_retries_and_fails(mock_post, mock_settings, mock_final_state):
    # Arrange
    mock_settings.n8n_webhook_url = "http://test-webhook.com"
    # Simulate a Connection Error every time
    mock_post.side_effect = requests.exceptions.ConnectionError("Network Down")

    # Act & Assert
    with pytest.raises(WebhookDeliveryError):
        WebhookService.dispatch_audit_results("session_123", "test.pdf", mock_final_state)
    
    # Assert tenacity attempted it 4 times (the initial try + 3 retries)
    assert mock_post.call_count == 4