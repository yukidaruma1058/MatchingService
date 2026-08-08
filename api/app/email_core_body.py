"""案件取込メールからコア原文を抽出（LLM）し emails.body_core_text にキャッシュする。"""

from __future__ import annotations

import html
import logging
import re
from typing import Protocol, Sequence

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# プロンプトや後処理を変えたら上げる（旧キャッシュは再抽出対象）
_CORE_CACHE_VERSION = "v10"
_CACHE_PREFIX = f"[[core:{_CORE_CACHE_VERSION}]]\n"

_CORE_EXTRACT_SYSTEM = (
    "あなたは SES / 人材紹介の案件メール整形アシスタントです。"
    "案件スペックのコア原文だけを、一字一句変えずに抜き出してください。"
)

_CORE_EXTRACT_USER = """次の案件メールから、案件条件・スペックの原文ブロックだけを残してください。

厳守:
- 要約しない・言い換えない・創作しない（削除のみ）
- 出力はコア原文のプレーンテキストのみ
- HTML 実体（&nbsp; 等）は使わず通常の空白にする

必ず削除:
- 宛名・定型あいさつ・自己紹介（「○○の△△です」「いつもお世話になっております」）
- 冒頭の営業文（「下記にて案件情報」「見合う要員がいらっしゃいましたら」「CCに下記メール」など）
- 「ご提案時のお願い」「ご返信の際は〜」「件名は変更せず〜」など手続きメモ
- 末尾の署名・フッタ（■□■□、住所、TEL/FAX、携帯電話、URL、共通メール、配信停止、注力営業リスト）
- 「以上」「ご確認の程」「よろしくお願い」など締めの定型文

残す（区切り線〜案件項目本体）:
- 「ーーー案件情報ーーー」配下の【案件名】【作業内容】【単価】などの項目
- 【案件詳細】や ■案件名 / ■案件概要 配下の案件条件

件名: {subject}

本文:
{body}
"""

_CORP_PREFIX_RE = re.compile(
    r"^(株式会社|有限会社|合同会社|\(株\)|（株）|㈱)\s*",
)

_SENDER_INTRO_RE = re.compile(
    r"^"
    r"(?:私は|わたしは)?"
    r".{0,24}?"
    r"(?:の)?"
    r"[一-龥ぁ-んァ-ヶーA-Za-z]{1,16}"
    r"(?:です|でございます|と申します)"
    r"[。．]?"
    r"$"
)

_SALES_HIGHLIGHT_RE = re.compile(r"^[★☆●◆◇]\s*\S+")

# 案件スペック開始（優先度順）
_CORE_START_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^【\s*案件詳細\s*】"),
    re.compile(r"^[ー−–—-]{3,}\s*案件情報\s*[ー−–—-]{3,}"),
    re.compile(r"^【\s*案件名\s*】\s*[：:]"),
    re.compile(r"^■\s*案件名\s*[：:]"),
    re.compile(r"^■\s*案件名\s*$"),
    re.compile(r"^【\s*案件概要\s*】"),
    re.compile(r"^■\s*プロジェクト名\s*[：:]"),
    re.compile(r"^■\s*プロジェクト名\s*$"),
    re.compile(r"^◆\s*案件概要\s*$"),
    re.compile(r"^◆\s*案件概要\s*[：:]"),
    re.compile(r"^【\s*場所\s*】"),
]

