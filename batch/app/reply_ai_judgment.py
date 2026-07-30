"""返信本文の OK/NG を AI（Cursor → OpenAI）で判定する。

複数案件/人材への1通返信を、候補リスト付きで一度に判定する。
AI が使えない場合はキーワード判定へフォールバックする。
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from app.reply_judgment import Judgment, judge_reply_for_item


def _get_logger() -> logging.Logger | None:
    try:
        from app.logging_util import get_batch_logger

        return get_batch_logger()
    except Exception:  # noqa: BLE001
        return None


def _log_error(**kwargs: Any) -> None:
    try:
        from app.logging_util import log_error_event

        logger = kwargs.pop("logger", None) or _get_logger()
        if logger is None:
            return
        log_error_event(logger, **kwargs)
    except Exception:  # noqa: BLE001
        return


class AiSettings(Protocol):
    cursor_api_key: str
    openai_api_key: str
    openai_model: str


@dataclass(frozen=True)
class ReplyJudgeItem:
    """AI に渡す判定対象（提案1件分）。"""

    proposal_id: UUID
    title: str
    item_index: int | None = None


def _parse_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_judgment(value: Any) -> Judgment | None:
    text = str(value or "").strip().lower()
    if text in {"ok", "ng", "unknown"}:
        return text  # type: ignore[return-value]
    if text in {"承諾", "前向き", "よろしく"}:
        return "ok"
    if text in {"見送り", "辞退", "ng", "no"}:
        return "ng"
    return None


def _call_cursor(prompt: str, cfg: AiSettings, *, logger: logging.Logger | None = None) -> str | None:
    if not (cfg.cursor_api_key or "").strip():
        return None
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError as exc:
        _log_error(
            logger=logger,
            event="outreach.reply_sync.cursor_unavailable",
            error_code="ERR-0030",
            detail=str(exc),
            operation="返信AI判定 Cursor SDK",
            method_name="_call_cursor",
            job_id="reply_sync",
            function_id="BAT-008",
            module_name="app.reply_ai_judgment",
        )
        return None

    try:
        with tempfile.TemporaryDirectory(prefix="bat008-cursor-") as cwd:
            result = Agent.prompt(
                prompt,
                AgentOptions(
                    api_key=cfg.cursor_api_key,
                    model="composer-2.5",
                    local=LocalAgentOptions(cwd=cwd),
                ),
            )
        text = getattr(result, "result", None) or str(result)
        return str(text) if text else None
    except Exception as exc:  # noqa: BLE001
        _log_error(
            logger=logger,
            event="outreach.reply_sync.cursor_failed",
            error_code="ERR-0030",
            detail=str(exc),
            operation="返信AI判定 Cursor",
            method_name="_call_cursor",
            job_id="reply_sync",
            function_id="BAT-008",
            module_name="app.reply_ai_judgment",
        )
        return None


def _call_openai(prompt: str, cfg: AiSettings, *, logger: logging.Logger | None = None) -> str | None:
    if not (cfg.openai_api_key or "").strip():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=cfg.openai_api_key)
        response = client.chat.completions.create(
            model=cfg.openai_model or "gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an SES sales assistant that classifies email replies. "
                        "Reply with a single JSON object only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        content = response.choices[0].message.content
        return content if content else None
    except Exception as exc:  # noqa: BLE001
        _log_error(
            logger=logger,
            event="outreach.reply_sync.openai_failed",
            error_code="ERR-0030",
            detail=str(exc),
            operation="返信AI判定 OpenAI",
            method_name="_call_openai",
            job_id="reply_sync",
            function_id="BAT-008",
            module_name="app.reply_ai_judgment",
        )
        return None


def _build_prompt(items: list[ReplyJudgeItem], reply_body: str) -> str:
    lines = []
    for index, item in enumerate(items, start=1):
        marker = f"【{item.item_index}】" if item.item_index is not None else f"#{index}"
        lines.append(f"- id={item.proposal_id} marker={marker} title={item.title}")
    catalog = "\n".join(lines)
    return (
        "あなたは SES マッチングの返信判定者です。\n"
        "1通の返信メールを読み、提案した各候補（案件または人材）ごとに "
        "ok / ng / unknown を判定してください。\n"
        "- ok: 前向き・承諾・進めたい・よろしくお願いします 等\n"
        "- ng: 辞退・見送り・他決・対象外 等\n"
        "- unknown: 判断材料不足、該当候補への言及なし\n"
        "番号【N】が無くても、案件名/人材名や「1と2はOK」のような表現から割り当ててください。\n"
        "JSON のみ返してください。形式:\n"
        '{"results":[{"id":"<proposal_id>","judgment":"ok|ng|unknown"}]}\n'
        "results は候補一覧の全 id を含めてください。\n\n"
        f"候補一覧:\n{catalog}\n\n"
        f"返信本文:\n{(reply_body or '').strip() or '（本文なし）'}\n"
    )


def _fallback_keyword_judgments(
    items: list[ReplyJudgeItem],
    reply_body: str | None,
    *,
    ok_keywords: list[str],
    ng_keywords: list[str],
) -> dict[UUID, Judgment]:
    return {
        item.proposal_id: judge_reply_for_item(
            reply_body,
            item_index=item.item_index,
            ok_keywords=ok_keywords,
            ng_keywords=ng_keywords,
        )
        for item in items
    }


def judge_replies_with_ai(
    items: list[ReplyJudgeItem],
    reply_body: str | None,
    *,
    cfg: AiSettings,
    ok_keywords: list[str] | None = None,
    ng_keywords: list[str] | None = None,
) -> dict[UUID, Judgment]:
    """候補ごとに ok/ng/unknown を返す。AI 失敗時はキーワード判定へフォールバック。"""
    if not items:
        return {}
    ok_keywords = ok_keywords or []
    ng_keywords = ng_keywords or []
    fallback = _fallback_keyword_judgments(
        items,
        reply_body,
        ok_keywords=ok_keywords,
        ng_keywords=ng_keywords,
    )
    if len(items) == 1 and not (reply_body or "").strip():
        return fallback

    logger = _get_logger()
    prompt = _build_prompt(items, reply_body or "")
    raw = _call_cursor(prompt, cfg, logger=logger) or _call_openai(prompt, cfg, logger=logger)
    if not raw:
        return fallback

    data = _parse_json(raw)
    results = data.get("results")
    if not isinstance(results, list):
        return fallback

    by_id = {str(item.proposal_id): item.proposal_id for item in items}
    judged: dict[UUID, Judgment] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        raw_id = str(row.get("id") or "").strip()
        proposal_id = by_id.get(raw_id)
        if proposal_id is None:
            continue
        judgment = _normalize_judgment(row.get("judgment"))
        if judgment is None:
            continue
        judged[proposal_id] = judgment

    # 欠けた候補はキーワード判定で補完
    for item in items:
        if item.proposal_id not in judged:
            judged[item.proposal_id] = fallback[item.proposal_id]
    return judged
