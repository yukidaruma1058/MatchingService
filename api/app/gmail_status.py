"""Gmail 連携状態の取得。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.config import settings
from app.gmail_client import GmailClient, GmailConfigError
from app.gmail_credentials import credentials_configured, ensure_gmail_credentials_file, gmail_setup_hint

GmailAuthStatus = Literal["connected", "disconnected", "expired"]


class GmailStatus(BaseModel):
    gmail_connected_account: str | None = None
    gmail_auth_status: GmailAuthStatus = "disconnected"
    gmail_last_checked_at: str | None = None
    gmail_error_code: str | None = None
    gmail_setup_required: bool = False
    gmail_setup_message: str | None = None
    gmail_oauth_client_configured: bool = False
    gmail_oauth_client_id: str | None = None


def fetch_gmail_status(
    db_settings: dict[str, Any] | None = None,
    *,
    redirect_uri: str | None = None,
) -> GmailStatus:
    """OAuth ファイルと Gmail API で連携状態を確認する。"""
    checked_at = datetime.now(UTC).isoformat()
    oauth_configured = credentials_configured(db_settings)
    client_id = None
    if db_settings:
        raw_id = db_settings.get("gmail_oauth_client_id")
        if isinstance(raw_id, str) and raw_id.strip():
            client_id = raw_id.strip()
    if not client_id and settings.gmail_client_id:
        client_id = settings.gmail_client_id

    if not oauth_configured:
        return GmailStatus(
            gmail_auth_status="disconnected",
            gmail_last_checked_at=checked_at,
            gmail_error_code="ERR-0018",
            gmail_setup_required=True,
            gmail_setup_message=gmail_setup_hint(redirect_uri),
            gmail_oauth_client_configured=False,
            gmail_oauth_client_id=client_id,
        )

    if not ensure_gmail_credentials_file(db_settings, redirect_uri=redirect_uri):
        return GmailStatus(
            gmail_auth_status="disconnected",
            gmail_last_checked_at=checked_at,
            gmail_error_code="ERR-0018",
            gmail_setup_required=True,
            gmail_setup_message=gmail_setup_hint(redirect_uri),
            gmail_oauth_client_configured=oauth_configured,
            gmail_oauth_client_id=client_id,
        )

    if not settings.gmail_token_path.exists():
        return GmailStatus(
            gmail_auth_status="disconnected",
            gmail_last_checked_at=checked_at,
            gmail_error_code=None,
            gmail_setup_required=False,
            gmail_setup_message=None,
            gmail_oauth_client_configured=True,
            gmail_oauth_client_id=client_id,
        )

    client = GmailClient(str(settings.gmail_credentials_path), str(settings.gmail_token_path))

    try:
        client.connect()
        profile = client.get_profile()
        return GmailStatus(
            gmail_connected_account=profile.get("emailAddress"),
            gmail_auth_status="connected",
            gmail_last_checked_at=checked_at,
            gmail_error_code=None,
            gmail_setup_required=False,
            gmail_setup_message=None,
            gmail_oauth_client_configured=True,
            gmail_oauth_client_id=client_id,
        )
    except GmailConfigError as exc:
        status: GmailAuthStatus = "expired" if exc.error_code == "ERR-0019" else "disconnected"
        return GmailStatus(
            gmail_connected_account=None,
            gmail_auth_status=status,
            gmail_last_checked_at=checked_at,
            gmail_error_code=exc.error_code,
            gmail_setup_required=exc.error_code == "ERR-0018" and not oauth_configured,
            gmail_setup_message=gmail_setup_hint(redirect_uri) if exc.error_code == "ERR-0018" else None,
            gmail_oauth_client_configured=True,
            gmail_oauth_client_id=client_id,
        )
    except Exception:
        return GmailStatus(
            gmail_connected_account=None,
            gmail_auth_status="disconnected",
            gmail_last_checked_at=checked_at,
            gmail_error_code="ERR-0021",
            gmail_oauth_client_configured=True,
            gmail_oauth_client_id=client_id,
        )
