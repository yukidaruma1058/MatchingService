"""返信本文から OK/NG をキーワード判定する。"""

from __future__ import annotations

import re
from typing import Literal

Judgment = Literal["ok", "ng", "unknown"]

# 設定に無くても拾いたい、案件別返信でよく使う表現
_BUILTIN_OK_KEYWORDS = (
    "進めさせて",
    "進めてください",
    "進めてまいり",
    "進めます",
    "前向き",
    "よろしくお願いします",
    "お願いいたします",
    "ご提案ください",
    "候補として",
)
_BUILTIN_NG_KEYWORDS = (
    "辞退",
    "見送り",
    "他決",
    "今回は結構",
    "対象外",
)

_ITEM_MARKER_RE = re.compile(r"【\s*(\d+)\s*】")
_ITEM_HEADER_RE = re.compile(r"【\s*(\d+)\s*】\s*(.+?)(?=\n|$)")


def parse_keywords(raw: str | None) -> list[str]:
    if not raw:
        return []
    items: list[str] = []
    for line in str(raw).replace(",", "\n").splitlines():
        text = line.strip()
        if text:
            items.append(text)
    return items


def merge_keywords(configured: list[str], builtin: tuple[str, ...]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for keyword in [*configured, *builtin]:
        key = keyword.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(keyword.strip())
    return merged


def judge_reply_body(body_text: str | None, *, ok_keywords: list[str], ng_keywords: list[str]) -> Judgment:
    """NG キーワード優先。どちらも無ければ unknown。"""
    text = (body_text or "").strip()
    if not text:
        return "unknown"
    lowered = text.lower()
    for keyword in ng_keywords:
        if keyword and keyword.lower() in lowered:
            return "ng"
    for keyword in ok_keywords:
        if keyword and keyword.lower() in lowered:
            return "ok"
    return "unknown"


def split_reply_by_item_markers(body_text: str | None) -> dict[int, str]:
    """返信本文を 【N】 単位のセグメントに分割する。"""
    text = body_text or ""
    matches = list(_ITEM_MARKER_RE.finditer(text))
    if not matches:
        return {}
    segments: dict[int, str] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        segments[int(match.group(1))] = text[start:end]
    return segments


def parse_proposal_item_titles(proposal_body: str | None) -> dict[int, str]:
    """提案本文の 【N】タイトル を抽出する。"""
    titles: dict[int, str] = {}
    for match in _ITEM_HEADER_RE.finditer(proposal_body or ""):
        titles[int(match.group(1))] = match.group(2).strip()
    return titles


def resolve_item_index_for_title(proposal_body: str | None, title: str | None) -> int | None:
    """提案本文の番号付き項目から、タイトルに対応する番号を返す。"""
    needle = (title or "").strip()
    if not needle:
        return None
    for index, item_title in parse_proposal_item_titles(proposal_body).items():
        if needle == item_title or needle in item_title or item_title in needle:
            return index
    return None


def judge_reply_for_item(
    body_text: str | None,
    *,
    item_index: int | None,
    ok_keywords: list[str],
    ng_keywords: list[str],
) -> Judgment:
    """複数案件返信向け。item_index があればその【N】セグメントだけ判定する。"""
    ok = merge_keywords(ok_keywords, _BUILTIN_OK_KEYWORDS)
    ng = merge_keywords(ng_keywords, _BUILTIN_NG_KEYWORDS)
    segments = split_reply_by_item_markers(body_text)
    if item_index is not None and item_index in segments:
        return judge_reply_body(segments[item_index], ok_keywords=ok, ng_keywords=ng)
    if segments:
        # 番号付き返信なのに当該番号が無い場合は不明
        return "unknown"
    return judge_reply_body(body_text, ok_keywords=ok, ng_keywords=ng)
