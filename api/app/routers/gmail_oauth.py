"""Gmail OAuth 再連携 API。"""

from __future__ import annotations

import secrets
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow
from sqlalchemy.orm import Session

from app.config import settings
from app.db import load_settings
from app.deps import get_db
from app.gmail_client import GMAIL_SCOPES, GmailConfigError
from app.gmail_credentials import ensure_gmail_credentials_file, gmail_setup_hint, resolve_oauth_credentials
from app.gmail_oauth_urls import resolve_gmail_oauth_redirect_uri, resolve_web_settings_url

router = APIRouter(prefix="/api/gmail", tags=["gmail"])

_pending_oauth_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600


def _cleanup_expired_states() -> None:
    now = time.time()
    expired = [state for state, created_at in _pending_oauth_states.items() if now - created_at > _STATE_TTL_SECONDS]
    for state in expired:
        _pending_oauth_states.pop(state, None)


def _build_flow(request: Request, db_settings: dict, state: str | None = None) -> Flow:
    redirect_uri = resolve_gmail_oauth_redirect_uri(request)
    resolved = resolve_oauth_credentials(db_settings)
    force = resolved is not None and resolved[0] != "__file__"
    if not ensure_gmail_credentials_file(db_settings, force=force, redirect_uri=redirect_uri):
        raise GmailConfigError("ERR-0018", gmail_setup_hint(redirect_uri))
    return Flow.from_client_secrets_file(
        str(settings.gmail_credentials_path),
        scopes=GMAIL_SCOPES,
        redirect_uri=redirect_uri,
        state=state,
    )


def _settings_redirect(request: Request, query: dict[str, str]) -> str:
    base = resolve_web_settings_url(request).rstrip("/")
    return f"{base}?{urlencode(query)}"


@router.get("/oauth/start")
def start_gmail_oauth(request: Request, session: Session = Depends(get_db)) -> RedirectResponse:
    """Google OAuth 同意画面へリダイレクトする。"""
    _cleanup_expired_states()
    db_settings = load_settings(session)
    try:
        flow = _build_flow(request, db_settings)
    except GmailConfigError as exc:
        return RedirectResponse(
            _settings_redirect(request, {"gmail": "error", "error_code": exc.error_code}),
        )

    state = secrets.token_urlsafe(32)
    _pending_oauth_states[state] = time.time()

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state,
        prompt="consent",
    )
    return RedirectResponse(authorization_url)


@router.get("/oauth/callback", name="gmail_oauth_callback")
def gmail_oauth_callback(
    request: Request,
    session: Session = Depends(get_db),
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
) -> RedirectResponse:
    """OAuth コールバック。token.json を更新し設定画面へ戻す。"""
    db_settings = load_settings(session)

    if error:
        return RedirectResponse(_settings_redirect(request, {"gmail": "error", "error_code": "ERR-0019"}))

    if not code or not state or state not in _pending_oauth_states:
        return RedirectResponse(_settings_redirect(request, {"gmail": "error", "error_code": "ERR-0019"}))

    _pending_oauth_states.pop(state, None)

    try:
        flow = _build_flow(request, db_settings, state=state)
        flow.fetch_token(code=code)
        credentials = flow.credentials
        if credentials is None:
            raise GmailConfigError("ERR-0019", "Gmail OAuth token exchange failed")

        settings.gmail_token_path.parent.mkdir(parents=True, exist_ok=True)
        settings.gmail_token_path.write_text(credentials.to_json())
    except GmailConfigError as exc:
        return RedirectResponse(
            _settings_redirect(request, {"gmail": "error", "error_code": exc.error_code}),
        )
    except Exception:
        return RedirectResponse(_settings_redirect(request, {"gmail": "error", "error_code": "ERR-0019"}))

    return RedirectResponse(_settings_redirect(request, {"gmail": "linked"}))
