"""提案メール用 CC アドレスの抽出・正規化。

ヘッダ Cc と本文の「CCに…」等を合算し、除外リストを差し引く。
トリガ表記は当面コード内固定。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)

# 本文 CC 記載のトリガ（固定）
BODY_CC_TRIGGERS = (
    "CCに",
    "ＣＣに",
    "CC:",
    "CC：",
    "ＣＣ:",
    "ＣＣ：",
    "【CC】",
    "［CC］",
)


def normalize_email(raw: str) -> str | None:
    text = (raw or "").strip().strip("<>").strip()
    if not text:
        return None
    match = EMAIL_RE.search(text)
    if not match:
        return None
    return match.group(0).lower()


def parse_address_list(header_value: str | None) -> list[str]:
    """Cc / To ヘッダ値からアドレス一覧を返す。"""
    if not header_value or not str(header_value).strip():
        return []
    # カンマ区切り（表示名付き "Name <a@b.com>" も EMAIL_RE で拾う）
    found: list[str] = []
    seen: set[str] = set()
    for match in EMAIL_RE.finditer(str(header_value)):
        addr = match.group(0).lower()
        if addr not in seen:
            seen.add(addr)
            found.append(addr)
    return found


def extract_cc_from_body(text: str | None) -> list[str]:
    """本文の CC 記載ブロックからアドレスを抽出する。"""
    if not text or not text.strip():
        return []

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    found: list[str] = []
    seen: set[str] = set()
    i = 0
    while i < len(lines):
        line = lines[i]
        trigger_pos = -1
        trigger_len = 0
        for trigger in BODY_CC_TRIGGERS:
            pos = line.find(trigger)
            if pos >= 0 and (trigger_pos < 0 or pos < trigger_pos):
                trigger_pos = pos
                trigger_len = len(trigger)
        if trigger_pos < 0:
            i += 1
            continue

        block_parts = [line[trigger_pos + trigger_len :]]
        j = i + 1
        while j < len(lines):
            nxt = lines[j]
            stripped = nxt.strip()
            if not stripped:
                break
            if re.match(r"^【[^】]+】", stripped) or re.match(r"^［[^］]+］", stripped):
                break
            # 次のトリガ行ならそこで止める
            if any(t in nxt for t in BODY_CC_TRIGGERS):
                break
            block_parts.append(nxt)
            j += 1

        block = "\n".join(block_parts)
        for match in EMAIL_RE.finditer(block):
            addr = match.group(0).lower()
            if addr not in seen:
                seen.add(addr)
                found.append(addr)
        i = j if j > i + 1 else i + 1

    return found


def resolve_proposal_cc(
    *,
    header_cc: Iterable[str] | None = None,
    body_text: str | None = None,
    exclude: Iterable[str] | None = None,
) -> list[str]:
    """ヘッダ Cc と本文抽出を合算し、除外リストを差し引く。"""
    merged: list[str] = []
    seen: set[str] = set()

    for raw in header_cc or []:
        addr = normalize_email(str(raw))
        if addr and addr not in seen:
            seen.add(addr)
            merged.append(addr)

    for addr in extract_cc_from_body(body_text):
        if addr not in seen:
            seen.add(addr)
            merged.append(addr)

    excluded = {a for a in (normalize_email(str(x)) for x in (exclude or [])) if a}
    return [addr for addr in merged if addr not in excluded]
