"""Microsoft OAuth2 authentication for Outlook email access."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://outlook.office365.com/IMAP.AccessAsUser.All",
    "https://outlook.office365.com/SMTP.Send",
]

TOKEN_FILE = Path(settings.data_dir) / "ms_token_cache.json"


def _get_msal_app():
    """Create an MSAL confidential client application."""
    import msal

    cache = msal.SerializableTokenCache()
    if TOKEN_FILE.exists():
        cache.deserialize(TOKEN_FILE.read_text())

    app = msal.ConfidentialClientApplication(
        client_id=settings.ms_client_id,
        client_credential=settings.ms_client_secret,
        authority=f"https://login.microsoftonline.com/{settings.ms_tenant_id}",
        token_cache=cache,
    )
    return app, cache


def _save_cache(cache):
    """Persist token cache to disk."""
    if cache.has_state_changed:
        TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_FILE.write_text(cache.serialize())


def get_auth_url() -> str:
    """Generate the Microsoft login URL for the user to visit."""
    app, _ = _get_msal_app()
    redirect_uri = settings.ms_redirect_uri
    if not redirect_uri:
        redirect_uri = "http://localhost:8000/auth/callback"

    flow = app.initiate_auth_code_flow(
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )
    # Save flow state for callback validation
    flow_file = Path(settings.data_dir) / "ms_auth_flow.json"
    flow_file.write_text(json.dumps(flow))

    return flow.get("auth_uri", "")


def handle_callback(query_params: dict) -> dict:
    """Exchange the authorization code for tokens."""
    app, cache = _get_msal_app()

    flow_file = Path(settings.data_dir) / "ms_auth_flow.json"
    if not flow_file.exists():
        return {"error": "No pending auth flow. Please start sign-in again."}

    flow = json.loads(flow_file.read_text())

    result = app.acquire_token_by_auth_code_flow(
        auth_code_flow=flow,
        auth_response=query_params,
    )

    _save_cache(cache)
    flow_file.unlink(missing_ok=True)

    if "error" in result:
        logger.error("OAuth2 error: %s - %s", result.get("error"), result.get("error_description"))
        return {"error": result.get("error_description", result.get("error"))}

    # Extract user info
    user_email = ""
    if "id_token_claims" in result:
        claims = result["id_token_claims"]
        user_email = claims.get("preferred_username", "") or claims.get("email", "")

    # Store the email in settings for IMAP use
    if user_email:
        from app.services.settings_store import save_settings
        save_settings({
            "imap_user": user_email,
            "imap_host": "outlook.office365.com",
            "imap_port": "993",
        })

    return {
        "success": True,
        "email": user_email,
        "name": result.get("id_token_claims", {}).get("name", ""),
    }


def get_access_token() -> str | None:
    """Get a valid access token, refreshing if needed."""
    app, cache = _get_msal_app()

    accounts = app.get_accounts()
    if not accounts:
        return None

    result = app.acquire_token_silent(
        scopes=SCOPES,
        account=accounts[0],
    )

    _save_cache(cache)

    if result and "access_token" in result:
        return result["access_token"]

    return None


def get_signed_in_user() -> dict | None:
    """Return info about the currently signed-in user, or None."""
    app, _ = _get_msal_app()
    accounts = app.get_accounts()
    if not accounts:
        return None
    return {
        "email": accounts[0].get("username", ""),
        "name": accounts[0].get("name", ""),
    }


def sign_out():
    """Clear the token cache (sign out)."""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
    flow_file = Path(settings.data_dir) / "ms_auth_flow.json"
    flow_file.unlink(missing_ok=True)


def is_configured() -> bool:
    """Check if OAuth2 credentials are configured."""
    return bool(settings.ms_client_id and settings.ms_client_secret)
