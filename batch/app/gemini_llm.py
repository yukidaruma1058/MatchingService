"""Gemini generateContent の薄いラッパー（BAT-002 / BAT-004 共用）。"""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_KEY_QUERY_RE = re.compile(r"([?&]key=)[^&\s]+", re.IGNORECASE)
_BODY_LOG_LIMIT = 1500


def resolve_gemini_model(model: str | None) -> str:
    text = (model or "").strip()
    return text or DEFAULT_GEMINI_MODEL


def resolve_gemini_batch_size(value: int | None, *, default: int = 20) -> int:
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(50, n))


def resolve_gemini_batch_parallel(value: int | None, *, default: int = 10) -> int:
    """1波で同時送信する20通パック数。無料 RPM 15 に合わせて上限 15。"""
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(15, n))


def resolve_gemini_batch_wave_interval_seconds(value: int | None, *, default: int = 60) -> int:
    """次波・直列再送まで待つ秒数。0 で待機なし。"""
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        n = default
    return max(0, min(180, n))


def resolve_gemini_input_tpm(value: int | None, *, default: int = 250_000) -> int:
    """1分あたりの入力トークン上限。再送を即時にするかの判定に使う。"""
    try:
        n = int(value) if value is not None else default
    except (TypeError, ValueError):
        n = default
    return max(1, min(10_000_000, n))


def redact_gemini_secrets(text: str) -> str:
    """ログ用に URL 中の API キーを隠す。"""
    return _KEY_QUERY_RE.sub(r"\1REDACTED", text or "")


def classify_gemini_failure(
    *,
    http_status: int | None,
    google_status: str = "",
    message: str = "",
    finish_reason: str = "",
    block_reason: str = "",
) -> str:
    """キー/権限・スキーマ・モデル・レート制限などを切り分けるラベルを返す。"""
    blob = f"{google_status} {message} {finish_reason} {block_reason}".lower()
    if block_reason or finish_reason.upper() in {
        "SAFETY",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "RECITATION",
    }:
        return "blocked"
    if http_status in (401, 403) or any(
        token in blob
        for token in ("unauthenticated", "permission_denied", "permission denied", "api key", "api_key")
    ):
        return "key_or_permission"
    if http_status == 404 or "not_found" in blob or "not found" in blob:
        return "model_not_found"
    if http_status == 429 or "resource_exhausted" in blob or "rate" in blob:
        return "rate_limit"
    if http_status == 400 or "invalid_argument" in blob or "schema" in blob or "responseschema" in blob:
        return "schema_or_request"
    if http_status is None:
        return "network"
    if http_status:
        return "http_error"
    return "unknown"


def call_gemini_json(
    *,
    api_key: str,
    model: str | None,
    system: str,
    user: str,
    response_schema: dict[str, Any] | None = None,
    temperature: float = 0.1,
    timeout_seconds: int = 180,
    purpose: str = "generate",
) -> str | None:
    """Gemini を1回呼び、JSON テキストを返す。失敗時は None（理由はバッチログへ）。"""
    key = (api_key or "").strip()
    if not key:
        return None

    resolved_model = resolve_gemini_model(model)
    generation_config: dict[str, Any] = {
        "temperature": temperature,
        "responseMimeType": "application/json",
    }
    if response_schema:
        generation_config["responseSchema"] = response_schema

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": generation_config,
    }
    url = _GEMINI_ENDPOINT.format(model=resolved_model) + "?key=" + urllib.parse.quote(key, safe="")
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = _read_http_error_body(exc)
        google_status, google_message = _parse_google_error(body)
        _log_gemini_failure(
            purpose=purpose,
            model=resolved_model,
            failure_class=classify_gemini_failure(
                http_status=exc.code,
                google_status=google_status,
                message=google_message or str(exc.reason or ""),
            ),
            http_status=exc.code,
            google_status=google_status,
            detail=google_message or redact_gemini_secrets(str(exc.reason or exc)),
            body_excerpt=redact_gemini_secrets(body)[:_BODY_LOG_LIMIT],
            has_response_schema=bool(response_schema),
        )
        return None
    except TimeoutError as exc:
        _log_gemini_failure(
            purpose=purpose,
            model=resolved_model,
            failure_class="timeout",
            detail=str(exc),
            has_response_schema=bool(response_schema),
        )
        return None
    except urllib.error.URLError as exc:
        _log_gemini_failure(
            purpose=purpose,
            model=resolved_model,
            failure_class="network",
            detail=redact_gemini_secrets(str(getattr(exc, "reason", exc))),
            has_response_schema=bool(response_schema),
        )
        return None
    except (json.JSONDecodeError, OSError) as exc:
        _log_gemini_failure(
            purpose=purpose,
            model=resolved_model,
            failure_class="parse_error" if isinstance(exc, json.JSONDecodeError) else "network",
            detail=str(exc),
            has_response_schema=bool(response_schema),
        )
        return None
    except Exception as exc:  # noqa: BLE001
        _log_gemini_failure(
            purpose=purpose,
            model=resolved_model,
            failure_class="unknown",
            detail=redact_gemini_secrets(str(exc)),
            has_response_schema=bool(response_schema),
        )
        return None

    text = _response_text(raw)
    if text:
        return text

    candidate = _first_candidate(raw)
    prompt_feedback = raw.get("promptFeedback") if isinstance(raw.get("promptFeedback"), dict) else {}
    finish_reason = str((candidate or {}).get("finishReason") or "")
    block_reason = str(prompt_feedback.get("blockReason") or "")
    _log_gemini_failure(
        purpose=purpose,
        model=resolved_model,
        failure_class=classify_gemini_failure(
            http_status=200,
            message="empty generateContent text",
            finish_reason=finish_reason,
            block_reason=block_reason,
        )
        if (finish_reason or block_reason)
        else "empty_candidates",
        http_status=200,
        finish_reason=finish_reason or None,
        block_reason=block_reason or None,
        detail="generateContent returned no JSON text",
        body_excerpt=redact_gemini_secrets(json.dumps(raw, ensure_ascii=False)[:_BODY_LOG_LIMIT]),
        has_response_schema=bool(response_schema),
    )
    return None


