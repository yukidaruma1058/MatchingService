"""Gmail OAuth credentials.json の確保。

優先順位: 既存ファイル > 環境変数 > system_settings（画面保存）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.setting_keys import (
    SETTING_KEY_GMAIL_OAUTH_CLIENT_ID,
    SETTING_KEY_GMAIL_OAUTH_CLIENT_SECRET,
    SETTING_KEY_GMAIL_OAUTH_PROJECT_ID,
)


def _pick_str(db_settings: dict[str, Any] | None, key: str) -> str:
    if not db_settings:
        return ""
    raw = db_settings.get(key)
    if isinstance(raw, str):
        return raw.strip()
    if raw is None:
        return ""
    return str(raw).strip()


def resolve_oauth_credentials(db_settings: dict[str, Any] | None = None) -> tuple[str, str, str] | None:
    """client_id / client_secret / project_id を解決する。"""
    client_id = settings.gmail_client_id or _pick_str(db_settings, SETTING_KEY_GMAIL_OAUTH_CLIENT_ID)
    client_secret = settings.gmail_client_secret or _pick_str(db_settings, SETTING_KEY_GMAIL_OAUTH_CLIENT_SECRET)
    project_id = (
        settings.gmail_oauth_project_id
        or _pick_str(db_settings, SETTING_KEY_GMAIL_OAUTH_PROJECT_ID)
        or "matching-service"
    )
    if client_id and client_secret:
        return client_id, client_secret, project_id
    if settings.gmail_credentials_path.exists():
        return "__file__", "__file__", project_id
    return None


def credentials_configured(db_settings: dict[str, Any] | None = None) -> bool:
    """OAuth クライアントが利用可能か。"""
    if settings.gmail_credentials_path.exists():
        return True
    return resolve_oauth_credentials(db_settings) is not None


def ensure_gmail_credentials_file(
    db_settings: dict[str, Any] | None = None,
    *,
    force: bool = False,
    redirect_uri: str | None = None,
) -> bool:
    """credentials.json を用意する。成功時 True、未設定時 False。"""
    credentials_path: Path = settings.gmail_credentials_path
    resolved = resolve_oauth_credentials(db_settings)

    if resolved is None:
        return credentials_path.exists()

    if resolved[0] == "__file__":
        return credentials_path.exists()

    if credentials_path.exists() and not force:
        return True

    client_id, client_secret, project_id = resolved
    if redirect_uri is None:
        from app.gmail_oauth_urls import resolve_gmail_oauth_redirect_uri

        oauth_redirect_uri = resolve_gmail_oauth_redirect_uri()
    else:
        oauth_redirect_uri = redirect_uri
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "project_id": project_id,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [oauth_redirect_uri],
        }
    }
    credentials_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return True


def gmail_setup_hint(redirect_uri: str | None = None) -> str:
    """未設定時に利用者へ表示する短い案内。"""
    uri = redirect_uri or settings.gmail_oauth_redirect_uri or "（画面上部のリダイレクト URI）"
    return (
        "Google Cloud で OAuth クライアントを作成し、Client ID / Secret を入力して「Gmailと連携する」を押してください。"
        f" 詳しい手順は「Gmail 初回連携」横の ? にカーソルを合わせて確認できます。リダイレクト URI: {uri}"
    )
