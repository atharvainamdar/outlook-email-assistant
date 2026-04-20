"""Application configuration via environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings


def _default_data_dir() -> Path:
    """Use /data on Fly.io (persistent volume), ~/email-assistant-data locally."""
    fly_vol = Path("/data")
    if fly_vol.exists() and fly_vol.is_dir():
        return fly_vol
    return Path.home() / "email-assistant-data"


class Settings(BaseSettings):
    # ── General ───────────────────────────────────────────────────────────
    app_title: str = "Ariya Email Assistant"
    data_dir: Path = _default_data_dir()
    db_path: str = ""  # resolved in validator
    log_level: str = "INFO"

    # ── IMAP (primary ingestion) ──────────────────────────────────────────
    imap_host: str = "outlook.office365.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    imap_use_ssl: bool = True
    imap_poll_interval_seconds: int = 120  # 2 minutes

    # ── SMTP (sending) ────────────────────────────────────────────────────
    smtp_host: str = "smtp-mail.outlook.com"
    smtp_port: int = 587
    smtp_user: str = ""  # defaults to imap_user
    smtp_password: str = ""  # defaults to imap_password

    # ── Azure AI (summarisation / drafting) ───────────────────────────────
    azure_ai_endpoint: str = ""
    azure_ai_key: str = ""
    azure_ai_model: str = "gpt-4o"
    azure_ai_api_version: str = "2024-12-01-preview"

    # ── Backup ────────────────────────────────────────────────────────────
    backup_format: Literal["json", "eml", "both"] = "both"
    max_backup_age_days: int = 0  # 0 = back up everything

    # ── Webhook (fallback ingestion when IMAP blocked) ────────────────────
    webhook_secret: str = ""  # shared secret for forwarding endpoint

    # ── WhatsApp ──────────────────────────────────────────────────────────
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_dad_phone: str = ""
    whatsapp_secretary_phone: str = ""

    # ── Sarvam AI (voice — Hindi/Marathi) ─────────────────────────────────
    sarvam_api_key: str = ""

    # ── Daily Briefing ────────────────────────────────────────────────────
    briefing_hour: int = 8  # 8 AM
    briefing_recipient: str = ""  # defaults to imap_user

    # ── Dashboard ─────────────────────────────────────────────────────────
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "EA_", "env_file": ".env", "extra": "ignore"}

    def model_post_init(self, __context: object) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "backups").mkdir(exist_ok=True)
        (self.data_dir / "attachments").mkdir(exist_ok=True)
        if not self.db_path:
            self.db_path = str(self.data_dir / "emails.db")
        if not self.smtp_user:
            self.smtp_user = self.imap_user
        if not self.smtp_password:
            self.smtp_password = self.imap_password


settings = Settings()