# 署名・フッタ開始
_CORE_END_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^To unsubscribe\b", re.I),
    re.compile(r"^★\s*注力営業"),
    re.compile(r"^★\s*配信停止"),
    re.compile(r"^配信停止希望"),
    re.compile(r"^■□■"),
    re.compile(r"^□■□"),
    re.compile(r"^━{5,}"),
    re.compile(r"^─{5,}"),
    re.compile(r"^={10,}"),
    re.compile(r"^:{5,}"),
    re.compile(r"^※?件名は変更せず"),
    re.compile(r"^以上[。．]?$"),
    re.compile(r"^以上です[。．]?$"),
    re.compile(r"^ご不明点等"),
    re.compile(r"^ご確認の程"),
    re.compile(r"^何卒[、,]"),
    re.compile(r"^ご検討のほど"),
    re.compile(r"^よろしくお願い"),
    re.compile(r"^《会社HP》"),
    re.compile(r"^《フリーランス向け"),
    re.compile(r"^《東京本社》"),
    re.compile(r"^《大阪支社》"),
    re.compile(r"^《福岡支社》"),
    re.compile(r"^株式会社\s+.+(グロース市場|証券コード)"),
    re.compile(r"^本部共通ML"),
    re.compile(r"^共通メール\s*[：:]"),
    re.compile(r"^携帯電話番号\s*[：:]"),
    re.compile(r"^電話番号\s*[：:]"),
    re.compile(r"^TEL\s*[：:]", re.I),
    re.compile(r"^FAX\s*[：:]", re.I),
    re.compile(r"^〒\d{3}"),
    # Outlook 署名の区切り・会社 URL だけの行
    re.compile(r"^_{5,}$"),
    re.compile(r"^https?://\S+$", re.I),
    # 案件ポータル／Salesforce 等の UI 文言（HTML メールに混入）
    re.compile(r"^人材を提案"),
    re.compile(r"^営業中の案件"),
    re.compile(r"^.*案件一覧を見る\s*$"),
    re.compile(r"^マッチングする\s*$"),
    re.compile(r"^詳細を見る\s*$"),
    re.compile(r"^この人材を"),
]

_DIRTY_EMAIL_RE = re.compile(
    r"To unsubscribe|会社HP|フリーランス向け案件紹介|証券コード|本社が移転|"
    r"sales\+unsubscribe|LINE：https://line\.me|"
    r"★\s*注力営業|★\s*配信停止|配信停止希望|■□■□|"
    r"いつもお世話になっております|下記にて案件情報をお送り|"
    r"見合う要員がいらっしゃいましたら|CCに下記メール|"
    r"&nbsp;|携帯電話番号|電話番号\s*[：:]|共通メール\s*[：:]|"
    r"_{10,}\s*\n\s*https?://|"
    r"人材を提案する|営業中の案件一覧|案件一覧を見る",
    re.I,
)

_PERSON_NAME_ONLY_RE = re.compile(
    r"^[一-龥々ぁ-んァ-ヶーA-Za-z]{1,8}[\s　]+[一-龥々ぁ-んァ-ヶーA-Za-z]{1,8}$"
)

_PHONE_VALUE_RE = re.compile(
    r"^(?:電話番号|携帯電話|携帯|TEL|FAX)\s*[：:].+$|"
    r"^0\d{1,4}[-(]?\d{1,4}[-)]?\d{3,4}$",
    re.I,
)

_FIELD_LINE_RE = re.compile(
    r"^(?:■|◆|【)\s*\S+"
)

_SECTION_HEADER_RE = re.compile(
    r"^【\s*(?:案件詳細|案件概要)\s*】$"
)

# Outlook の _____ も含める（ハイフン系の装飾区切りと同じ扱い）
_SEPARATOR_ONLY_RE = re.compile(r"^[ー−–—\-─━_=:＊*]{5,}$")

_STANDALONE_URL_RE = re.compile(r"^https?://\S+$", re.I)


def _is_field_line(line: str) -> bool:
    return bool(_FIELD_LINE_RE.match((line or "").strip()))


def _is_section_header_line(line: str) -> bool:
    text = (line or "").strip()
    if _SECTION_HEADER_RE.match(text):
        return True
    if re.match(r"^[ー−–—-]{3,}\s*案件情報\s*[ー−–—-]{3,}$", text):
        return True
    return False


