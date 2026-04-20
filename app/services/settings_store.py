"""Persistent settings store — saves user config to JSON so no .env editing needed."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

SETTINGS_FILE = Path(settings.data_dir) / "user_settings.json"

# Fields that can be configured via the web UI
CONFIGURABLE_FIELDS = {
    "imap_host",
    "imap_port",
    "imap_user",
    "imap_password",
    "imap_folder",
    "smtp_host",
    "smtp_port",
    "smtp_user",
    "smtp_password",
    "azure_ai_endpoint",
    "azure_ai_key",
    "azure_ai_model",
    "sarvam_api_key",
    "whatsapp_token",
    "whatsapp_phone_id",
    "whatsapp_dad_phone",
    "whatsapp_secretary_phone",
    "briefing_hour",
    "briefing_recipient",
}

# Fields that should be masked when returned to the UI
SENSITIVE_FIELDS = {
    "imap_password",
    "smtp_password",
    "azure_ai_key",
    "sarvam_api_key",
    "whatsapp_token",
}


def load_saved_settings() -> dict:
    """Load saved settings from JSON file."""
    if not SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read settings file: %s", exc)
        return {}


def save_settings(updates: dict) -> dict:
    """Save settings to JSON and apply to running config."""
    current = load_saved_settings()

    for key, value in updates.items():
        if key not in CONFIGURABLE_FIELDS:
            continue
        if key in SENSITIVE_FIELDS and value == "********":
            continue
        current[key] = value

    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(current, indent=2))

    _apply_to_runtime(current)
    return get_current_settings()


def _apply_to_runtime(saved: dict) -> None:
    """Push saved values into the running Settings singleton."""
    for key, value in saved.items():
        if key in CONFIGURABLE_FIELDS and hasattr(settings, key):
            try:
                field_type = type(getattr(settings, key))
                object.__setattr__(settings, key, field_type(value))
            except (ValueError, TypeError) as exc:
                logger.warning("Cannot apply setting %s=%r: %s", key, value, exc)

    if "smtp_user" not in saved and settings.imap_user:
        object.__setattr__(settings, "smtp_user", settings.imap_user)
    if "smtp_password" not in saved and settings.imap_password:
        object.__setattr__(settings, "smtp_password", settings.imap_password)


def get_current_settings() -> dict:
    """Return current settings with sensitive fields masked."""
    result = {}
    for key in CONFIGURABLE_FIELDS:
        value = getattr(settings, key, "")
        if key in SENSITIVE_FIELDS and value:
            result[key] = "********"
        else:
            result[key] = value
    result["is_configured"] = bool(settings.imap_user)
    result["has_ai"] = bool(settings.azure_ai_key)
    result["has_sarvam"] = bool(settings.sarvam_api_key)
    result["has_whatsapp"] = bool(settings.whatsapp_token)
    return result


def apply_saved_on_startup() -> None:
    """Called at app startup to load saved settings into runtime."""
    saved = load_saved_settings()
    if saved:
        logger.info("Applying %d saved settings from %s", len(saved), SETTINGS_FILE)
        _apply_to_runtime(saved)
