"""Email backup — export to JSON and .eml files for archival."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from app.config import settings
from app.database import list_emails, mark_backed_up
from app.models.email import EmailMessage

logger = logging.getLogger(__name__)


def _email_to_dict(email_msg: EmailMessage) -> dict:
    return {
        "id": email_msg.id,
        "message_id": email_msg.message_id,
        "subject": email_msg.subject,
        "sender": email_msg.sender,
        "sender_name": email_msg.sender_name,
        "recipients": email_msg.recipients,
        "cc": email_msg.cc,
        "date": email_msg.date.isoformat() if email_msg.date else None,
        "body_text": email_msg.body_text,
        "body_html": email_msg.body_html,
        "attachments": [a.model_dump() for a in email_msg.attachments],
        "folder": email_msg.folder,
        "summary": email_msg.summary,
    }


def _email_to_eml(email_msg: EmailMessage) -> str:
    """Convert EmailMessage to RFC822 .eml format."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = email_msg.subject
    if email_msg.sender_name:
        msg["From"] = f"{email_msg.sender_name} <{email_msg.sender}>"
    else:
        msg["From"] = email_msg.sender
    msg["To"] = ", ".join(email_msg.recipients)
    if email_msg.cc:
        msg["Cc"] = ", ".join(email_msg.cc)
    if email_msg.date:
        msg["Date"] = email_msg.date.strftime("%a, %d %b %Y %H:%M:%S %z")
    if email_msg.message_id:
        msg["Message-ID"] = email_msg.message_id

    if email_msg.body_text:
        msg.attach(MIMEText(email_msg.body_text, "plain", "utf-8"))
    if email_msg.body_html:
        msg.attach(MIMEText(email_msg.body_html, "html", "utf-8"))

    return msg.as_string()


def backup_emails(
    emails: list[EmailMessage] | None = None,
    backup_format: str = "",
) -> dict:
    """Backup emails to local files. Returns stats."""
    fmt = backup_format or settings.backup_format
    backup_dir = settings.data_dir / "backups"
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    batch_dir = backup_dir / f"batch_{timestamp}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    if emails is None:
        emails = list_emails(limit=10000)

    stats = {"total": len(emails), "json_files": 0, "eml_files": 0, "errors": 0}

    # JSON export
    if fmt in ("json", "both"):
        json_dir = batch_dir / "json"
        json_dir.mkdir(exist_ok=True)
        for em in emails:
            try:
                date_prefix = em.date.strftime("%Y%m%d") if em.date else "nodate"
                safe_subj = "".join(
                    c if c.isalnum() or c in " -_" else "_"
                    for c in em.subject
                )[:60]
                filename = f"{date_prefix}_{safe_subj}_{em.id[:8]}.json"
                with open(json_dir / filename, "w", encoding="utf-8") as f:
                    json.dump(_email_to_dict(em), f, indent=2, ensure_ascii=False)
                stats["json_files"] += 1
                mark_backed_up(em.id)
            except Exception:
                logger.exception("Failed to backup email %s as JSON", em.id)
                stats["errors"] += 1

    # EML export
    if fmt in ("eml", "both"):
        eml_dir = batch_dir / "eml"
        eml_dir.mkdir(exist_ok=True)
        for em in emails:
            try:
                date_prefix = em.date.strftime("%Y%m%d") if em.date else "nodate"
                safe_subj = "".join(
                    c if c.isalnum() or c in " -_" else "_"
                    for c in em.subject
                )[:60]
                filename = f"{date_prefix}_{safe_subj}_{em.id[:8]}.eml"
                with open(eml_dir / filename, "w", encoding="utf-8") as f:
                    f.write(_email_to_eml(em))
                stats["eml_files"] += 1
                mark_backed_up(em.id)
            except Exception:
                logger.exception("Failed to backup email %s as EML", em.id)
                stats["errors"] += 1

    # Copy attachments
    att_dir = batch_dir / "attachments"
    att_dir.mkdir(exist_ok=True)
    for em in emails:
        for att in em.attachments:
            if att.local_path and Path(att.local_path).exists():
                try:
                    shutil.copy2(att.local_path, att_dir / Path(att.local_path).name)
                except Exception:
                    logger.exception("Failed to copy attachment %s", att.filename)

    logger.info("Backup complete: %s", stats)
    return stats


def get_backup_size_mb() -> float:
    """Return total backup size in MB."""
    backup_dir = settings.data_dir / "backups"
    if not backup_dir.exists():
        return 0.0
    total = sum(f.stat().st_size for f in backup_dir.rglob("*") if f.is_file())
    return round(total / (1024 * 1024), 2)


def list_backups() -> list[dict]:
    """List all backup batches."""
    backup_dir = settings.data_dir / "backups"
    if not backup_dir.exists():
        return []
    batches = []
    for d in sorted(backup_dir.iterdir(), reverse=True):
        if d.is_dir() and d.name.startswith("batch_"):
            file_count = sum(1 for f in d.rglob("*") if f.is_file())
            size_mb = sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / (1024 * 1024)
            batches.append({
                "name": d.name,
                "path": str(d),
                "files": file_count,
                "size_mb": round(size_mb, 2),
                "created": d.stat().st_mtime,
            })
    return batches
