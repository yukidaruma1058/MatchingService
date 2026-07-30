"""BAT-003: ルールスコア採点ロジック（Google API 非依存）。

配点: スキル40 / 単価25 / 稼働15 / 勤務形態10 / 通勤10 = 100
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

_SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "golang": "go",
    "springboot": "spring boot",
    "spring": "spring boot",
    "postgres": "postgresql",
    "pgsql": "postgresql",
    "k8s": "kubernetes",
    "reactjs": "react",
    "vuejs": "vue",
    "nodejs": "node",
    "node.js": "node",
}

_REMOTE_HINTS = ("リモート", "remote", "在宅", "フルリモート", "テレワーク")
_ONSITE_HINTS = ("常駐", "出社", "オンサイト", "onsite", "出社必須", "客先")


@dataclass(frozen=True)
class ScoreResult:
    score: int
    score_band: str
    breakdown: dict[str, Any]


def normalize_skill(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").strip().lower()
    text = re.sub(r"[\s　_\-]+", " ", text)
    text = text.replace("．", ".").strip()
    return _SKILL_ALIASES.get(text.replace(" ", ""), _SKILL_ALIASES.get(text, text))


def normalize_skills(values: list[Any] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = normalize_skill(str(value))
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _skill_tokens(skill: str) -> list[str]:
    """正規化後スキルを「単語（空白区切り）」として扱う。

    これにより `java` が `javascript` の部分文字列として誤一致するのを防ぐ。
    """
    return [t for t in (skill or "").split(" ") if t]


def _tokens_subset(needle: str, haystack: str) -> bool:
    needle_tokens = _skill_tokens(needle)
    if not needle_tokens:
        return False
    hay_tokens = set(_skill_tokens(haystack))
    return all(t in hay_tokens for t in needle_tokens)


def score_band_for(score: int) -> str:
    clamped = max(0, min(100, int(score)))
    if clamped >= 90:
        return "90-100"
    low = (clamped // 10) * 10
    if low == 0:
        return "0-9"
    return f"{low}-{low + 9}"


def score_skills(talent_skills: list[Any] | None, required: list[Any] | None) -> tuple[int, list[str]]:
    req = normalize_skills(required)
    have = set(normalize_skills(talent_skills))
    if not req:
        return 20, []
    if not have:
        return 0, []
    # 部分文字列（includes）ベースだと `java` が `javascript` に誤ヒットするため、
    # 「空白区切りトークンの包含」で照合する。
    hits = [skill for skill in req if skill in have or any(_tokens_subset(skill, h) for h in have)]
    ratio = len(hits) / len(req)
    return int(round(40 * ratio)), hits


def score_rate(desired: int | None, rate_min: int | None, rate_max: int | None) -> int:
    if desired is None or (rate_min is None and rate_max is None):
        return 12
    lo = rate_min if rate_min is not None else rate_max
    hi = rate_max if rate_max is not None else rate_min
    assert lo is not None and hi is not None
    if lo > hi:
        lo, hi = hi, lo
    if lo <= desired <= hi:
        return 25
    if desired < lo:
        return 22
    over = desired - hi
    if over <= 5:
        return 18
    if over <= 10:
        return 10
    return 0


def _extract_month(text: str | None) -> int | None:
    if not text:
        return None
    if "即日" in text or "即稼働" in text:
        return 0
    match = re.search(r"(\d{1,2})\s*月", text)
    if match:
        month = int(match.group(1))
        if 1 <= month <= 12:
            return month
    return None


def score_availability(talent_from: str | None, project_start: str | None) -> int:
    if not talent_from or not project_start:
        return 8
    t_month = _extract_month(talent_from)
    p_month = _extract_month(project_start)
    if t_month == 0 and p_month == 0:
        return 15
    if t_month is not None and p_month is not None:
        if t_month == 0:
            return 15
        if p_month == 0:
            return 12 if t_month <= 2 else 8
        delta = (t_month - p_month + 12) % 12
        if t_month == p_month or delta == 0:
            return 15
        if t_month < p_month or delta >= 10:
            return 12
        if delta == 1:
            return 8
        return 3
    if "即日" in (talent_from or "") or "即日" in (project_start or ""):
        return 12
    return 8


def _has_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(h.lower() in lowered for h in hints)


def score_work_style(talent_ws: str | None, project_ws: str | None) -> int:
    if not talent_ws and not project_ws:
        return 5
    if not talent_ws or not project_ws:
        return 5
    t_remote = _has_any(talent_ws, _REMOTE_HINTS)
    t_onsite = _has_any(talent_ws, _ONSITE_HINTS)
    p_remote = _has_any(project_ws, _REMOTE_HINTS)
    p_onsite = _has_any(project_ws, _ONSITE_HINTS) and not p_remote
    if p_remote and t_remote:
        return 10
    if p_onsite and (t_onsite or "常駐" in talent_ws):
        return 8
    if p_onsite and t_remote and not t_onsite:
        return 2
    if not p_onsite and not p_remote:
        return 6
    return 6


def is_full_remote(project_ws: str | None) -> bool:
    if not project_ws:
        return False
    return any(k in project_ws for k in ("フルリモート", "完全リモート", "出社不要")) or (
        "リモート" in project_ws and "出社" not in project_ws and "常駐" not in project_ws
    )


def score_commute_minutes(minutes: int | None, *, full_remote: bool = False) -> int:
    if full_remote:
        return 10
    if minutes is None:
        return 5
    if minutes <= 45:
        return 10
    if minutes <= 60:
        return 8
    if minutes <= 90:
        return 5
    if minutes <= 120:
        return 2
    return 0


def score_pair(
    *,
    talent_skills: list[Any] | None,
    required_skills: list[Any] | None,
    desired_rate: int | None,
    rate_min: int | None,
    rate_max: int | None,
    available_from: str | None,
    start_date: str | None,
    talent_work_style: str | None,
    project_work_style: str | None,
    commute_minutes: int | None = None,
    commute_resolved: bool = False,
    project_foreign_nationality_ng: bool = False,
    talent_is_foreign_national: bool | None = None,
    project_commerce_flow_limit: str | None = None,
    talent_commerce_flow: str | None = None,
    talent_affiliation: str | None = None,
) -> ScoreResult:
    """1 人材×1 案件を採点する。

    commute_resolved=False のとき通勤は中立 5（Pass1）。
    full remote は commute_resolved に関わらず 10。
    外国籍不可・商流制限に抵触する場合は合計 0 点。
    """
    from constraint_rules import hard_constraint_reject_reason, hard_reject_label

    reject = hard_constraint_reject_reason(
        project_foreign_nationality_ng=bool(project_foreign_nationality_ng),
        talent_is_foreign_national=talent_is_foreign_national,
        project_commerce_flow_limit=project_commerce_flow_limit,
        talent_commerce_flow=talent_commerce_flow,
        talent_affiliation=talent_affiliation,
    )
    if reject:
        label = hard_reject_label(reject) or reject
        return ScoreResult(
            score=0,
            score_band="0-9",
            breakdown={
                "skill": 0,
                "rate": 0,
                "availability": 0,
                "work_style": 0,
                "commute": 0,
                "skill_hits": [],
                "hard_reject": reject,
                "hard_reject_label": label,
            },
        )

    skill, hits = score_skills(talent_skills, required_skills)
    rate = score_rate(desired_rate, rate_min, rate_max)
    availability = score_availability(available_from, start_date)
    work = score_work_style(talent_work_style, project_work_style)
    remote = is_full_remote(project_work_style)
    if remote:
        commute = 10
        minutes_out: int | None = None
    elif not commute_resolved:
        commute = 5
        minutes_out = None
    else:
        commute = score_commute_minutes(commute_minutes, full_remote=False)
        minutes_out = commute_minutes

    total = max(0, min(100, skill + rate + availability + work + commute))
    breakdown: dict[str, Any] = {
        "skill": skill,
        "rate": rate,
        "availability": availability,
        "work_style": work,
        "commute": commute,
        "skill_hits": hits,
    }
    if minutes_out is not None:
        breakdown["commute_minutes"] = minutes_out
    if remote:
        breakdown["commute_skip"] = "full_remote"
    return ScoreResult(score=total, score_band=score_band_for(total), breakdown=breakdown)