def _is_content_field_line(line: str) -> bool:
    """■案件名 などの実項目。セクション見出し【案件詳細】は除外。"""
    text = (line or "").strip()
    if not text or _is_section_header_line(text):
        return False
    if _is_standalone_url_line(text) or _is_separator_only_line(text):
        return False
    return _is_field_line(text)


def _is_separator_only_line(line: str) -> bool:
    return bool(_SEPARATOR_ONLY_RE.match((line or "").strip()))


def _is_standalone_url_line(line: str) -> bool:
    return bool(_STANDALONE_URL_RE.match((line or "").strip()))


def _is_portal_ui_line(line: str) -> bool:
    """案件ポータルのボタン／ナビ文言（本文ではない）。"""
    text = (line or "").strip()
    if not text:
        return False
    if re.match(r"^人材を提案", text):
        return True
    if re.match(r"^営業中の案件", text):
        return True
    if re.search(r"案件一覧を見る\s*$", text) and len(text) <= 40:
        return True
    if text in {"マッチングする", "詳細を見る", "候補を見る", "提案する", "この人材を提案する"}:
        return True
    return False


def _is_person_name_only_line(line: str) -> bool:
    text = (line or "").strip()
    if not text or "：" in text or ":" in text:
        return False
    return bool(_PERSON_NAME_ONLY_RE.match(text))


def _is_phone_contact_line(line: str) -> bool:
    return bool(_PHONE_VALUE_RE.match((line or "").strip()))


def _has_substantial_spec(text: str) -> bool:
    """案件項目が実質的に入っているか（見出しだけの空コアを弾く）。"""
    body = (text or "").strip()
    if len(body) < 60:
        return False
    field_count = sum(1 for line in body.split("\n") if _is_content_field_line(line))
    if field_count >= 2:
        return True
    lines = [ln.strip() for ln in body.split("\n") if ln.strip()]
    if len(lines) <= 2 and any(_is_section_header_line(ln) for ln in lines):
        return False
    return len(body) >= 120


class _EmailLike(Protocol):
    body_text: str | None
    body_html: str | None
    body_core_text: str | None
    subject: str | None


