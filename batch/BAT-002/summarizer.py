"""BAT-002: メール本文から人材/案件の構造化 JSON を抽出する。

優先順:
  1. GEMINI_API_KEY → Gemini generateContent (JSON / 20通まとめ可)
  2. CURSOR_API_KEY → Cursor SDK
  3. OPENAI_API_KEY → OpenAI Chat Completions (JSON mode)
  4. ANTHROPIC_API_KEY → Claude Messages API
  5. いずれも無い / AI 失敗 → 【項目】：値 の定型パース + ヒューリスティック
"""

from __future__ import annotations

import json
import logging
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable
from typing import Any, Literal, Protocol

EmailType = Literal["talent", "project"]


class AiSettings(Protocol):
    cursor_api_key: str
    openai_api_key: str
    openai_model: str
    anthropic_api_key: str
    anthropic_model: str
    gemini_api_key: str
    gemini_model: str
    gemini_batch_size: int
    gemini_batch_parallel: int
    gemini_batch_wave_interval_seconds: int
    gemini_input_tpm: int
    ai_concurrency: int


_ISOLATION_RULES = """\
【厳守事項】
・各メールの情報は、そのメール内に書かれている内容のみを根拠にしてください。
・他のメールの単価・勤務地・スキル等の数値や固有名詞を、絶対に別のメールの結果に混ぜないでください。
・出力するJSON配列の各要素には、必ず元の email id を含めてください。
"""

_TALENT_SCHEMA_HINT = """\
あなたは SES 人材紹介メールの抽出器です。
企業ごとにメール書式が違うため、【項目】定型に頼らず文脈から推論してください。
次の JSON オブジェクトだけを返してください。Markdown や説明文は禁止です。

""" + _ISOLATION_RULES + """
必須キー:
- display_name (string): 要員の呼称・イニシャルのみ（雇用形態は含めない）
- skills (string array): 技術名または工程名のみ（「Java開発の経験5年程度」→ "Java"。「基本設計以降」は 基本設計,詳細設計,製造,単体試験,結合試験,システム試験,リリース に分ける。結合試験とシステム試験は分けて書く。年数や「以降」の説明文は入れない。「実務経験：N年」は experience_years へ）
- summary (string|null): 【営業コメント】【自己PR】【備考】など該当欄の原文そのまま。要約禁止。該当欄が無ければ空文字。メール全文は入れない
- source_company_name (string|null): 配信元（紹介）会社名。署名や From 表示名から取る
- contact_name (string|null): 送信担当者の氏名。署名の「担当：」や From 表示名から取る

任意キー:
- affiliation (雇用形態。例: プロパー(コアパートナー所属) / フリーランス / 一社専属),
  age (int|null), gender (string|null: 男性 / 女性。不明は null),
  experience_years (int|null),
  desired_rate (int|null, 万円/月・レンジなら下限), available_from, work_style, nearest_station,
  is_foreign_national (bool|null: 外国籍なら true、日本国籍なら false、不明は null),
  commerce_flow (string|null: 商流。例: プロパー / 一社先 / 二社先。affiliation から分かる場合はそちらを優先してよい)

表記ゆれの例:
- 【名　前】ST　プロパー(コアパートナー所属) → display_name="ST", affiliation="プロパー(コアパートナー所属)"
- 【性　別】男性 → gender="男性"
- 【稼動日】8月～ / 【稼働】即日 → available_from に入れる（稼動と稼働は同義）
- 【単　金】65～70万円 → desired_rate=65
- 【備　考】詳細設計以降を自走できます → 工程は skills へ。summary はその備考原文
- 署名「担当：中村」→ contact_name="中村"

出力例:
{"display_name":"ST","affiliation":"プロパー(コアパートナー所属)","age":25,"gender":"男性","experience_years":4,"desired_rate":65,"available_from":"8月～","work_style":null,"nearest_station":"北綾瀬駅","skills":["Java","Spring Boot"],"source_company_name":"株式会社アストロ","contact_name":"中村","summary":"詳細設計以降の工程を自走できます。"}
"""

_PROJECT_SCHEMA_HINT = """\
あなたは SES 案件紹介メールの抽出器です。
次の JSON オブジェクトだけを返してください。Markdown や説明文は禁止です。

""" + _ISOLATION_RULES + """
必須キー:
- title (string): 案件名（【案件名】があればそれを使う）
- required_skills (string array): 必須スキル。技術名または工程名のみ（「Java開発の経験5年程度」→ "Java"。「基本設計以降のご経験」→ 基本設計,詳細設計,製造,単体試験,結合試験,システム試験,リリース。結合試験とシステム試験は分けて書く。年数や説明文は入れない）
- preferred_skills (string array): 尚可スキル・歓迎スキル（【尚可】【尚可スキル】【歓迎スキル】内のみ。技術名または工程名。無ければ空配列。稼働開始日・備考・契約形態・商流・署名・URL・会社名・TEL/FAX は入れない）
- summary (string): 業務内容の原文抜粋。【業務内容】【作業内容】【案件概要】等の項目本文を要約せず近い文言で抜く（営業文・署名は含めない）
- source_company_name (string|null): 配信元会社名。署名や From 表示名から取る
- contact_name (string|null): 送信担当者の氏名。署名の「担当：」や From 表示名から取る

任意キー:
- project_code, rate_min (int|null), rate_max (int|null),
  location, work_style, working_hours, start_date, settlement_range,
  interview_count (int|null: 面談回数。例: 1回→1、2回→2。不明は null),
  headcount (int|null: 募集人数。例: 1名→1。不明は null),
  foreign_nationality_ng (bool|null: 外国籍不可・日本人のみなら true。可・不問なら false。メールに記載がなければ null),
  commerce_flow_limit (string|null: 商流制限。例: エンド直 / 貴社まで / 一社先まで / 二社先まで / 制限なし)

working_hours は勤務時間・就業時間（例: 10:00〜19:00 / フレックス）。
settlement_range は精算幅（例: 140〜180h / 140h-180h）。

出力例:
{"title":"飲料メーカー向け保守業務","project_code":null,"required_skills":["Java","PostgreSQL"],"preferred_skills":["AWS"],"rate_min":null,"rate_max":null,"location":"お台場","work_style":"基本フルリモート（月1回程度出社）","working_hours":"10:00〜19:00","start_date":"8月～長期","settlement_range":"140〜180h","interview_count":2,"headcount":1,"foreign_nationality_ng":true,"commerce_flow_limit":"一社先まで","source_company_name":"株式会社サンプル","contact_name":"山田","summary":"・飲料メーカー向け基幹システムの保守対応\\n・障害調査と軽微な改修"}
"""

_GEMINI_BATCH_FIELD_SCHEMA_TALENT = """\
【各要素の JSON キー（人材メール）】
必須:
- mail_id (string): 入力 <email id="..."> の id 属性値
- display_name (string): 要員の呼称・イニシャルのみ（雇用形態は含めない）
- skills (string array): 技術名または工程名（年数や「以降」の説明文は入れない。工程は細分化した名前で出す）
- summary (string): 【営業コメント】【自己PR】【備考】など該当欄の原文そのまま（要約禁止）。該当なしは「要確認」。メール全文は入れない

任意（記載なしは「要確認」。数値・bool はメールに明記がある場合のみ）:
- affiliation, age, gender, experience_years, desired_rate, available_from,
  work_style, nearest_station, is_foreign_national, commerce_flow,
  source_company_name, contact_name
"""

