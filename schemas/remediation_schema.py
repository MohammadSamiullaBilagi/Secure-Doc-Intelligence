from pydantic import BaseModel, Field

class RemediationDraft(BaseModel):
    """Structured output for the Remediation Agent."""
    requires_action: bool = Field(..., description="True if violations exist and action is needed, False otherwise.")
    target_recipient_type: str = Field(..., description="E.g., 'Vendor', 'Internal Legal', 'Tax Department', or 'None'.")
    email_subject: str = Field(..., description="Professional, concise subject line for the email.")
    email_body: str = Field(..., description="The complete draft of the correction request or explanation letter.")