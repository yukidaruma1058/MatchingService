"""Gmail OAuth credentials.json の確保（バッチ用）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import Settings, settings


def _pick_str(db_settings: dict[str, Any] | None, key: str) -> str:
    if not db_settings:
        return ""
    raw = db_settings.get(key)
    if isinstance(raw, str):
        return raw.strip()
    if raw is None:
        return ""
    return str(raw).strip()


def ensure_gmail_credentials_file(
    cfg: Settings | None = None,
    db_settings: dict[str, Any] | None = None,
) -> bool:
    """credentials.json を用意する。成功時 True、未設定時 False。"""
    cfg = cfg or settings
    credentials_path = Path(cfg.gmail_credentials_path)
    if credentials_path.exists():
        return True

    client_id = cfg.gmail_client_id or _pick_str(db_settings, "gmail_oauth_client_id")
    client_secret = cfg.gmail_client_secret or _pick_str(db_settings, "gmail_oauth_client_secret")
    project_id = (
        cfg.gmail_oauth_project_id
        or _pick_str(db_settings, "gmail_oauth_project_id")
        or "matching-service"
    )
    redirect_uri = getattr(cfg, "gmail_oauth_redirect_uri", "http://localhost:8000/api/gmail/oauth/callback")

    if not client_id or not client_secret:
        return False

    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "project_id": project_id,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [redirect_uri],
        }
    }
    credentials_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return True