_GEMINI_BATCH_FIELD_SCHEMA_PROJECT = """\
【各要素の JSON キー（案件メール）】
必須:
- mail_id (string): 入力 <email id="..."> の id 属性値
- title (string): 案件名
- required_skills (string array): 必須スキル（技術名または工程名。年数・「以降」の説明は入れず工程は細分化）
- preferred_skills (string array): 【尚可】【尚可スキル】【歓迎スキル】内の技術名または工程名のみ（無ければ空配列。備考・署名・URL・会社情報は入れない）
- summary (string): 業務内容の原文抜粋（要約禁止）。該当なしは「要確認」

任意:
- project_code (string|null): 案件番号。メールに無ければ null。「要確認」は禁止
- その他（記載なしは「要確認」。数値・bool はメールに明記がある場合のみ）:
  rate_min, rate_max, location, work_style, working_hours,
  start_date, settlement_range, interview_count, headcount,
  foreign_nationality_ng, commerce_flow_limit, source_company_name, contact_name
"""

_GEMINI_BATCH_USER_PROMPT = """\
あなたは優秀なSES営業アシスタントです。
<emails_list> タグ内に囲まれた全 {count} 件のメール（<email>）を個別に解析し、指定された JSON 配列フォーマットで出力してください。

【最重要制約事項（厳守）】
1. 完全な相互独立性（情報混同の禁止）:
   各 <email> タグ内のデータは、他の <email> タグの情報から完全に独立した別個の{entity_label}として処理してください。あるメールに書かれている単価やスキルなどの情報を、別のメールの出力結果に混ぜたり補完したりすることは絶対に禁止です。

2. 配列要素数とIDの完全一致:
   - 入力された <email> タグの個数（{count}件）と、出力される JSON 配列 items の要素数（{count}件）は絶対に 1:1 で一致させてください。
   - 各 JSON オブジェクトの "mail_id" には、解析対象の <email> タグに付与されている id 属性の値を、一字一句そのまま設定してください。
   - 次の mail_id をすべて返せ。欠け・余分・別IDへの置き換えは禁止。件数はちょうど {count} 件:
{mail_id_list}

3. 情報が見つからない場合:
   該当する <email> タグ内に記載がない項目については、他のメールの情報から類推せず、必ず「要確認」と出力してください。
   ただし project_code（案件番号）だけは例外で、記載がなければ null。文字列「要確認」は禁止。

【出力 JSON 形式】
{{"items": [ {{ "mail_id": "<email id>", ... }} ]}}
Markdown や説明文は禁止。上記 JSON オブジェクトのみ返してください。

{field_schema}

【解析対象データ】
{combined_text}
"""

_GEMINI_BATCH_SYSTEM = (
    "You extract structured SES data from Japanese emails in batch. "
    'Each <email> is independent. Reply with a JSON object {"items":[...]} only. '
    "Every item must include mail_id matching the input <email id> attribute. "
    "The items array length must equal the number of input emails, and every listed mail_id must appear. "
    "For projects, summary must be a verbatim excerpt of work scope from the email, not a paraphrase. "
    "For talents, summary must be a verbatim excerpt of 営業コメント / 自己PR / 備考, never the full email."
)

_TALENT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "mail_id": {"type": "STRING"},
        "display_name": {"type": "STRING"},
        "affiliation": {"type": "STRING"},
        "age": {"type": "INTEGER"},
        "gender": {"type": "STRING"},
        "experience_years": {"type": "INTEGER"},
        "desired_rate": {"type": "INTEGER"},
        "available_from": {"type": "STRING"},
        "work_style": {"type": "STRING"},
        "nearest_station": {"type": "STRING"},
        "skills": {"type": "ARRAY", "items": {"type": "STRING"}},
        "source_company_name": {"type": "STRING"},
        "contact_name": {"type": "STRING"},
        "is_foreign_national": {"type": "BOOLEAN"},
        "commerce_flow": {"type": "STRING"},
        "summary": {"type": "STRING"},
    },
    "required": ["mail_id", "display_name", "skills", "summary"],
}

_PROJECT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "mail_id": {"type": "STRING"},
        "title": {"type": "STRING"},
        "project_code": {"type": "STRING"},
        "required_skills": {"type": "ARRAY", "items": {"type": "STRING"}},
        "preferred_skills": {"type": "ARRAY", "items": {"type": "STRING"}},
        "rate_min": {"type": "INTEGER"},
        "rate_max": {"type": "INTEGER"},
        "location": {"type": "STRING"},
        "work_style": {"type": "STRING"},
        "working_hours": {"type": "STRING"},
        "start_date": {"type": "STRING"},
        "settlement_range": {"type": "STRING"},
        "interview_count": {"type": "INTEGER"},
        "headcount": {"type": "INTEGER"},
        "foreign_nationality_ng": {"type": "BOOLEAN"},
        "commerce_flow_limit": {"type": "STRING"},
        "source_company_name": {"type": "STRING"},
        "contact_name": {"type": "STRING"},
        "summary": {"type": "STRING"},
    },
    "required": ["mail_id", "title", "required_skills", "summary"],
}

_BATCH_ITEMS_SCHEMA: dict[str, dict[str, Any]] = {
    "talent": {
        "type": "OBJECT",
        "properties": {"items": {"type": "ARRAY", "items": _TALENT_ITEM_SCHEMA}},
        "required": ["items"],
    },
    "project": {
        "type": "OBJECT",
        "properties": {"items": {"type": "ARRAY", "items": _PROJECT_ITEM_SCHEMA}},
        "required": ["items"],
    },
}

_SINGLE_RESPONSE_SCHEMA: dict[str, dict[str, Any]] = {
    "talent": {
        "type": "OBJECT",
        "properties": {
            k: v for k, v in _TALENT_ITEM_SCHEMA["properties"].items() if k != "mail_id"
        },
        "required": [k for k in _TALENT_ITEM_SCHEMA["required"] if k != "mail_id"],
    },
    "project": {
        "type": "OBJECT",
        "properties": {
            k: v for k, v in _PROJECT_ITEM_SCHEMA["properties"].items() if k != "mail_id"
        },
        "required": [k for k in _PROJECT_ITEM_SCHEMA["required"] if k != "mail_id"],
    },
}

_BRACKET_FIELD_RE = re.compile(
    r"【\s*(?P<key>[^】]+?)\s*】\s*[:：]?\s*(?P<value>[^\n【]*)",
    re.MULTILINE,
)


@dataclass
class ExtractionResult:
    """構造化抽出の結果。"""

    email_type: EmailType
    data: dict[str, Any]
    needs_review: bool
    provider: str
    raw_summary: str = ""
    error_code: str | None = None


@dataclass(frozen=True)
class EmailExtractRequest:
    """バッチ抽出の1通分入力。"""

    item_id: str
    subject: str
    body: str
    from_header: str | None = None


_BATCH_BODY_CHARS = 3000


