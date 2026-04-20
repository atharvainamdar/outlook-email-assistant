"""SMTP email sending service for Outlook."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    reply_to_message_id: str = "",
    html: bool = False,
) -> bool:
    """Send an email via SMTP through Outlook.

    Returns True on success, False on failure.
    """
    if not settings.smtp_user or not settings.smtp_password:
        logger.error("SMTP credentials not configured")
        return False

    msg = MIMEMultipart("alternative")
    msg["From"] = settings.smtp_user
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    if reply_to_message_id:
        msg["In-Reply-To"] = reply_to_message_id
        msg["References"] = reply_to_message_id

    content_type = "html" if html else "plain"
    msg.attach(MIMEText(body, content_type, "utf-8"))

    all_recipients = list(to) + (cc or [])

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.smtp_user, settings.smtp_password)
            server.sendmail(settings.smtp_user, all_recipients, msg.as_string())
        logger.info("Email sent to %s: %s", all_recipients, subject)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", all_recipients)
        return False