def flatten_email_body(*, body_text: str | None, body_html: str | None) -> str:
    """HTML があれば平文化して優先。なければ body_text。HTML 実体もデコードする。"""
    raw = ""
    if body_html and body_html.strip():
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", body_html)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p\s*>", "\n", text)
        text = re.sub(r"(?i)</div\s*>", "\n", text)
        text = re.sub(r"(?i)</tr\s*>", "\n", text)
        text = re.sub(r"(?i)</li\s*>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", "", text)
        raw = text
    elif body_text and body_text.strip():
        raw = body_text
    if not raw.strip():
        return ""
    # &nbsp; や &#160; などを通常空白へ
    raw = html.unescape(raw)
    raw = raw.replace("\xa0", " ").replace("\u200b", "")
    raw = re.sub(r"[ \t]+\n", "\n", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def _normalize_company_key(name: str) -> str:
    text = _CORP_PREFIX_RE.sub("", (name or "").strip())
    text = re.sub(r"[\s　]+", "", text)
    return text.casefold()


def _company_name_variants(name: str) -> set[str]:
    raw = (name or "").strip()
    if not raw:
        return set()
    bare = _CORP_PREFIX_RE.sub("", raw).strip()
    variants = {raw, bare}
    if bare:
        variants.update(
            {
                f"株式会社{bare}",
                f"（株）{bare}",
                f"(株){bare}",
                f"㈱{bare}",
            }
        )
    return {v for v in variants if v}


def _is_company_only_line(line: str, strip_keys: set[str]) -> bool:
    text = (line or "").strip()
    if not text:
        return False
    text = text.strip("-ー−–—･・*|＊＝=　 ")
    if not text:
        return False
    key = _normalize_company_key(text)
    if key and key in strip_keys:
        return True
    for suffix in ("御中", "様", "殿", "ご関係各位", "各位"):
        if text.endswith(suffix):
            trimmed = text[: -len(suffix)].strip()
            if _normalize_company_key(trimmed) in strip_keys:
                return True
    return False


def _is_greeting_only_line(line: str) -> bool:
    text = (line or "").strip()
    if not text:
        return False
    patterns = (
        r"^ご担当者\s*様?$",
        r"^ご担当者様ご関係各位$",
        r"^関係各位$",
        r"^各位$",
        r"^.+様$",
        r"^いつもお世話になっております[。．]?$",
        r"^お世話になっております[。．]?$",
        r"^お疲れ様です[。．]?$",
        r"^下記(の)?案件をご案内.*$",
        r"^下記(の)?案件をご紹介.*$",
        r"^下記にて案件情報.*$",
        r"^下記のとおりご案内.*$",
        r"^弊社案件のご紹介.*$",
        r"^見合う要員(様|が).*$",
        r"^是非[、,]?ご紹介.*$",
        r"^ご返信の際は.*$",
        r"^ご提案の際には.*$",
        r"^※?メールの確認漏れ.*$",
        r"^※?CCに下記.*$",
        r"^＜[^＞]+＞$",
        r"^案件[①-⑨0-9０-９]+■?ご提案時のお願い.*$",
        r"^■?ご提案時のお願い.*$",
        r"^以下の点を記載の上.*$",
    )
    return any(re.match(p, text) for p in patterns)


def _is_sender_intro_line(line: str) -> bool:
    text = (line or "").strip()
    if not text or len(text) > 48:
        return False
    if _SENDER_INTRO_RE.match(text):
        return True
    # 「メディアリンクの大久保です。」「BTM DX推進事業本部でございます。」
    if re.match(r"^.{2,40}(?:です|でございます|と申します)[。．]?$", text):
        return True
    return False


def _is_sales_highlight_line(line: str) -> bool:
    text = (line or "").strip()
    if not text:
        return False
    return bool(_SALES_HIGHLIGHT_RE.match(text))


def _is_leading_preamble_line(line: str, strip_keys: set[str]) -> bool:
    if not line.strip():
        return True
    if strip_keys and _is_company_only_line(line, strip_keys):
        return True
    if _is_greeting_only_line(line):
        return True
    if _is_sender_intro_line(line):
        return True
    if _is_sales_highlight_line(line):
        return True
    if re.match(r"^[・･]\s*(稼働実績|人柄|面談可能|コミュニケーション)", line.strip()):
        return True
    # 単独の数字やゴミ行（HTML 変換の残骸）
    if re.match(r"^\d{1,4}$", line.strip()):
        return True
    return False


def _is_end_marker_line(line: str) -> bool:
    text = (line or "").strip()
    if not text:
        return False
    return any(p.match(text) for p in _CORE_END_PATTERNS)


def _is_signature_block_start(line: str, next_line: str | None = None) -> bool:
    text = (line or "").strip()
    if not text:
        return False
    if _is_end_marker_line(text):
        return True
    if _is_portal_ui_line(text) or _is_phone_contact_line(text):
        return True
    # Outlook 署名: _____ の次が会社 URL、または URL 単独
    if _is_standalone_url_line(text):
        return True
    if _is_separator_only_line(text) and text.startswith("_") and len(text) >= 8:
        nxt = (next_line or "").strip()
        if not nxt or _is_standalone_url_line(nxt) or re.match(r"^株式会社", nxt):
            return True
    # 「吉田　渉」の次が電話番号 → 担当者署名
    if _is_person_name_only_line(text):
        nxt = (next_line or "").strip()
        if _is_phone_contact_line(nxt) or _is_portal_ui_line(nxt):
            return True
    if re.match(r"^株式会社\s*\S+", text) or re.match(r"^[\w一-龥ぁ-んァ-ヶーA-Za-z&.]+株式会社", text):
        nxt = (next_line or "").strip()
        if re.match(
            r"^(代表取締役|取締役|営業|エンジニアリング|TEL|FAX|E-?mail|メール|本部|DX推進|〒|電話)",
            nxt,
            re.I,
        ):
            return True
    if re.match(r"^(代表取締役|E-?mail\s*[：:]|TEL\s*[：:]|FAX\s*[：:]|メール\s*[：:])", text, re.I):
        return False
    return False


def extract_project_spec_block(plain: str) -> str | None:
    """【案件詳細】/■案件名/ーーー案件情報ーーー などから署名直前までのスペック原文を規則抽出。"""
    text = (plain or "").replace("\r\n", "\n").replace("\r", "\n")
    text = html.unescape(text).replace("\xa0", " ")
    if not text.strip():
        return None
    lines = text.split("\n")

    start_idx: int | None = None
    for pattern in _CORE_START_PATTERNS:
        for idx, line in enumerate(lines):
            if pattern.match(line.strip()):
                start_idx = idx
                break
        if start_idx is not None:
            break
    if start_idx is None:
        return None

    # 開始直後の装飾区切り（----------------）は終端にしない。
    # 実項目（■案件名 等）が出たあとの区切り線／署名だけを終端とする。
    end_idx = len(lines)
    saw_field = False
    for idx in range(start_idx + 1, len(lines)):
        line = lines[idx]
        nxt = lines[idx + 1] if idx + 1 < len(lines) else None
        stripped = line.strip()
        if not stripped:
            continue
        if _is_separator_only_line(stripped):
            if saw_field and len(stripped) >= 8:
                look = idx + 1
                while look < len(lines) and not lines[look].strip():
                    look += 1
                if look < len(lines) and _is_content_field_line(lines[look]):
                    continue
                end_idx = idx
                break
            continue
        if _is_content_field_line(stripped) or (
            len(stripped) >= 8
            and not _is_end_marker_line(line)
            and not _is_section_header_line(stripped)
        ):
            saw_field = True
        if _is_end_marker_line(line):
            end_idx = idx
            break
        if _is_signature_block_start(line, nxt):
            end_idx = idx
            break

    block = "\n".join(lines[start_idx:end_idx]).strip()
    block = re.sub(r"[\n\s]*[-─━=:ー−–—]{5,}[\n\s]*$", "", block).strip()
    if not _has_substantial_spec(block):
        return None
    return block or None


def looks_like_full_email(text: str) -> bool:
    """署名・配信停止・冒頭あいさつなどが残っており、まだ全文メールっぽいか。"""
    return bool(_DIRTY_EMAIL_RE.search(text or ""))


def looks_like_empty_core(text: str) -> bool:
    """見出しだけで案件項目が無いコア（再抽出対象）。"""
    return not _has_substantial_spec(text or "")


def sanitize_core_body(text: str, *, strip_names: Sequence[str] | None = None) -> str:
    """社名・あいさつ・署名フッタなどを落とす（LLM/規則抽出の取りこぼし用）。"""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    raw = html.unescape(raw).replace("\xa0", " ").replace("\u200b", "")
    raw = raw.strip()
    if not raw:
        return ""

    strip_keys: set[str] = set()
    for name in strip_names or []:
        for variant in _company_name_variants(name):
            key = _normalize_company_key(variant)
            if key:
                strip_keys.add(key)

    ruled = extract_project_spec_block(raw)
    # 規則抽出が十分な案件ブロックを取れたら、二度目の切断はせず軽く整えるだけ
    if ruled and _has_substantial_spec(ruled) and not looks_like_full_email(ruled):
        cleaned = re.sub(r"[ \t]+\n", "\n", ruled)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        cleaned = re.sub(r"[\n\s]*[-─━=:ー−–—]{5,}[\n\s]*$", "", cleaned).strip()
        return cleaned

    if ruled and len(ruled) >= 40:
        raw = ruled

    lines = raw.split("\n")

    start = 0
    while start < len(lines) and _is_leading_preamble_line(lines[start], strip_keys):
        start += 1

    end = len(lines)
    saw_field = False
    for idx in range(start, len(lines)):
        line = lines[idx]
        nxt = lines[idx + 1] if idx + 1 < len(lines) else None
        stripped = line.strip()
        if not stripped:
            continue
        if _is_separator_only_line(stripped):
            if saw_field and len(stripped) >= 8:
                look = idx + 1
                while look < len(lines) and not lines[look].strip():
                    look += 1
                if look < len(lines) and _is_content_field_line(lines[look]):
                    continue
                end = idx
                break
            continue
        if (
            (_is_content_field_line(stripped) or len(stripped) >= 8)
            and not _is_greeting_only_line(stripped)
            and not _is_sender_intro_line(stripped)
            and not _is_end_marker_line(line)
            and not _is_section_header_line(stripped)
        ):
            saw_field = True
        if _is_end_marker_line(line) or _is_signature_block_start(line, nxt):
            end = idx
            break

    while end > start:
        line = lines[end - 1]
        if not line.strip():
            end -= 1
            continue
        if strip_keys and _is_company_only_line(line, strip_keys):
            end -= 1
            continue
        if _is_sender_intro_line(line) or _is_greeting_only_line(line):
            end -= 1
            continue
        if _is_separator_only_line(line):
            end -= 1
            continue
        if _is_standalone_url_line(line) or _is_end_marker_line(line):
            end -= 1
            continue
        if _is_portal_ui_line(line) or _is_phone_contact_line(line):
            end -= 1
            continue
        if _is_person_name_only_line(line):
            end -= 1
            continue
        break

    kept: list[str] = []
    body_lines = lines[start:end]
    for idx, line in enumerate(body_lines):
        if strip_keys and _is_company_only_line(line, strip_keys):
            prev_blank = idx == 0 or not body_lines[idx - 1].strip()
            next_blank = idx == len(body_lines) - 1 or not body_lines[idx + 1].strip()
            if prev_blank or next_blank:
                continue
        if _is_leading_preamble_line(line, strip_keys) and not any(
            p.match(line.strip()) for p in _CORE_START_PATTERNS
        ):
            if _is_greeting_only_line(line) or _is_sender_intro_line(line):
                continue
        kept.append(line.rstrip())

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    cleaned = re.sub(r"[\n\s]*[-─━=:ー−–—]{5,}[\n\s]*$", "", cleaned).strip()
    return cleaned


def _parse_cached_core(raw: str | None) -> tuple[str | None, str]:
    text = (raw or "").strip()
    if not text:
        return None, ""
    match = re.match(r"^\[\[core:(v\d+)\]\]\n?", text)
    if not match:
        return None, text
    version = match.group(1)
    body = text[match.end() :].lstrip("\n")
    return version, body


def _store_cached_core(body: str) -> str:
    return f"{_CACHE_PREFIX}{body.strip()}"


def _extract_core_via_openai(
    *,
    plain_body: str,
    subject: str | None,
    openai_api_key: str,
    openai_model: str,
) -> str | None:
    if not openai_api_key.strip() or not plain_body.strip():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key)
        response = client.chat.completions.create(
            model=openai_model or "gpt-4o-mini",
            temperature=0,
            messages=[
                {"role": "system", "content": _CORE_EXTRACT_SYSTEM},
                {
                    "role": "user",
                    "content": _CORE_EXTRACT_USER.format(
                        subject=(subject or "").strip() or "（件名なし）",
                        body=plain_body[:24000],
                    ),
                },
            ],
        )
        content = (response.choices[0].message.content or "").strip()
        return content or None
    except Exception:  # noqa: BLE001
        logger.exception("Failed to extract email core body via OpenAI")
        return None