def _xml_escape(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_batch_emails_xml(requests: list[EmailExtractRequest]) -> str:
    """複数メールを <email id> タグで区切った1本のテキストにする。"""
    lines = ["<emails_list>"]
    for item in requests:
        mail_id = _xml_escape(str(item.item_id))
        body = _strip_html_if_needed((item.body or "").strip())[:_BATCH_BODY_CHARS]
        lines.append(f'  <email id="{mail_id}">')
        if item.from_header:
            lines.append(f"    <from>{_xml_escape(item.from_header)}</from>")
        lines.append(f"    <subject>{_xml_escape(item.subject or '')}</subject>")
        lines.append(f"    <body>{_xml_escape(body)}</body>")
        lines.append("  </email>")
    lines.append("</emails_list>")
    return "\n".join(lines)


def _build_gemini_batch_user_prompt(
    email_type: EmailType,
    requests: list[EmailExtractRequest],
) -> str:
    """Gemini 20通バッチ用ユーザープロンプト。"""
    count = len(requests)
    entity_label = "人材" if email_type == "talent" else "案件"
    field_schema = (
        _GEMINI_BATCH_FIELD_SCHEMA_TALENT
        if email_type == "talent"
        else _GEMINI_BATCH_FIELD_SCHEMA_PROJECT
    )
    combined_text = _build_batch_emails_xml(requests)
    mail_id_list = "\n".join(f"   - {item.item_id}" for item in requests)
    return _GEMINI_BATCH_USER_PROMPT.format(
        count=count,
        entity_label=entity_label,
        field_schema=field_schema,
        combined_text=combined_text,
        mail_id_list=mail_id_list,
    )


def _parse_json_value(text: str) -> Any | None:
    cleaned = _strip_json_fence(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"[\[{][\s\S]*[\]}]", cleaned)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None


def _extract_batch_items(parsed: Any) -> list[dict[str, Any]] | None:
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        items = parsed.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return None


def _batch_item_mail_id(raw: dict[str, Any]) -> Any:
    if raw.get("mail_id") is not None:
        return raw.get("mail_id")
    return raw.get("id")


def _strip_json_fence(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def _parse_json_object(text: str) -> dict[str, Any] | None:
    cleaned = _strip_json_fence(text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return None
        try:
            payload = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        parts = re.split(r"[,、/｜|\n・]+", value)
        return [part.strip(" ・\t") for part in parts if part.strip(" ・\t")]
    return []


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        match = re.search(r"\d+", value.replace(",", ""))
        if not match:
            return None
        value = match.group(0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_gender(value: Any) -> str | None:
    """性別を 男性 / 女性 に正規化する。不明は null。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in ("男性", "女性"):
        return text
    lowered = re.sub(r"\s+", "", text.lower())
    if "女" in text or "female" in lowered:
        return "女性"
    if "男" in text or ("male" in lowered and "female" not in lowered):
        return "男性"
    return None


def _normalize_key(key: str) -> str:
    """【単　金】のような表記ゆれを吸収する。"""
    return re.sub(r"[\s　]+", "", key)


def _bracket_map(text: str) -> dict[str, str]:
    """【項目名】：値 を辞書化する（キーは空白除去後も参照できる）。"""
    result: dict[str, str] = {}
    for match in _BRACKET_FIELD_RE.finditer(text):
        key = match.group("key").strip()
        value = match.group("value").strip()
        if key and value:
            result[key] = value
            result[_normalize_key(key)] = value
    return result


def _pick_bracket(fields: dict[str, str], *aliases: str) -> str | None:
    """別名に一致する【項目】値を返す。完全一致を優先し、次に部分一致。"""
    normalized_map = {_normalize_key(key): value for key, value in fields.items()}
    for alias in aliases:
        exact = _normalize_key(alias)
        if exact in normalized_map and normalized_map[exact]:
            return normalized_map[exact]
    for alias in aliases:
        needle = _normalize_key(alias)
        if not needle:
            continue
        for key, value in normalized_map.items():
            if needle in key and value:
                return value
    return None


def _split_name_and_affiliation(raw: str) -> tuple[str, str | None]:
    """『ST　プロパー(コアパートナー所属)』形式を名前と雇用形態に分ける。"""
    text = raw.strip()
    if not text:
        return text, None

    paren = re.match(
        r"^(.+?)[\s　]+((?:プロパー|フリーランス|一社専属|個人事業主|正社員|契約社員|BP)[^\n]*)$",
        text,
    )
    if paren:
        return paren.group(1).strip(), paren.group(2).strip()

    with_paren = re.match(
        r"^(.+?)[\s　]*[（(]([^）)]*所属[^）)]*)[）)]\s*$",
        text,
    )
    if with_paren:
        return with_paren.group(1).strip(), with_paren.group(2).strip()

    return text, None


def _extract_sender_company(body: str, from_header: str | None = None) -> str | None:
    """From 表示名または署名末尾から配信会社名を推定する。"""
    if from_header:
        match = re.match(r'^"?([^"<]+)"?\s*<', from_header.strip())
        if match:
            name = match.group(1).strip().strip("'")
            if name and not re.fullmatch(r"[^\s@]+@[^\s@]+", name):
                # 表示名が人名っぽい場合は会社名にしない
                if not re.search(r"(株式会社|有限会社|合同会社|Inc|Corp|Ltd)", name, re.IGNORECASE):
                    pass
                else:
                    return name[:255]

    tail = (body or "")[-2000:]
    matches = list(
        re.finditer(r"((?:株式会社|有限会社|合同会社)[^\s　\n＝]{1,40})", tail)
    )
    for match in reversed(matches):
        # 「株式会社Kanana　様」は宛先なのでスキップ
        after = tail[match.end() : match.end() + 3]
        if after.lstrip("　 ").startswith("様"):
            continue
        return match.group(1).strip("　 。．")[:255]
    return None


def _extract_contact_name(body: str, from_header: str | None = None) -> str | None:
    """署名の担当行、または From 表示名から担当者名を推定する。"""
    text = body or ""
    for pattern in (
        r"(?:担当|営業担当|連絡先)\s*[:：]\s*([^\s　\n／/]{1,40})",
        r"担当者\s*[:：]\s*([^\s　\n／/]{1,40})",
    ):
        match = re.search(pattern, text[-2500:])
        if match:
            name = match.group(1).strip("　 。．様")
            if name and not re.search(r"(株式会社|有限会社|合同会社)", name):
                return name[:128]

    if from_header:
        match = re.match(r'^"?([^"<]+)"?\s*<', from_header.strip())
        if match:
            name = match.group(1).strip().strip("'")
            if name and not re.fullmatch(r"[^\s@]+@[^\s@]+", name):
                if not re.search(r"(株式会社|有限会社|合同会社|Inc|Corp|Ltd)", name, re.IGNORECASE):
                    return name[:128]
    return None


def _extract_contact_email(from_header: str | None = None, from_address: str | None = None) -> str | None:
    raw = from_header or from_address or ""
    match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", raw, re.IGNORECASE)
    return match.group(0).lower() if match else None


def _parse_rate_man_yen(raw: str | None) -> int | None:
    """「65～70万円」などから代表単価（下限）を万円単位で取る。"""
    if not raw:
        return None
    nums = [int(n) for n in re.findall(r"\d+", raw.replace(",", ""))]
    if not nums:
        return None
    # 65～70万円 → 65。千円表記(650000)は万円に換算
    value = nums[0]
    if value >= 10000:
        value = value // 10000
    return value


# 【尚可】の直後が ■稼働開始日： のような別項目のとき、ブロックをそこで切る
_LABELED_BLOCK_STOP = (
    r"\n【"
    r"|\n[ー－━═＝\-]{3,}"
    r"|\n[■▼]\s*[^\n]{0,40}[：:]"
    r"|\n以上[、,．。\s　]"
    r"|\Z"
)
_SALES_COMMENT_LABELS: tuple[str, ...] = (
    "営業コメント",
    "推薦コメント",
    "自己PR",
    "自己ＰＲ",
    "アピールポイント",
    "アピール",
    "人物像",
    "PR",
    "ＰＲ",
    "備考",
    "特記事項",
    "補足",
)
_SKILL_SECTION_CUT_RE = re.compile(
    r"(?:"
    r"\n【"
    r"|\n[ー－━═＝\-]{3,}"
    r"|[■▼]\s*[^\n]{0,40}[：:]"
    r"|(?:^|\n)(?:株式会社|有限会社|合同会社)"
    r"|(?:^|\n)(?:TEL|FAX)\s*[：:]"
    r"|https?://"
    r")",
    re.IGNORECASE | re.MULTILINE,
)
_JUNK_SKILL_RE = re.compile(
    r"(?:"
    r"https?:|\bwww\.|\.(?:co\.)?jp$"
    r"|株式会社|有限会社|合同会社|証券コード"
    r"|事業部|営業グループ|案件紹介サイト|フリーランス向け"
    r"|\b(?:TEL|FAX)\b"
    r"|\d{2,4}-\d{2,4}-\d{3,4}"
    r"|^(?:稼働開始日|開始日|参画日|備考|契約形態|商流|商談回数|面談回数)"
    r"|^[■▼◆].*[：:]\s*$"
    r")",
    re.IGNORECASE,
)


def _flexible_label_re(label: str) -> str:
    """【備　考】のようにラベル内空白を許す。"""
    chars = [re.escape(ch) for ch in label if not ch.isspace()]
    return r"[\s　]*".join(chars) if chars else re.escape(label)


def _extract_labeled_block(text: str, labels: tuple[str, ...]) -> str | None:
    """【ラベル】以降の複数行ブロックを抜き出す。"""
    for label in labels:
        pattern = re.compile(
            rf"【\s*{_flexible_label_re(label)}[^】]*】\s*[:：]?\s*(?P<body>.*?)(?={_LABELED_BLOCK_STOP})",
            re.DOTALL,
        )
        match = pattern.search(text)
        if not match:
            continue
        body = match.group("body").strip()
        if body:
            return body[:2000]
    return None


def _trim_skill_block(body: str) -> str:
    """スキル箇条書きの後ろに付いた別項目・署名を落とす。"""
    match = _SKILL_SECTION_CUT_RE.search(body)
    if match and match.start() > 0:
        return body[: match.start()].strip()
    return body.strip()


def _is_plausible_skill(text: str) -> bool:
    cleaned = text.strip(" ・\t　")
    if not cleaned or cleaned == "要確認":
        return False
    if len(cleaned) > 40:
        return False
    if _JUNK_SKILL_RE.search(cleaned):
        return False
    return True


def _filter_skill_items(skills: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for skill in skills:
        cleaned = skill.strip(" ・\t　")
        if not _is_plausible_skill(cleaned) or cleaned in seen:
            continue
        seen.add(cleaned)
        unique.append(cleaned)
    return unique[:40]


def _parse_skill_lines(body: str) -> list[str]:
    """箇条書き・区切り文字からスキル名リストを作る。"""
    skills: list[str] = []
    for raw_line in _trim_skill_block(body).splitlines():
        line = re.sub(r"^[・●◆▪\-]\s*", "", raw_line.strip())
        if not line:
            continue
        skills.extend(_as_str_list(line))
    from app.skill_terms import expand_skill_items

    return _filter_skill_items(expand_skill_items(skills))


def _extract_skills_block(text: str) -> list[str]:
    """必要スキル / 主な環境ブロックから技術名を拾う。"""
    body = _extract_labeled_block(
        text,
        ("必要スキル", "必須スキル", "主な環境", "技術要素", "スキル"),
    )
    if not body:
        return []
    return _parse_skill_lines(body)


def _extract_preferred_skills_block(text: str) -> list[str]:
    """尚可スキル / 歓迎スキルブロックから技術名を拾う。"""
    body = _extract_labeled_block(
        text,
        ("尚可スキル", "歓迎スキル", "尚可", "あると尚可", "プラススキル", "歓迎"),
    )
    if not body:
        return []
    return _parse_skill_lines(body)


def _extract_work_content_block(text: str) -> str | None:
    """業務内容ブロックをメール原文に近い形で抜粋する。"""
    return _extract_labeled_block(
        text,
        ("業務内容", "作業内容", "案件概要", "案件内容", "詳細", "内容", "概要"),
    )


def _extract_sales_comment_block(text: str) -> str | None:
    """営業コメント／自己PR／備考をメール原文のまま抜粋する。"""
    chunks: list[str] = []
    seen: set[str] = set()
    for label in _SALES_COMMENT_LABELS:
        body = _extract_labeled_block(text, (label,))
        if not body:
            pattern = re.compile(
                rf"(?:^|\n)[■▼◆●]?\s*{_flexible_label_re(label)}\s*[：:]+\s*(?P<body>.*?)(?={_LABELED_BLOCK_STOP})",
                re.DOTALL,
            )
            match = pattern.search(text)
            body = match.group("body").strip()[:2000] if match else None
        if body and body not in seen:
            seen.add(body)
            chunks.append(body)
    if not chunks:
        return None
    return "\n\n".join(chunks)[:2000]


def _rule_extract_project(
    subject: str,
    body: str,
    *,
    from_header: str | None = None,
) -> dict[str, Any]:
    fields = _bracket_map(f"{subject}\n{body}")
    title = _pick_bracket(fields, "案件名", "案件タイトル") or subject.strip()[:255]
    location = _pick_bracket(fields, "作業場所", "勤務地", "場所")
    work_style = _pick_bracket(fields, "作業形態", "勤務形態", "リモート")
    working_hours = _pick_bracket(fields, "勤務時間", "就業時間", "稼働時間")
    settlement_range = _pick_bracket(fields, "精算幅", "精算", "時間幅", "清算幅")
    start_date = _pick_bracket(fields, "作業期間", "開始", "期間")
    rate_raw = _pick_bracket(fields, "単金", "単価", "金額")
    rate_min = None
    rate_max = None
    if rate_raw:
        nums = [int(n) for n in re.findall(r"\d+", rate_raw.replace(",", ""))]
        # 万円換算（650000 → 65）
        nums = [n // 10000 if n >= 10000 else n for n in nums]
        if len(nums) >= 2:
            rate_min, rate_max = nums[0], nums[1]
        elif len(nums) == 1:
            rate_min = rate_max = nums[0]

    skills = _extract_skills_block(body) or _as_str_list(
        _pick_bracket(fields, "必要スキル", "必須スキル", "主な環境")
    )
    preferred_skills = _extract_preferred_skills_block(body) or _as_str_list(
        _pick_bracket(fields, "尚可スキル", "歓迎スキル", "尚可")
    )
    source_company_name = _extract_sender_company(body, from_header)
    contact_name = _extract_contact_name(body, from_header)
    from app.constraint_rules import extract_project_constraint_fields

    foreign_nationality_ng, commerce_flow_limit = extract_project_constraint_fields(fields, body)
    interview_count = _as_optional_int(
        _pick_bracket(fields, "面談回数", "面接回数", "面談数", "面接数")
    )
    headcount = _as_optional_int(
        _pick_bracket(fields, "人数", "募集人数", "必要人数", "採用人数")
    )
    work_content = _extract_work_content_block(body) or _pick_bracket(
        fields,
        "業務内容",
        "案件概要",
        "概要",
        "作業内容",
        "案件内容",
        "詳細",
        "内容",
    )
    if work_content:
        summary = work_content
    else:
        # 業務内容欄が無い場合の最低限フォールバック
        summary_parts = [p for p in (title, location, work_style, start_date) if p]
        if skills:
            summary_parts.append("スキル: " + " / ".join(skills[:6]))
        summary = "。".join(summary_parts) if summary_parts else subject.strip()

    return {
        "title": title,
        "project_code": None,
        "required_skills": skills,
        "preferred_skills": preferred_skills,
        "rate_min": rate_min,
        "rate_max": rate_max,
        "location": location,
        "work_style": work_style,
        "working_hours": working_hours,
        "start_date": start_date,
        "settlement_range": settlement_range,
        "interview_count": interview_count,
        "headcount": headcount,
        "foreign_nationality_ng": foreign_nationality_ng,
        "commerce_flow_limit": commerce_flow_limit,
        "source_company_name": source_company_name,
        "contact_name": contact_name,
        "summary": summary[:2000],
    }


def _rule_extract_talent(
    subject: str,
    body: str,
    *,
    from_header: str | None = None,
) -> dict[str, Any]:
    fields = _bracket_map(f"{subject}\n{body}")
    name_raw = (
        _pick_bracket(fields, "名前", "氏名", "お名前", "要員名", "候補者")
        or subject.strip()[:128]
    )
    display_name, affiliation_from_name = _split_name_and_affiliation(name_raw)
    skills = _extract_skills_block(body) or _as_str_list(
        _pick_bracket(fields, "スキル", "技術", "言語")
    )
    # 「実務経験：4.5年」はスキルではなく経験年数へ
    cleaned_skills: list[str] = []
    experience_years = _as_optional_int(_pick_bracket(fields, "経験年数", "経験"))
    for skill in skills:
        exp_match = re.search(r"実務経験\s*[:：]?\s*([\d.]+)\s*年", skill)
        if exp_match and experience_years is None:
            try:
                experience_years = int(float(exp_match.group(1)))
            except ValueError:
                pass
            continue
        if skill.startswith("実務経験"):
            continue
        cleaned_skills.append(skill.strip())
    skills = [
        s for s in cleaned_skills
        if s and not re.match(r"(?:株式会社|有限会社|合同会社)", s)
    ]

    rate_raw = _pick_bracket(fields, "単金", "単価", "希望単価", "金額")
    desired_rate = _parse_rate_man_yen(rate_raw)
    available_from = _pick_bracket(
        fields,
        "稼動日",
        "稼働日",
        "稼働開始",
        "稼動開始",
        "稼働可能",
        "稼動可能",
        "稼働",
        "稼動",
        "開始可能",
        "参画",
    )
    work_style = _pick_bracket(fields, "勤務形態", "勤務", "リモート", "出社")
    nearest_station = _pick_bracket(fields, "最寄駅", "最寄", "駅", "エリア")
    age = _as_optional_int(_pick_bracket(fields, "年齢"))
    gender = _normalize_gender(_pick_bracket(fields, "性別"))
    affiliation = (
        _pick_bracket(fields, "雇用形態", "契約形態", "所属", "雇用")
        or affiliation_from_name
    )
    source_company_name = _extract_sender_company(body, from_header)
    contact_name = _extract_contact_name(body, from_header)
    from app.constraint_rules import extract_talent_constraint_fields

    is_foreign_national, commerce_flow = extract_talent_constraint_fields(
        fields, body, affiliation=affiliation
    )
    summary = _extract_sales_comment_block(body)

    return {
        "display_name": display_name,
        "affiliation": affiliation,
        "age": age,
        "gender": gender,
        "experience_years": experience_years,
        "desired_rate": desired_rate,
        "available_from": available_from,
        "work_style": work_style,
        "nearest_station": nearest_station,
        "is_foreign_national": is_foreign_national,
        "commerce_flow": commerce_flow,
        "skills": skills,
        "source_company_name": source_company_name,
        "contact_name": contact_name,
        "summary": summary,
    }


def _merge_prefer_filled(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """overlay の空でない値で base を埋める。"""
    merged = dict(base)
    for key, value in overlay.items():
        current = merged.get(key)
        empty_current = current in (None, "", [])
        empty_value = value in (None, "", [])
        if empty_current and not empty_value:
            merged[key] = value
    return merged


def _normalize_talent(
    data: dict[str, Any],
    *,
    subject: str,
    body: str | None = None,
) -> tuple[dict[str, Any], bool]:
    raw_name = str(data.get("display_name") or "").strip()
    split_name, split_affiliation = _split_name_and_affiliation(raw_name) if raw_name else ("", None)
    display_name = split_name or subject.strip()[:128] or "名称未設定"
    affiliation = (
        str(data.get("affiliation")).strip()[:255]
        if data.get("affiliation")
        else (split_affiliation[:255] if split_affiliation else None)
    )
    needs_review = not bool(raw_name)
    skills = _as_str_list(data.get("skills"))
    skills = [s for s in skills if not s.startswith("実務経験")]
    from app.skill_terms import expand_skill_items, expand_skills_from_text

    skills = expand_skill_items(skills)
    # 営業コメント／自己PR は該当欄の原文。メール全文・AI要約は使わない
    summary = _extract_sales_comment_block(body) if body else None
    if summary == "要確認":
        summary = None
    if summary:
        skills = expand_skill_items([*skills, *expand_skills_from_text(summary)])
    skills = _filter_skill_items(skills)
    if not summary:
        needs_review = True
    if not skills:
        needs_review = True
    source_company_name = (
        str(data.get("source_company_name")).strip()[:255]
        if data.get("source_company_name")
        else None
    )
    contact_name = (
        str(data.get("contact_name")).strip()[:128]
        if data.get("contact_name")
        else None
    )
    is_foreign_raw = data.get("is_foreign_national")
    if isinstance(is_foreign_raw, bool):
        is_foreign_national: bool | None = is_foreign_raw
    elif is_foreign_raw is None or is_foreign_raw == "":
        is_foreign_national = None
    else:
        from app.constraint_rules import parse_talent_is_foreign_national

        is_foreign_national = parse_talent_is_foreign_national(is_foreign_raw)
    commerce_flow = (
        str(data.get("commerce_flow")).strip()[:64]
        if data.get("commerce_flow")
        else (affiliation[:64] if affiliation else None)
    )
    gender = _normalize_gender(data.get("gender"))
    normalized = {
        "display_name": display_name[:128],
        "affiliation": affiliation,
        "age": _as_optional_int(data.get("age")),
        "gender": gender,
        "experience_years": _as_optional_int(data.get("experience_years")),
        "desired_rate": _as_optional_int(data.get("desired_rate")),
        "available_from": (str(data.get("available_from")).strip()[:64] if data.get("available_from") else None),
        "work_style": (str(data.get("work_style")).strip()[:255] if data.get("work_style") else None),
        "nearest_station": (str(data.get("nearest_station")).strip()[:64] if data.get("nearest_station") else None),
        "is_foreign_national": is_foreign_national,
        "commerce_flow": commerce_flow,
        "skills": skills,
        "source_company_name": source_company_name,
        "contact_name": contact_name,
        "summary": summary,
    }
    return normalized, needs_review


def _normalize_project(data: dict[str, Any], *, subject: str) -> tuple[dict[str, Any], bool]:
    title = str(data.get("title") or "").strip() or subject.strip()[:255] or "案件名未設定"
    needs_review = not str(data.get("title") or "").strip()
    skills = _filter_skill_items(_as_str_list(data.get("required_skills")))
    preferred_skills = _filter_skill_items(
        [s for s in _as_str_list(data.get("preferred_skills")) if s and s != "要確認"]
    )
    from app.skill_terms import expand_skill_items

    skills = _filter_skill_items(expand_skill_items(skills))
    preferred_skills = _filter_skill_items(expand_skill_items(preferred_skills))
    # summary は業務内容の原文抜粋。AI が work_content で返した場合も受け入れる
    summary_raw = data.get("summary")
    if not summary_raw:
        summary_raw = data.get("work_content")
    summary = (str(summary_raw).strip() if summary_raw else None)
    if summary == "要確認":
        summary = None
    if not summary:
        needs_review = True
        summary = subject.strip()
    # 本文丸写しっぽい長い summary は要確認
    if summary and len(summary) > 400 and "ーーー" in summary:
        needs_review = True
    if not skills:
        needs_review = True
    source_company_name = (
        str(data.get("source_company_name")).strip()[:255]
        if data.get("source_company_name")
        else None
    )
    contact_name = (
        str(data.get("contact_name")).strip()[:128]
        if data.get("contact_name")
        else None
    )
    foreign_raw = data.get("foreign_nationality_ng")
    if isinstance(foreign_raw, bool):
        foreign_nationality_ng: bool | None = foreign_raw
    elif foreign_raw is None or foreign_raw == "":
        foreign_nationality_ng = None
    else:
        from app.constraint_rules import parse_project_foreign_nationality_ng

        foreign_nationality_ng = parse_project_foreign_nationality_ng(foreign_raw)
    commerce_flow_limit = (
        str(data.get("commerce_flow_limit")).strip()[:64]
        if data.get("commerce_flow_limit")
        else None
    )
    interview_count = _as_optional_int(data.get("interview_count"))
    if interview_count is None:
        interview_count = _as_optional_int(data.get("interview_rounds"))
    headcount = _as_optional_int(data.get("headcount"))
    if headcount is None:
        headcount = _as_optional_int(data.get("required_count"))
    project_code_raw = str(data.get("project_code") or "").strip()
    project_code = None if (not project_code_raw or project_code_raw == "要確認") else project_code_raw[:32]
    normalized = {
        "title": title[:255],
        "project_code": project_code,
        "required_skills": skills,
        "preferred_skills": preferred_skills,
        "rate_min": _as_optional_int(data.get("rate_min")),
        "rate_max": _as_optional_int(data.get("rate_max")),
        "location": (str(data.get("location")).strip()[:128] if data.get("location") else None),
        "work_style": (str(data.get("work_style")).strip()[:255] if data.get("work_style") else None),
        "working_hours": (str(data.get("working_hours")).strip()[:128] if data.get("working_hours") else None),
        "start_date": (str(data.get("start_date")).strip()[:64] if data.get("start_date") else None),
        "settlement_range": (
            str(data.get("settlement_range")).strip()[:64] if data.get("settlement_range") else None
        ),
        "interview_count": interview_count,
        "headcount": headcount,
        "foreign_nationality_ng": foreign_nationality_ng,
        "commerce_flow_limit": commerce_flow_limit,
        "source_company_name": source_company_name,
        "contact_name": contact_name,
        "summary": summary[:2000] if summary else summary,
    }
    return normalized, needs_review


def _heuristic(
    email_type: EmailType,
    subject: str,
    body: str,
    *,
    from_header: str | None = None,
) -> ExtractionResult:
    if email_type == "talent":
        raw = _rule_extract_talent(subject, body, from_header=from_header)
        data, needs_review = _normalize_talent(raw, subject=subject, body=body)
    else:
        raw = _rule_extract_project(subject, body, from_header=from_header)
        data, needs_review = _normalize_project(raw, subject=subject)
    return ExtractionResult(
        email_type=email_type,
        data=data,
        needs_review=needs_review,
        provider="heuristic",
        raw_summary=data.get("summary") or subject,
    )


def _build_user_prompt(
    email_type: EmailType,
    subject: str,
    body: str,
    *,
    from_header: str | None = None,
) -> str:
    hint = _TALENT_SCHEMA_HINT if email_type == "talent" else _PROJECT_SCHEMA_HINT
    from_line = f"\n\nFrom:\n{from_header}" if from_header else ""
    return f"{hint}{from_line}\n\nSubject:\n{subject}\n\nBody:\n{body[:8000]}"


def _finalize_with_rules(
    email_type: EmailType,
    subject: str,
    body: str,
    payload: dict[str, Any],
    *,
    provider: str,
    from_header: str | None = None,
) -> ExtractionResult:
    rules = (
        _rule_extract_talent(subject, body, from_header=from_header)
        if email_type == "talent"
        else _rule_extract_project(subject, body, from_header=from_header)
    )
    merged = _merge_prefer_filled(payload, rules)
    if email_type == "project":
        work = _extract_work_content_block(body)
        if work:
            merged["summary"] = work
        preferred = _extract_preferred_skills_block(body)
        if preferred:
            merged["preferred_skills"] = preferred
        req = _extract_skills_block(body)
        if req:
            merged["required_skills"] = req
        # 国籍はルールが取れたら AI の誤判定（可など）を上書きする
        if rules.get("foreign_nationality_ng") is not None:
            merged["foreign_nationality_ng"] = rules["foreign_nationality_ng"]
    if email_type == "talent":
        merged["summary"] = _extract_sales_comment_block(body)
        data, needs_review = _normalize_talent(merged, subject=subject, body=body)
    else:
        data, needs_review = _normalize_project(merged, subject=subject)
    return ExtractionResult(
        email_type=email_type,
        data=data,
        needs_review=needs_review,
        provider=provider,
        raw_summary=data.get("summary") or "",
    )


def _load_gemini_llm():
    try:
        from app.gemini_llm import call_gemini_json, resolve_gemini_batch_size
    except ImportError:
        batch_root = str(Path(__file__).resolve().parents[1])
        if batch_root not in sys.path:
            sys.path.insert(0, batch_root)
        try:
            from app.gemini_llm import call_gemini_json, resolve_gemini_batch_size
        except ImportError:
            return None
    return call_gemini_json, resolve_gemini_batch_size


def _extract_via_gemini(
    email_type: EmailType,
    subject: str,
    body: str,
    cfg: AiSettings,
    *,
    from_header: str | None = None,
) -> ExtractionResult | None:
    api_key = getattr(cfg, "gemini_api_key", "") or ""
    if not str(api_key).strip():
        return None
    loaded = _load_gemini_llm()
    if loaded is None:
        return None
    call_gemini_json, _ = loaded
    content = call_gemini_json(
        api_key=str(api_key),
        model=getattr(cfg, "gemini_model", None),
        system=(
            "You extract structured SES staffing data from Japanese emails. "
            "Formats vary by sender company. Reply with a single JSON object only. "
            "Never paste the full email body into summary."
        ),
        user=_build_user_prompt(email_type, subject, body, from_header=from_header),
        response_schema=_SINGLE_RESPONSE_SCHEMA[email_type],
        temperature=0.1,
        purpose=f"extract_single_{email_type}",
    )
    if not content:
        return None
    payload = _parse_json_object(content)
    if payload is None:
        return ExtractionResult(
            email_type=email_type,
            data={},
            needs_review=True,
            provider="gemini",
            raw_summary=content[:2000],
            error_code="ERR-0025",
        )
    payload.pop("id", None)
    return _finalize_with_rules(
        email_type, subject, body, payload, provider="gemini", from_header=from_header
    )


def _extract_batch_via_gemini(
    email_type: EmailType,
    requests: list[EmailExtractRequest],
    cfg: AiSettings,
) -> dict[str, ExtractionResult]:
    api_key = getattr(cfg, "gemini_api_key", "") or ""
    if not str(api_key).strip() or not requests:
        return {}
    loaded = _load_gemini_llm()
    if loaded is None:
        return {}
    call_gemini_json, _ = loaded

    user = _build_gemini_batch_user_prompt(email_type, requests)
    content = call_gemini_json(
        api_key=str(api_key),
        model=getattr(cfg, "gemini_model", None),
        system=_GEMINI_BATCH_SYSTEM,
        user=user,
        response_schema=_BATCH_ITEMS_SCHEMA[email_type],
        temperature=0.1,
        timeout_seconds=180,
        purpose=f"extract_batch_{email_type}",
    )
    if not content:
        return {}
    parsed = _parse_json_value(content)
    items = _extract_batch_items(parsed)
    if items is None:
        return {}

    by_id = {item.item_id: item for item in requests}
    results: dict[str, ExtractionResult] = {}
    for raw in items:
        request = _match_batch_request(_batch_item_mail_id(raw), requests, by_id)
        if request is None:
            continue
        payload = dict(raw)
        payload.pop("mail_id", None)
        payload.pop("id", None)
        body = _strip_html_if_needed((request.body or "").strip())
        results[request.item_id] = _finalize_with_rules(
            email_type,
            request.subject,
            body,
            payload,
            provider="gemini",
            from_header=request.from_header,
        )
    return results


def _match_batch_request(
    raw_id: Any,
    requests: list[EmailExtractRequest],
    by_id: dict[str, EmailExtractRequest],
) -> EmailExtractRequest | None:
    """Gemini が返した mail_id / id を入力メールへ対応付ける。"""
    if raw_id is None:
        return None
    text = str(raw_id).strip()
    if text in by_id:
        return by_id[text]
    try:
        seq = int(text)
    except (TypeError, ValueError):
        return None
    if 1 <= seq <= len(requests):
        return requests[seq - 1]
    return None


def _wait_gemini_wave_interval(sent_monotonic: float, interval_seconds: int) -> None:
    """同時波の送信から interval 秒経つまで待つ（応答後でも送信起算）。"""
    if interval_seconds <= 0:
        return
    remaining = sent_monotonic + interval_seconds - time.monotonic()
    if remaining > 0:
        time.sleep(remaining)


_SCHEMA_TOKEN_OVERHEAD = 1500
_CHARS_PER_INPUT_TOKEN = 1.7


def _estimate_gemini_input_tokens(text: str) -> int:
    """入力トークンの概算（日本語混在をやや多めに見る）。"""
    return max(1, int(len(text or "") / _CHARS_PER_INPUT_TOKEN) + _SCHEMA_TOKEN_OVERHEAD)


def _estimate_pack_input_tokens(email_type: EmailType, chunk: list[EmailExtractRequest]) -> int:
    user = _build_gemini_batch_user_prompt(email_type, chunk)
    return _estimate_gemini_input_tokens(f"{_GEMINI_BATCH_SYSTEM}\n{user}")


def _should_wait_before_retry(
    *,
    used_tokens: int,
    retry_tokens: int,
    tpm_limit: int,
    interval_seconds: int,
) -> bool:
    """再送パックが同一分の TPM に収まらなければ待機する。"""
    if interval_seconds <= 0:
        return False
    return used_tokens + retry_tokens > tpm_limit


def _merge_batch_hits(
    out: dict[str, ExtractionResult],
    chunk: list[EmailExtractRequest],
    hits: dict[str, ExtractionResult],
) -> None:
    for item in chunk:
        result = hits.get(item.item_id)
        if result is not None and result.data:
            out[item.item_id] = result


def _log_gemini_batch(event: str, message: str, **counts: Any) -> None:
    """欠け・再送件数を batch.log の extra に残す。"""
    try:
        from app.logging_util import get_batch_logger, log_event
    except ImportError:
        logging.getLogger(__name__).info("%s %s", message, counts)
        return
    log_event(
        get_batch_logger(),
        logging.INFO,
        event=event,
        message=message,
        operation="AI要約",
        method_name="extract_email_fields_batch",
        job_id="run",
        function_id="BAT-002",
        module_name="BAT-002.summarizer",
        extra=counts,
    )


def extract_email_fields_batch(
    email_type: EmailType,
    requests: list[EmailExtractRequest],
    cfg: AiSettings,
    *,
    batch_size: int | None = None,
    batch_parallel: int | None = None,
    wave_interval_seconds: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> dict[str, ExtractionResult]:
    """複数通を Gemini 20通パックで抽出する。

    1波目は最大 batch_parallel パックを同時送信する。欠けた通は、推定 TPM が
    枠内ならすぐ直列再送し、オーバーするときだけ wave_interval_seconds 待つ。
    それでも欠けた通だけ既存 LLM チェーンへフォールバックする。
    """
    if not requests:
        return {}
    loaded = _load_gemini_llm()
    size = 20
    parallel = 10
    interval = 60
    tpm_limit = 250_000
    if loaded is not None:
        from app.gemini_llm import (
            resolve_gemini_batch_parallel,
            resolve_gemini_batch_wave_interval_seconds,
            resolve_gemini_input_tpm,
        )

        _, resolve_gemini_batch_size = loaded
        size = resolve_gemini_batch_size(
            batch_size if batch_size is not None else getattr(cfg, "gemini_batch_size", 20)
        )
        parallel = resolve_gemini_batch_parallel(
            batch_parallel
            if batch_parallel is not None
            else getattr(cfg, "gemini_batch_parallel", 10)
        )
        interval = resolve_gemini_batch_wave_interval_seconds(
            wave_interval_seconds
            if wave_interval_seconds is not None
            else getattr(cfg, "gemini_batch_wave_interval_seconds", 60)
        )
        tpm_limit = resolve_gemini_input_tpm(getattr(cfg, "gemini_input_tpm", 250_000))
    else:
        if batch_size is not None:
            size = max(1, int(batch_size))
        if batch_parallel is not None:
            parallel = max(1, int(batch_parallel))
        if wave_interval_seconds is not None:
            interval = max(0, int(wave_interval_seconds))
        try:
            tpm_limit = max(1, int(getattr(cfg, "gemini_input_tpm", 250_000)))
        except (TypeError, ValueError):
            tpm_limit = 250_000

    chunks = [requests[offset : offset + size] for offset in range(0, len(requests), size)]
    first_wave = chunks[:parallel]
    out: dict[str, ExtractionResult] = {}
    total = len(requests)
    done = 0
    done_lock = threading.Lock()

    def _bump(n: int) -> None:
        nonlocal done
        with done_lock:
            done += n
            if on_progress is not None:
                on_progress(min(done, total), total)

    sent_at = time.monotonic()
    if first_wave:
        _log_gemini_batch(
            "gmail_ingest.gemini_wave_started",
            f"Gemini {email_type} first wave started",
            email_type=email_type,
            total=total,
            first_wave_packs=len(first_wave),
            parallel=parallel,
            interval_seconds=interval,
        )
        workers = min(len(first_wave), parallel)
        if workers <= 1:
            hits = _extract_batch_via_gemini(email_type, first_wave[0], cfg)
            _merge_batch_hits(out, first_wave[0], hits)
            _bump(len(first_wave[0]))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                future_to_chunk = {
                    pool.submit(_extract_batch_via_gemini, email_type, chunk, cfg): chunk
                    for chunk in first_wave
                }
                for future in as_completed(future_to_chunk):
                    chunk = future_to_chunk[future]
                    try:
                        hits = future.result() or {}
                    except Exception:  # noqa: BLE001
                        hits = {}
                    _merge_batch_hits(out, chunk, hits)
                    _bump(len(chunk))

    missing = [item for item in requests if item.item_id not in out]
    first_hits = total - len(missing)
    _log_gemini_batch(
        "gmail_ingest.gemini_wave_done",
        f"Gemini {email_type} first wave done: hits={first_hits} missing={len(missing)}/{total}",
        email_type=email_type,
        total=total,
        first_wave_hits=first_hits,
        missing_count=len(missing),
        first_wave_packs=len(first_wave),
    )
    if missing:
        retry_packs = (len(missing) + size - 1) // size
        retry_chunks = [missing[offset : offset + size] for offset in range(0, len(missing), size)]
        used_tokens = sum(_estimate_pack_input_tokens(email_type, chunk) for chunk in first_wave)
        retry_tokens = sum(_estimate_pack_input_tokens(email_type, chunk) for chunk in retry_chunks)
        wait_for_tpm = _should_wait_before_retry(
            used_tokens=used_tokens,
            retry_tokens=retry_tokens,
            tpm_limit=tpm_limit,
            interval_seconds=interval,
        )
        _log_gemini_batch(
            "gmail_ingest.gemini_retry",
            f"Gemini {email_type} retry {len(missing)} mails in {retry_packs} serial pack(s)",
            email_type=email_type,
            missing_count=len(missing),
            retry_packs=retry_packs,
            retry_mail_ids=[item.item_id for item in missing[:40]],
            used_tokens=used_tokens,
            retry_tokens=retry_tokens,
            tpm_limit=tpm_limit,
            wait_before_retry=wait_for_tpm,
        )
        if wait_for_tpm:
            _wait_gemini_wave_interval(sent_at, interval)
        for chunk in retry_chunks:
            hits = _extract_batch_via_gemini(email_type, chunk, cfg)
            _merge_batch_hits(out, chunk, hits)
            _bump(len(chunk))
        recovered = sum(1 for item in missing if item.item_id in out)
        _log_gemini_batch(
            "gmail_ingest.gemini_retry_done",
            f"Gemini {email_type} retry done: recovered={recovered} still_missing={len(missing) - recovered}",
            email_type=email_type,
            missing_count=len(missing),
            retry_packs=retry_packs,
            recovered_count=recovered,
            still_missing_count=len(missing) - recovered,
        )

    still_missing = [item for item in requests if item.item_id not in out]
    if not still_missing:
        if on_progress is not None:
            on_progress(total, total)
        return out

    _log_gemini_batch(
        "gmail_ingest.gemini_single_fallback",
        f"Gemini {email_type} single fallback {len(still_missing)} mails",
        email_type=email_type,
        still_missing_count=len(still_missing),
    )

    try:
        from app.ai_concurrency import map_parallel, resolve_ai_concurrency
    except ImportError:
        map_parallel = None  # type: ignore[assignment]
        resolve_ai_concurrency = None  # type: ignore[assignment]

    def _one(item: EmailExtractRequest) -> tuple[str, ExtractionResult]:
        return item.item_id, extract_email_fields(
            email_type,
            item.subject,
            item.body,
            cfg,
            from_header=item.from_header,
        )

    if map_parallel is not None and resolve_ai_concurrency is not None:
        concurrency = resolve_ai_concurrency(getattr(cfg, "ai_concurrency", 3))
        for item_id, result in map_parallel(still_missing, _one, concurrency=concurrency):
            out[item_id] = result
    else:
        for item in still_missing:
            item_id, result = _one(item)
            out[item_id] = result
    if on_progress is not None:
        on_progress(total, total)
    return out


def _extract_via_cursor(
    email_type: EmailType,
    subject: str,
    body: str,
    cfg: AiSettings,
    *,
    from_header: str | None = None,
) -> ExtractionResult | None:
    if not cfg.cursor_api_key.strip():
        return None
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError:
        return None

    prompt = _build_user_prompt(email_type, subject, body, from_header=from_header)
    try:
        with tempfile.TemporaryDirectory(prefix="bat002-cursor-") as cwd:
            result = Agent.prompt(
                prompt,
                AgentOptions(
                    api_key=cfg.cursor_api_key,
                    model="composer-2.5",
                    local=LocalAgentOptions(cwd=cwd),
                ),
            )
        text = getattr(result, "result", None) or str(result)
        payload = _parse_json_object(str(text))
        if payload is None:
            return ExtractionResult(
                email_type=email_type,
                data={},
                needs_review=True,
                provider="cursor",
                raw_summary=str(text)[:2000],
                error_code="ERR-0025",
            )
        return _finalize_with_rules(
            email_type, subject, body, payload, provider="cursor", from_header=from_header
        )
    except Exception:
        return None


def _extract_via_openai(
    email_type: EmailType,
    subject: str,
    body: str,
    cfg: AiSettings,
    *,
    from_header: str | None = None,
) -> ExtractionResult | None:
    if not cfg.openai_api_key.strip():
        return None
    try:
        from openai import OpenAI

        client = OpenAI(api_key=cfg.openai_api_key)
        response = client.chat.completions.create(
            model=cfg.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract structured SES staffing data from Japanese emails. "
                        "Formats vary by sender company. Reply with a single JSON object only. "
                        "Never paste the full email body into summary."
                    ),
                },
                {
                    "role": "user",
                    "content": _build_user_prompt(email_type, subject, body, from_header=from_header),
                },
            ],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        payload = _parse_json_object(content)
        if payload is None:
            return ExtractionResult(
                email_type=email_type,
                data={},
                needs_review=True,
                provider="openai",
                raw_summary=content[:2000],
                error_code="ERR-0025",
            )
        return _finalize_with_rules(
            email_type, subject, body, payload, provider="openai", from_header=from_header
        )
    except Exception:
        return None


def _extract_via_claude(
    email_type: EmailType,
    subject: str,
    body: str,
    cfg: AiSettings,
    *,
    from_header: str | None = None,
) -> ExtractionResult | None:
    api_key = getattr(cfg, "anthropic_api_key", "") or ""
    if not str(api_key).strip():
        return None
    try:
        from app.claude_llm import call_claude_messages
    except ImportError:
        batch_root = str(Path(__file__).resolve().parents[1])
        if batch_root not in sys.path:
            sys.path.insert(0, batch_root)
        try:
            from app.claude_llm import call_claude_messages
        except ImportError:
            return None

    content = call_claude_messages(
        api_key=str(api_key),
        model=getattr(cfg, "anthropic_model", None),
        system=(
            "You extract structured SES staffing data from Japanese emails. "
            "Formats vary by sender company. Reply with a single JSON object only. "
            "Never paste the full email body into summary. "
            "Do not wrap the JSON in Markdown fences."
        ),
        user=_build_user_prompt(email_type, subject, body, from_header=from_header),
        max_tokens=4096,
        temperature=0.1,
    )
    if not content:
        return None
    payload = _parse_json_object(content)
    if payload is None:
        return ExtractionResult(
            email_type=email_type,
            data={},
            needs_review=True,
            provider="claude",
            raw_summary=content[:2000],
            error_code="ERR-0025",
        )
    return _finalize_with_rules(
        email_type, subject, body, payload, provider="claude", from_header=from_header
    )


def _strip_html_if_needed(text: str) -> str:
    """HTML メールでも【項目】パースできるようタグを除去する。"""
    if "<" not in text or ">" not in text:
        return text
    cleaned = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</p\s*>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</div\s*>", "\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = (
        cleaned.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&#12288;", "　")
    )
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_email_fields(
    email_type: EmailType,
    subject: str,
    body_text: str | None,
    cfg: AiSettings,
    *,
    from_header: str | None = None,
) -> ExtractionResult:
    """メールから人材/案件フィールドを抽出する。

    企業ごとに書式が違うため AI（Gemini → Cursor → OpenAI → Claude）を優先し、
    キー未設定や AI 失敗時のみルールベースへフォールバックする。
    """
    body = _strip_html_if_needed((body_text or "").strip())
    subject_text = (subject or "").strip()

    gemini_result = _extract_via_gemini(
        email_type, subject_text, body, cfg, from_header=from_header
    )
    if gemini_result is not None and gemini_result.data:
        return gemini_result

    cursor_result = _extract_via_cursor(
        email_type, subject_text, body, cfg, from_header=from_header
    )
    if cursor_result is not None and cursor_result.data:
        return cursor_result

    openai_result = _extract_via_openai(
        email_type, subject_text, body, cfg, from_header=from_header
    )
    if openai_result is not None and openai_result.data:
        return openai_result

    claude_result = _extract_via_claude(
        email_type, subject_text, body, cfg, from_header=from_header
    )
    if claude_result is not None and claude_result.data:
        return claude_result

    return _heuristic(email_type, subject_text, body, from_header=from_header)


def summarize_email(subject: str, body_text: str | None, cfg: AiSettings) -> str:
    result = extract_email_fields("talent", subject, body_text, cfg)
    return result.raw_summary or result.data.get("summary") or subject
