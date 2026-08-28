"""Anthropic Claude Messages API の薄いラッパー（BAT-002 / BAT-004 / 返信判定共用）。"""

from __future__ import annotations

import inspect
from typing import Any


DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"


def resolve_anthropic_model(model: str | None) -> str:
    text = (model or "").strip()
    return text or DEFAULT_ANTHROPIC_MODEL


def call_claude_messages(
    *,
    api_key: str,
    model: str | None,
    system: str,
    user: str,
    max_tokens: int = 4096,
    temperature: float = 0.1,
) -> str | None:
    """Claude Messages API を1回呼び、テキスト応答を返す。失敗時は None。"""
    key = (api_key or "").strip()
    if not key:
        return None
    try:
        from anthropic import Anthropic
    except ImportError:
        return None

    try:
        client = Anthropic(api_key=key)
        # anthropic SDK 1.x の Messages.create は temperature を受け付けない場合がある
        create_kwargs: dict[str, Any] = {
            "model": resolve_anthropic_model(model),
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            if "temperature" in inspect.signature(client.messages.create).parameters:
                create_kwargs["temperature"] = temperature
        except (TypeError, ValueError):
            pass
        response = client.messages.create(**create_kwargs)
    except Exception:
        return None

    return _content_to_text(getattr(response, "content", None))


def _content_to_text(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        text = content.strip()
        return text or None
    parts: list[str] = []
    for block in content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
        elif isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text")
            if text:
                parts.append(str(text))
    joined = "".join(parts).strip()
    return joined or None