def collect_core_strip_names(
    session: Session,
    email: _EmailLike,
    *,
    extra_names: Sequence[str] | None = None,
) -> list[str]:
    """コア原文から落とすべき社名（送信元会社 + 追加）。"""
    names: list[str] = []
    seen: set[str] = set()

    def _add(raw: str | None) -> None:
        text = (raw or "").strip()
        if not text:
            return
        key = _normalize_company_key(text)
        if not key or key in seen:
            return
        seen.add(key)
        names.append(text)

    company_id = getattr(email, "source_company_id", None)
    if company_id is not None:
        try:
            from app.models import Company

            company = session.get(Company, company_id)
            if company is not None:
                _add(getattr(company, "name", None))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to resolve source company for core strip names")

    for name in extra_names or []:
        _add(name)
    return names


def _choose_core_candidate(
    *,
    plain: str,
    llm_text: str | None,
    strip_names: Sequence[str] | None,
) -> str:
    """規則抽出を優先し、ダメなときだけ LLM。どちらも汚ければ再サニタイズ。"""
    ruled = extract_project_spec_block(plain)
    ruled_clean = sanitize_core_body(ruled, strip_names=strip_names) if ruled else ""
    llm_clean = sanitize_core_body(llm_text or "", strip_names=strip_names) if llm_text else ""

    def _ok(text: str) -> bool:
        return bool(text) and not looks_like_full_email(text) and not looks_like_empty_core(text)

    if ruled_clean and len(ruled_clean) >= 80 and _ok(ruled_clean):
        return ruled_clean

    if llm_clean and _ok(llm_clean):
        if ruled_clean and _ok(ruled_clean) and len(ruled_clean) > len(llm_clean) * 1.5:
            return ruled_clean
        return llm_clean

    if ruled_clean and not looks_like_empty_core(ruled_clean):
        return ruled_clean
    if llm_clean and not looks_like_empty_core(llm_clean):
        return llm_clean

    fallback = sanitize_core_body(plain, strip_names=strip_names)
    if fallback and not looks_like_empty_core(fallback):
        return fallback
    # 最後の手段: 規則が空でも LLM 原文をサニタイズ前から使う
    if llm_text and len(llm_text.strip()) >= 60:
        return sanitize_core_body(llm_text, strip_names=strip_names) or llm_text.strip()
    return fallback


