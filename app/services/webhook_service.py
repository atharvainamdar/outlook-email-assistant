"""Webhook ingestion — receive forwarded emails when IMAP is not available.

This service exposes an endpoint that can receive emails forwarded
via services like Mailgun, SendGrid, or custom SMTP-to-HTTP bridges.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.config import settings
from app.database import get_email_by_message_id, save_email
from app.models.email import Attachment, EmailMessage

logger = logging.getLogger(__name__)


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 signature if webhook_secret is configured."""
    if not settings.webhook_secret:
        return True  # no secret = no verification
    expected = hmac.new(
        settings.webhook_secret.encode(),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def ingest_forwarded_email(
    subject: str,
    sender: str,
    sender_name: str = "",
    recipients: list[str] | None = None,
    cc: list[str] | None = None,
    body_text: str = "",
    body_html: str = "",
    date: Optional[datetime] = None,
    message_id: str = "",
    attachments: list[dict] | None = None,
) -> EmailMessage:
    """Process a forwarded email received via webhook."""
    # Deduplicate by message_id
    if message_id:
        existing = get_email_by_message_id(message_id)
        if existing:
            logger.info("Webhook: skipping duplicate %s", message_id)
            return existing

    att_list = []
    if attachments:
        for a in attachments:
            att_list.append(
                Attachment(
                    filename=a.get("filename", "unnamed"),
                    content_type=a.get("content_type", "application/octet-stream"),
                    size_bytes=a.get("size", 0),
                    local_path=a.get("local_path", ""),
                )
            )

    email_msg = EmailMessage(
        message_id=message_id or f"<webhook-{uuid.uuid4().hex}@local>",
        subject=subject,
        sender=sender,
        sender_name=sender_name,
        recipients=recipients or [],
        cc=cc or [],
        date=date or datetime.now(timezone.utc),
        body_text=body_text,
        body_html=body_html,
        attachments=att_list,
        folder="INBOX",
    )

    saved = save_email(email_msg)
    logger.info("Webhook: ingested email '%s' from %s", subject[:60], sender)
    return saved
