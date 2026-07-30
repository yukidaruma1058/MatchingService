"""全企業共通の提案メールテンプレート。

- 案件提案用: 人材紹介メールへ案件を提案（BAT-007）
- 人材提案用: 案件配信メールへ要員を提案（BAT-009）

プレースホルダ:
  {{company_name}}    企業名（紹介元 / 配信元）
  {{contact_name}}    担当者名
  {{project_title}}   対象案件名（人材提案）
  {{items}}           案件一覧 / 要員一覧ブロック
                      （AI 採点時に保存したおすすめポイントを各 Item に付与）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

SETTING_KEY_TEMPLATE_PROJECT_PROPOSE = "outreach_template_project_propose"
SETTING_KEY_TEMPLATE_TALENT_PROPOSE = "outreach_template_talent_propose"
SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP = "talent_propose_rate_markup_man_yen"

DEFAULT_PROJECT_PROPOSE_TEMPLATE = (
    "{{company_name}}\n"
    "{{contact_name}} 様ご関係各位\n"
    "\n"
    "お世話になっております。マッチング結果に基づき、以下の案件をご提案いたします。\n"
    "\n"
    "{{items}}"
    "ご検討のほど、よろしくお願いいたします。\n"
)

DEFAULT_TALENT_PROPOSE_TEMPLATE = (
    "{{company_name}}\n"
    "{{contact_name}} 様\n"
    "\n"
    "お世話になっております。以下の要員をご提案いたします。\n"
    "\n"
    "■ 案件: {{project_title}}\n"
    "\n"
    "{{items}}"
    "ご検討のほど、よろしくお願いいたします。\n"
)


@dataclass(frozen=True)
class ProjectProposeLine:
    title: str | None
    required_skills: list[Any] | None
    rate_min: int | None
    rate_max: int | None
    work_style: str | None
    start_date: str | None
    score: int
    recommendation_points: str | None = None
    foreign_nationality_ng: bool | None = None
    commerce_flow_limit: str | None = None
    working_hours: str | None = None
    settlement_range: str | None = None
    interview_count: int | None = None
    summary: str | None = None


@dataclass(frozen=True)
class TalentProposeLine:
    display_name: str | None
    skills: list[Any] | None
    desired_rate: int | None
    available_from: str | None
    score: int
    ai_score: int | None = None
    recommendation_points: str | None = None
    is_foreign_national: bool | None = None
    commerce_flow: str | None = None


def _to_man_yen(value: int) -> int:
    """円（例: 600000）でも万円（例: 60）でも万円単位に揃える。"""
    if value >= 10000:
        return int(round(value / 10000))
    return value


def _format_man_yen(value: int | None) -> str | None:
    if value is None:
        return None
    return f"{_to_man_yen(value)}万円"


def _apply_man_yen_adjust(value: int, *, markdown_man_yen: int = 0) -> int:
    """万円単価から N 万円を引き、0 未満にはしない。"""
    markdown = max(0, int(markdown_man_yen))
    return max(0, _to_man_yen(value) - markdown)


def _format_rate(
    rate_min: int | None,
    rate_max: int | None,
    *,
    markdown_man_yen: int = 0,
) -> str | None:
    if rate_min is None and rate_max is None:
        return None
    lo = _apply_man_yen_adjust(rate_min, markdown_man_yen=markdown_man_yen) if rate_min is not None else None
    hi = _apply_man_yen_adjust(rate_max, markdown_man_yen=markdown_man_yen) if rate_max is not None else None
    if lo is not None and hi is not None:
        if lo == hi:
            return f"{lo}万円"
        return f"{lo}〜{hi}万円"
    if lo is not None:
        return f"{lo}万円〜"
    return f"〜{hi}万円"


def _join_skills(skills: list[Any] | None, *, limit: int) -> str | None:
    cleaned = [str(s).strip() for s in (skills or []) if str(s).strip()][:limit]
    if not cleaned:
        return None
    return ", ".join(cleaned)


def _format_nationality(is_foreign_national: bool | None) -> str | None:
    if is_foreign_national is True:
        return "外国籍"
    if is_foreign_national is False:
        return "日本国籍"
    return None


def _format_commerce_flow(commerce_flow: str | None) -> str | None:
    text = (commerce_flow or "").strip()
    return text or None


def _format_project_foreign_nationality(foreign_nationality_ng: bool | None) -> str | None:
    if foreign_nationality_ng is True:
        return "不可"
    if foreign_nationality_ng is False:
        return "可・不問"
    return None


def _format_interview_count(interview_count: int | None) -> str | None:
    if interview_count is None:
        return None
    return f"{int(interview_count)}回"


def _append_field(lines: list[str], label: str, value: str | None) -> None:
    text = (value or "").strip()
    if not text:
        return
    lines.append(f"  {label}: {text}")


def format_project_items(
    projects: Sequence[ProjectProposeLine],
    *,
    rate_markdown_man_yen: int = 0,
) -> str:
    lines: list[str] = []
    for idx, project in enumerate(projects, start=1):
        title = (project.title or "").strip() or f"案件{idx}"
        block = [f"【{idx}】{title}"]
        _append_field(block, "必須スキル", _join_skills(project.required_skills, limit=12))
        _append_field(
            block,
            "単価帯",
            _format_rate(project.rate_min, project.rate_max, markdown_man_yen=rate_markdown_man_yen),
        )
        _append_field(block, "勤務形態", project.work_style)
        _append_field(block, "勤務時間", project.working_hours)
        _append_field(block, "開始", project.start_date)
        _append_field(block, "精算幅", project.settlement_range)
        _append_field(
            block,
            "外国籍",
            _format_project_foreign_nationality(project.foreign_nationality_ng),
        )
        _append_field(block, "商流制限", _format_commerce_flow(project.commerce_flow_limit))
        _append_field(block, "面談回数", _format_interview_count(project.interview_count))
        _append_field(block, "案件概要", (project.summary or "").strip() or None)
        _append_field(block, "おすすめポイント", project.recommendation_points)
        block.append("")
        lines.extend(block)
    return "\n".join(lines)


def format_talent_items(talents: Sequence[TalentProposeLine]) -> str:
    lines: list[str] = []
    for idx, talent in enumerate(talents, start=1):
        name = (talent.display_name or "").strip() or f"要員{idx}"
        block = [f"【{idx}】{name}"]
        _append_field(block, "スキル", _join_skills(talent.skills, limit=10))
        _append_field(block, "単価", _format_man_yen(talent.desired_rate))
        _append_field(block, "稼働", talent.available_from)
        _append_field(block, "国籍", _format_nationality(talent.is_foreign_national))
        _append_field(block, "商流", _format_commerce_flow(talent.commerce_flow))
        _append_field(block, "おすすめポイント", talent.recommendation_points)
        block.append("")
        lines.extend(block)
    return "\n".join(lines)


def apply_template(template: str, replacements: dict[str, str]) -> str:
    text = template or ""
    for key, value in replacements.items():
        text = text.replace(f"{{{{{key}}}}}", value)
    return text


def render_project_propose_body(
    *,
    template: str | None,
    projects: Sequence[ProjectProposeLine],
    company_name: str | None = None,
    contact_name: str | None = None,
    rate_markdown_man_yen: int = 0,
) -> str:
    items = format_project_items(projects, rate_markdown_man_yen=rate_markdown_man_yen)
    tpl = (template or "").strip() or DEFAULT_PROJECT_PROPOSE_TEMPLATE
    contact = (contact_name or "").strip() or "ご担当者"
    company = (company_name or "").strip() or "（企業名なし）"
    body = apply_template(
        tpl,
        {
            "company_name": company,
            "contact_name": contact,
            "items": items,
        },
    )
    if "{{items}}" not in tpl:
        body = body.rstrip() + "\n\n" + items
    return body


def render_talent_propose_body(
    *,
    template: str | None,
    project_title: str | None,
    talents: Sequence[TalentProposeLine],
    company_name: str | None = None,
    contact_name: str | None = None,
) -> str:
    items = format_talent_items(talents)
    tpl = (template or "").strip() or DEFAULT_TALENT_PROPOSE_TEMPLATE
    contact = (contact_name or "").strip() or "ご担当者"
    company = (company_name or "").strip() or "（企業名なし）"
    body = apply_template(
        tpl,
        {
            "company_name": company,
            "contact_name": contact,
            "project_title": project_title or "（案件名なし）",
            "items": items,
        },
    )
    if "{{items}}" not in tpl:
        body = body.rstrip() + "\n\n" + items
    return body


def parse_talent_propose_rate_markup(raw: object, *, default: int = 0) -> int:
    """案件提案メール（人材紹介メールへ案件）の単価帯調整 N（万円）。

    案件単価帯の上下限からそれぞれ N を差し引く。不正値は default、範囲は 0〜100。
    """
    try:
        parsed = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0, min(100, parsed))
