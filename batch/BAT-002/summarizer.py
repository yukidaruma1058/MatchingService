"""BAT-002: メール本文から人材/案件の構造化 JSON を抽出する。

優先順:
  1. CURSOR_API_KEY → Cursor SDK
  2. OPENAI_API_KEY → OpenAI Chat Completions (JSON mode)
  3. ANTHROPIC_API_KEY → Claude Messages API
  4. いずれも無い / AI 失敗 → 【項目】：値 の定型パース + ヒューリスティック
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

EmailType = Literal["talent", "project"]


class AiSettings(Protocol):
    cursor_api_key: str
    openai_api_key: str
    openai_model: str
    anthropic_api_key: str
    anthropic_model: str


_TALENT_SCHEMA_HINT = """\
あなたは SES 人材紹介メールの抽出器です。
企業ごとにメール書式が違うため、【項目】定型に頼らず文脈から推論してください。
次の JSON オブジェクトだけを返してください。Markdown や説明文は禁止です。

必須キー:
- display_name (string): 要員の呼称・イニシャルのみ（雇用形態は含めない）
- skills (string array): 技術スキル（「実務経験：N年」は skills に入れず experience_years へ）
- summary (string|null): メール原文の営業コメント・自己PR・備考・アピール文。紹介者が書いた推薦・PR をそのまま要約せず近い文言で抜く。スキル一覧や署名・定型挨拶だけの場合は null
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
- 【備　考】詳細設計以降を自走できます → summary に入れる
- 署名「担当：中村」→ contact_name="中村"

出力例:
{"display_name":"ST","affiliation":"プロパー(コアパートナー所属)","age":25,"gender":"男性","experience_years":4,"desired_rate":65,"available_from":"8月～","work_style":null,"nearest_station":"北綾瀬駅","skills":["Java","Spring Boot"],"source_company_name":"株式会社アストロ","contact_name":"中村","summary":"詳細設計以降の工程を自走できます。"}
"""

_PROJECT_SCHEMA_HINT = """\
あなたは SES 案件紹介メールの抽出器です。
次の JSON オブジェクトだけを返してください。Markdown や説明文は禁止です。

必須キー:
- title (string): 案件名（【案件名】があればそれを使う）
- required_skills (string array): 必要スキル・技術
- summary (string): 業務内容。メールの【業務内容】【案件概要】【概要】【作業内容】【案件内容】などから、何をする案件かを2〜6文で要約する（署名・定型文の丸写し禁止）
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
{"title":"飲料メーカー向け保守業務","project_code":null,"required_skills":["Java","PostgreSQL"],"rate_min":null,"rate_max":null,"location":"お台場","work_style":"基本フルリモート（月1回程度出社）","working_hours":"10:00〜19:00","start_date":"8月～長期","settlement_range":"140〜180h","interview_count":2,"headcount":1,"foreign_nationality_ng":true,"commerce_flow_limit":"一社先まで","source_company_name":"株式会社サンプル","contact_name":"山田","summary":"飲料メーカー向け基幹システムの保守・改修。障害対応と軽微な機能追加が中心。Java/PostgreSQL を用いた既存資産の維持改善。"}
"""

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


def _extract_skills_block(text: str) -> list[str]:
    """必要スキル / 主な環境ブロックから技術名を拾う。"""
    skills: list[str] = []
    for label in ("必要スキル", "必須スキル", "主な環境", "技術要素", "スキル"):
        pattern = re.compile(
            rf"【\s*{re.escape(label)}[^】]*】\s*[:：]?\s*(?P<body>.*?)(?=\n【|\nー{{3,}}|\Z)",
            re.DOTALL,
        )
        match = pattern.search(text)
        if not match:
            continue
        body = match.group("body")
        skills.extend(_as_str_list(body))
    # 重複除去（順序維持）
    seen: set[str] = set()
    unique: list[str] = []
    for skill in skills:
        if skill not in seen and len(skill) <= 40:
            seen.add(skill)
            unique.append(skill)
    return unique[:20]


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
    work_content = _pick_bracket(
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
    # summary は営業コメント / 自己PR（プロフィール要約ではない）
    summary = _pick_bracket(
        fields,
        "営業コメント",
        "自己PR",
        "自己ＰＲ",
        "自己pr",
        "PR",
        "ＰＲ",
        "アピール",
        "推薦コメント",
        "コメント",
        "備考",
        "特徴",
        "強み",
        "補足",
    )
    if summary:
        summary = summary.strip()[:2000]
    else:
        summary = None

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


def _normalize_talent(data: dict[str, Any], *, subject: str) -> tuple[dict[str, Any], bool]:
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
    # summary は営業コメント / 自己PR。別名キーも受け入れる
    summary_raw = data.get("summary")
    if not summary_raw:
        summary_raw = data.get("sales_comment") or data.get("self_pr") or data.get("pr")
    summary = str(summary_raw).strip()[:2000] if summary_raw else None
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
    skills = _as_str_list(data.get("required_skills"))
    # summary は業務内容。AI が work_content で返した場合も受け入れる
    summary_raw = data.get("summary")
    if not summary_raw:
        summary_raw = data.get("work_content")
    summary = (str(summary_raw).strip() if summary_raw else None)
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
    normalized = {
        "title": title[:255],
        "project_code": (str(data.get("project_code")).strip()[:32] if data.get("project_code") else None),
        "required_skills": skills,
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
        data, needs_review = _normalize_talent(raw, subject=subject)
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
    if email_type == "talent":
        data, needs_review = _normalize_talent(merged, subject=subject)
    else:
        data, needs_review = _normalize_project(merged, subject=subject)
    return ExtractionResult(
        email_type=email_type,
        data=data,
        needs_review=needs_review,
        provider=provider,
        raw_summary=data.get("summary") or "",
    )


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

    企業ごとに書式が違うため AI（Cursor → OpenAI → Claude）を優先し、
    キー未設定や AI 失敗時のみルールベースへフォールバックする。
    """
    body = _strip_html_if_needed((body_text or "").strip())
    subject_text = (subject or "").strip()

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
