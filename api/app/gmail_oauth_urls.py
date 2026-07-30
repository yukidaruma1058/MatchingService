"""Gmail OAuth 用の公開 URL をリクエスト・環境変数から解決する。"""

from __future__ import annotations

from urllib.parse import urljoin, urlparse

from fastapi import Request

from app.config import settings

OAUTH_CALLBACK_PATH = "/api/gmail/oauth/callback"
WEB_SETTINGS_PATH = "/settings"
LOCAL_API_BASE_URL = "http://localhost:8000"
LOCAL_WEB_SETTINGS_URL = "http://localhost:3000/settings"


def _first_header_value(request: Request, name: str) -> str | None:
    raw = request.headers.get(name)
    if not raw:
        return None
    return raw.split(",")[0].strip() or None


def resolve_api_public_base_url(request: Request | None = None) -> str:
    """API の公開ベース URL（スキーム + ホスト）を返す。"""
    if settings.api_public_base_url.strip():
        return settings.api_public_base_url.strip().rstrip("/")

    if request is not None:
        forwarded_proto = _first_header_value(request, "x-forwarded-proto")
        forwarded_host = _first_header_value(request, "x-forwarded-host") or _first_header_value(request, "host")
        if forwarded_proto and forwarded_host:
            return f"{forwarded_proto}://{forwarded_host}".rstrip("/")
        return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")

    if settings.gmail_oauth_redirect_uri.strip():
        parsed = urlparse(settings.gmail_oauth_redirect_uri.strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"

    return LOCAL_API_BASE_URL


def resolve_gmail_oauth_redirect_uri(request: Request | None = None) -> str:
    """Google Cloud に登録する OAuth リダイレクト URI を返す。"""
    if settings.gmail_oauth_redirect_uri.strip():
        return settings.gmail_oauth_redirect_uri.strip()
    base = resolve_api_public_base_url(request)
    return urljoin(f"{base}/", OAUTH_CALLBACK_PATH.lstrip("/"))


def resolve_web_settings_url(request: Request | None = None) -> str:
    """OAuth 完了後に戻す Web 設定画面 URL を返す。"""
    if settings.web_settings_url.strip():
        return settings.web_settings_url.strip().rstrip("/")

    if settings.web_public_base_url.strip():
        base = settings.web_public_base_url.strip().rstrip("/")
        return urljoin(f"{base}/", WEB_SETTINGS_PATH.lstrip("/"))

    if request is not None:
        origin = _first_header_value(request, "origin")
        if origin:
            return urljoin(f"{origin.rstrip('/')}/", WEB_SETTINGS_PATH.lstrip("/"))
        referer = request.headers.get("referer")
        if referer:
            parsed = urlparse(referer)
            if parsed.scheme and parsed.netloc:
                base = f"{parsed.scheme}://{parsed.netloc}"
                return urljoin(f"{base}/", WEB_SETTINGS_PATH.lstrip("/"))

    return LOCAL_WEB_SETTINGS_URL
