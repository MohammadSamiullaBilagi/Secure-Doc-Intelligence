import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)

# The verified sender address on SendGrid / Gmail
# All emails appear FROM this address so SendGrid doesn't block them.
# The CA's name appears in the display name; Reply-To is set to the CA's email
# so client replies go directly to the CA.
_PLATFORM_NAME = "Legal AI Expert"


class EmailService:
    """Multi-tenant SMTP email service.

    Emails are always sent from the platform's verified sender address
    (SMTP_FROM_EMAIL) but branded with the CA's firm name in the display
    name and the CA's preferred email in Reply-To.  This means:

        From:     CA Ravi Sharma via Legal AI Expert <notifications@legalaiexpert.in>
        Reply-To: ravi@ravisharma.com

    Clients see the CA's name and can reply directly to the CA.
    No per-CA domain verification is needed.
    """

    @staticmethod
    def is_configured() -> bool:
        return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)

    @staticmethod
    def send_email(
        to: str,
        subject: str,
        body_html: str,
        *,
        ca_name: Optional[str] = None,
        reply_to: Optional[str] = None,
    ) -> bool:
        """Send an email via SMTP.

        Args:
            to:        Recipient email address.
            subject:   Email subject line.
            body_html: Email body (plain text or HTML).
            ca_name:   CA firm/person name — shown in the From display name.
            reply_to:  CA's email — client replies go here directly.

        Returns:
            True on success, False on failure.
        """
        if not EmailService.is_configured():
            logger.warning("SMTP not configured. Skipping email send.")
            return False

        platform_from = settings.smtp_from_email or settings.smtp_user

        # Build branded display name: "CA Ravi Sharma via Legal AI Expert"
        if ca_name:
            display_name = f"{ca_name} via {_PLATFORM_NAME}"
        else:
            display_name = _PLATFORM_NAME

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{display_name} <{platform_from}>"
        msg["To"] = to

        # Reply-To lets the client reply directly to the CA's inbox
        if reply_to and reply_to != platform_from:
            msg["Reply-To"] = reply_to

        msg.attach(MIMEText(body_html, "plain"))

        try:
            if settings.smtp_port == 465:
                server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30)
            else:
                server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
                server.starttls()

            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(platform_from, [to], msg.as_string())
            server.quit()
            logger.info(f"Email sent to {to} (on behalf of: {display_name}): {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to}: {e}")
            return False

    @staticmethod
    def send_deadline_reminder(
        to: str,
        ca_name: str,
        deadline_name: str,
        due_date_str: str,
        days_remaining: int,
        reply_to: Optional[str] = None,
    ) -> bool:
        """Send a tax deadline reminder email branded with the CA's name."""
        subject = f"Tax Deadline Alert: {deadline_name} due in {days_remaining} days"
        body = (
            f"Dear Client,\n\n"
            f"This is a reminder from {ca_name or _PLATFORM_NAME} regarding an upcoming tax deadline:\n\n"
            f"  Deadline : {deadline_name}\n"
            f"  Due Date : {due_date_str}\n"
            f"  Days Left: {days_remaining}\n\n"
            f"Please ensure all filings are completed on time to avoid penalties.\n\n"
            f"For any queries, reply to this email or contact your CA directly.\n\n"
            f"Regards,\n"
            f"{ca_name or _PLATFORM_NAME}"
        )
        return EmailService.send_email(
            to, subject, body,
            ca_name=ca_name,
            reply_to=reply_to,
        )

    @staticmethod
    def send_audit_dispatch(
        to: str,
        ca_name: str,
        subject: str,
        body: str,
        reply_to: Optional[str] = None,
    ) -> bool:
        """Send an audit result / compliance report email to a client."""
        return EmailService.send_email(
            to, subject, body,
            ca_name=ca_name,
            reply_to=reply_to,
        )