def ensure_email_core_body(
    session: Session,
    email: _EmailLike,
    *,
    openai_api_key: str,
    openai_model: str,
    allow_llm: bool = True,
    strip_names: Sequence[str] | None = None,
) -> str:
    """キャッシュ済みコア原文を返す。無ければ規則＋LLM で抽出し保存。"""
    version, cached_body = _parse_cached_core(getattr(email, "body_core_text", None))
    cache_fresh = version == _CORE_CACHE_VERSION and bool(cached_body.strip())

    if (
        cache_fresh
        and not looks_like_full_email(cached_body)
        and not looks_like_empty_core(cached_body)
    ):
        cleaned = sanitize_core_body(cached_body, strip_names=strip_names)
        if looks_like_empty_core(cleaned):
            # 空コアはキャッシュ破棄して再抽出へ
            pass
        else:
            if cleaned != cached_body.strip():
                email.body_core_text = _store_cached_core(cleaned)
                session.add(email)
                session.flush()
            return cleaned

    plain = flatten_email_body(body_text=email.body_text, body_html=email.body_html)
    if not plain:
        return ""

    if not allow_llm:
        cleaned = _choose_core_candidate(
            plain=plain, llm_text=cached_body or None, strip_names=strip_names
        )
        if cleaned and (
            cleaned != cached_body.strip()
            or version != _CORE_CACHE_VERSION
            or looks_like_full_email(cached_body)
            or looks_like_empty_core(cached_body)
        ):
            email.body_core_text = _store_cached_core(cleaned)
            session.add(email)
            session.flush()
        return cleaned

    llm_text = _extract_core_via_openai(
        plain_body=plain,
        subject=email.subject,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
    )
    cleaned = _choose_core_candidate(plain=plain, llm_text=llm_text, strip_names=strip_names)
    if cleaned:
        email.body_core_text = _store_cached_core(cleaned)
        session.add(email)
        session.flush()
    return cleaned