def _read_http_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read()
    except Exception:
        return ""
    if not raw:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _parse_google_error(body: str) -> tuple[str, str]:
    if not (body or "").strip():
        return "", ""
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return "", body[:_BODY_LOG_LIMIT]
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return "", body[:_BODY_LOG_LIMIT]
    status = str(error.get("status") or "")
    message = str(error.get("message") or "")
    return status, message


def _first_candidate(raw: dict[str, Any]) -> dict[str, Any] | None:
    candidates = raw.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return None
    first = candidates[0]
    return first if isinstance(first, dict) else None


def _response_text(raw: dict[str, Any]) -> str | None:
    candidate = _first_candidate(raw)
    if candidate is None:
        return None
    content = candidate.get("content")
    if not isinstance(content, dict):
        return None
    parts = content.get("parts")
    if not isinstance(parts, list):
        return None
    texts: list[str] = []
    for part in parts:
        if isinstance(part, dict) and part.get("text"):
            texts.append(str(part["text"]))
    joined = "".join(texts).strip()
    return joined or None


def _log_gemini_failure(
    *,
    purpose: str,
    model: str,
    failure_class: str,
    detail: str,
    http_status: int | None = None,
    google_status: str = "",
    finish_reason: str | None = None,
    block_reason: str | None = None,
    body_excerpt: str = "",
    has_response_schema: bool = False,
) -> None:
    extra: dict[str, Any] = {
        "purpose": purpose,
        "model": model,
        "failure_class": failure_class,
        "has_response_schema": has_response_schema,
    }
    if http_status is not None:
        extra["http_status"] = http_status
    if google_status:
        extra["google_status"] = google_status
    if finish_reason:
        extra["finish_reason"] = finish_reason
    if block_reason:
        extra["block_reason"] = block_reason
    if body_excerpt:
        extra["body_excerpt"] = body_excerpt
    try:
        from app.logging_util import get_batch_logger, log_error_event

        log_error_event(
            get_batch_logger(),
            event="gemini.call_failed",
            error_code="ERR-0025",
            detail=detail[:_BODY_LOG_LIMIT],
            operation="Gemini API",
            method_name="call_gemini_json",
            job_id="gemini",
            function_id="BATCH",
            module_name="app.gemini_llm",
            extra=extra,
        )
        return
    except Exception:
        logging.getLogger("batch").error(
            "gemini.call_failed failure_class=%s http_status=%s google_status=%s detail=%s extra=%s",
            failure_class,
            http_status,
            google_status,
            (detail or "")[:_BODY_LOG_LIMIT],
            json.dumps(extra, ensure_ascii=False)[:_BODY_LOG_LIMIT],
        )
