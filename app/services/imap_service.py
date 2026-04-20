"""IMAP email fetcher — connects to Outlook and pulls emails without marking as read."""

from __future__ import annotations

import email
import logging
import uuid
from datetime import datetime
from email.header import decode_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Optional

from imapclient import IMAPClient

from app.config import settings
from app.database import get_email_by_message_id, save_email
from app.models.email import Attachment, EmailMessage

logger = logging.getLogger(__name__)


def _decode_header_value(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    parts = decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _extract_body(msg: email.message.Message) -> tuple[str, str]:
    """Return (plain_text, html) body from an email message."""
    text_body = ""
    html_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            disp = str(part.get("Content-Disposition", ""))
            if "attachment" in disp:
                continue
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if ct == "text/plain" and not text_body:
                text_body = decoded
            elif ct == "text/html" and not html_body:
                html_body = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                html_body = decoded
            else:
                text_body = decoded
    return text_body, html_body


def _extract_attachments(msg: email.message.Message) -> list[Attachment]:
    attachments: list[Attachment] = []
    if not msg.is_multipart():
        return attachments
    att_dir = settings.data_dir / "attachments"
    for part in msg.walk():
        disp = str(part.get("Content-Disposition", ""))
        if "attachment" not in disp:
            continue
        filename = _decode_header_value(part.get_filename()) or f"unnamed_{uuid.uuid4().hex[:8]}"
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        safe_name = f"{uuid.uuid4().hex[:8]}_{filename}"
        local_path = str(att_dir / safe_name)
        with open(local_path, "wb") as f:
            f.write(payload)
        attachments.append(
            Attachment(
                filename=filename,
                content_type=part.get_content_type() or "application/octet-stream",
                size_bytes=len(payload),
                local_path=local_path,
            )
        )
    return attachments


def _parse_email(raw_bytes: bytes) -> Optional[EmailMessage]:
    """Parse raw email bytes into an EmailMessage."""
    try:
        msg = email.message_from_bytes(raw_bytes)
    except Exception:
        logger.exception("Failed to parse email bytes")
        return None

    message_id = msg.get("Message-ID", "") or ""
    subject = _decode_header_value(msg.get("Subject"))
    from_header = msg.get("From", "")
    sender_name, sender_addr = parseaddr(from_header)

    to_header = msg.get("To", "")
    recipients = [parseaddr(a)[1] for a in to_header.split(",") if a.strip()]

    cc_header = msg.get("Cc", "")
    cc = [parseaddr(a)[1] for a in cc_header.split(",") if a.strip()]

    date: Optional[datetime] = None
    date_str = msg.get("Date")
    if date_str:
        try:
            date = parsedate_to_datetime(date_str)
        except Exception:
            pass

    text_body, html_body = _extract_body(msg)
    attachments = _extract_attachments(msg)

    return EmailMessage(
        message_id=message_id,
        subject=subject,
        sender=sender_addr,
        sender_name=_decode_header_value(sender_name) if sender_name else "",
        recipients=recipients,
        cc=cc,
        date=date,
        body_text=text_body,
        body_html=html_body,
        attachments=attachments,
        folder="INBOX",
    )


class IMAPService:
    """Fetch emails from Outlook via IMAP without marking them as read."""

    def __init__(
        self,
        host: str = "",
        port: int = 0,
        user: str = "",
        password: str = "",
        use_ssl: bool = True,
    ):
        self.host = host or settings.imap_host
        self.port = port or settings.imap_port
        self.user = user or settings.imap_user
        self.password = password or settings.imap_password
        self.use_ssl = use_ssl if use_ssl is not None else settings.imap_use_ssl

    def _connect(self) -> IMAPClient:
        client = IMAPClient(self.host, port=self.port, ssl=self.use_ssl)
        client.login(self.user, self.password)
        return client

    def test_connection(self) -> tuple[bool, str]:
        """Return (True, message) if IMAP login succeeds, (False, error) otherwise."""
        if not self.user or not self.password:
            return False, "Email address and password are required"
        try:
            client = self._connect()
            client.logout()
            return True, "Connection successful"
        except Exception as exc:
            logger.warning("IMAP connection test failed: %s", exc)
            return False, str(exc)

    def fetch_new_emails(
        self,
        folder: str = "",
        limit: int = 50,
        since_date: Optional[datetime] = None,
    ) -> list[EmailMessage]:
        """Fetch emails via IMAP **without** marking them as read.

        Uses BODY.PEEK to avoid setting the \\Seen flag.
        """
        folder = folder or settings.imap_folder
        client = self._connect()
        try:
            client.select_folder(folder, readonly=True)  # readonly = no flag changes

            criteria: list[str | bytes] = ["ALL"]
            if since_date:
                criteria = ["SINCE", since_date.strftime("%d-%b-%Y").encode()]

            msg_ids = client.search(criteria)
            if not msg_ids:
                return []

            # Take the most recent `limit` messages
            msg_ids = msg_ids[-limit:]

            # BODY.PEEK[] fetches full message without setting \Seen
            raw_messages = client.fetch(msg_ids, ["BODY.PEEK[]", "FLAGS"])
            emails: list[EmailMessage] = []
            for uid, data in raw_messages.items():
                raw = data.get(b"BODY[]") or data.get(b"RFC822")
                if not raw:
                    continue

                parsed = _parse_email(raw)
                if parsed is None:
                    continue

                # Skip if we already have this message
                if parsed.message_id and get_email_by_message_id(parsed.message_id):
                    continue

                flags = data.get(b"FLAGS", ())
                parsed.is_read = b"\\Seen" in flags
                saved = save_email(parsed)
                emails.append(saved)

            logger.info("Fetched %d new emails from %s", len(emails), folder)
            return emails
        finally:
            client.logout()

    def list_folders(self) -> list[str]:
        """List all IMAP folders."""
        client = self._connect()
        try:
            folders = client.list_folders()
            return [f[2] for f in folders]
        finally:
            client.logout()

    def fetch_all_for_backup(
        self,
        folder: str = "",
        batch_size: int = 100,
    ) -> list[EmailMessage]:
        """Fetch ALL emails for backup purposes. Reads in readonly mode."""
        folder = folder or settings.imap_folder
        client = self._connect()
        try:
            client.select_folder(folder, readonly=True)
            msg_ids = client.search(["ALL"])
            if not msg_ids:
                return []

            all_emails: list[EmailMessage] = []
            for i in range(0, len(msg_ids), batch_size):
                batch = msg_ids[i : i + batch_size]
                raw_messages = client.fetch(batch, ["BODY.PEEK[]"])
                for uid, data in raw_messages.items():
                    raw = data.get(b"BODY[]")
                    if not raw:
                        continue
                    parsed = _parse_email(raw)
                    if parsed is None:
                        continue
                    existing = get_email_by_message_id(parsed.message_id)
                    if existing:
                        all_emails.append(existing)
                    else:
                        saved = save_email(parsed)
                        all_emails.append(saved)
                progress = min(i + batch_size, len(msg_ids))
                logger.info("Backup progress: %d/%d", progress, len(msg_ids))

            return all_emails
        finally:
            client.logout()
