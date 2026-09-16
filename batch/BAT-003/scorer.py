"""BAT-003: ルールスコア採点ロジック（Google API 非依存）。

配点: スキル45（必須30 / 尚可15） / 単価30 / 稼働15 / 勤務形態10 = 100
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from app.skill_terms import expand_skill_items, expand_skills_from_text

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

REQUIRED_SKILL_MAX = 30
PREFERRED_SKILL_MAX = 15


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


def prepare_talent_skills(talent_skills: list[Any] | None, talent_summary: str | None = None) -> list[str]:
    """スキル欄と要約から、照合用に正規化したスキル一覧を1回だけ作る。"""
    return normalize_skills(
        expand_skill_items(list(talent_skills or []) + expand_skills_from_text(talent_summary))
    )


def prepare_project_skills(skills: list[Any] | None) -> list[str]:
    """案件の必須／尚可スキルを照合用に正規化する。"""
    return normalize_skills(expand_skill_items(skills))


def score_skills(
    talent_skills: list[Any] | None,
    required: list[Any] | None,
    *,
    max_points: int = REQUIRED_SKILL_MAX,
    prepared: bool = False,
) -> tuple[int, list[str]]:
    req = list(required or []) if prepared else normalize_skills(expand_skill_items(required))
    have = set(talent_skills or []) if prepared else set(normalize_skills(expand_skill_items(talent_skills)))
    if not req:
        return max_points // 2, []
    if not have:
        return 0, []
    # 部分文字列（includes）ベースだと `java` が `javascript` に誤ヒットするため、
    # 「空白区切りトークンの包含」で照合する。
    hits = [skill for skill in req if skill in have or any(_tokens_subset(skill, h) for h in have)]
    ratio = len(hits) / len(req)
    return int(round(max_points * ratio)), hits


def score_rate(desired: int | None, rate_min: int | None, rate_max: int | None) -> int:
    if desired is None or (rate_min is None and rate_max is None):
        return 17
    lo = rate_min if rate_min is not None else rate_max
    hi = rate_max if rate_max is not None else rate_min
    assert lo is not None and hi is not None
    if lo > hi:
        lo, hi = hi, lo
    if lo <= desired <= hi:
        return 30
    if desired < lo:
        return 27
    over = desired - hi
    if over <= 5:
        return 23
    if over <= 10:
        return 15
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


def score_pair(
    *,
    talent_skills: list[Any] | None = None,
    required_skills: list[Any] | None = None,
    preferred_skills: list[Any] | None = None,
    talent_summary: str | None = None,
    talent_skills_prepared: list[str] | None = None,
    required_skills_prepared: list[str] | None = None,
    preferred_skills_prepared: list[str] | None = None,
    desired_rate: int | None = None,
    rate_min: int | None = None,
    rate_max: int | None = None,
    available_from: str | None = None,
    start_date: str | None = None,
    talent_work_style: str | None = None,
    project_work_style: str | None = None,
    project_foreign_nationality_ng: bool = False,
    talent_is_foreign_national: bool | None = None,
    project_commerce_flow_limit: str | None = None,
    talent_commerce_flow: str | None = None,
    talent_affiliation: str | None = None,
) -> ScoreResult:
    """1 人材×1 案件を採点する。

    外国籍不可に抵触する場合は合計 0 点。商流制限は足切りしない。
    通勤は配点に含めない。prepared スキルを渡すと正規化を省略する。
    """
    from app.constraint_rules import hard_constraint_reject_reason, hard_reject_label

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
                "skill_hits": [],
                "preferred_hits": [],
                "skill_required": 0,
                "skill_preferred": 0,
                "hard_reject": reject,
                "hard_reject_label": label,
            },
        )

    have = talent_skills_prepared if talent_skills_prepared is not None else prepare_talent_skills(
        talent_skills, talent_summary
    )
    required = (
        required_skills_prepared
        if required_skills_prepared is not None
        else prepare_project_skills(required_skills)
    )
    preferred = (
        preferred_skills_prepared
        if preferred_skills_prepared is not None
        else prepare_project_skills(preferred_skills)
    )
    required_points, hits = score_skills(have, required, max_points=REQUIRED_SKILL_MAX, prepared=True)
    preferred_points, preferred_hits = score_skills(
        have, preferred, max_points=PREFERRED_SKILL_MAX, prepared=True
    )
    skill = required_points + preferred_points
    rate = score_rate(desired_rate, rate_min, rate_max)
    availability = score_availability(available_from, start_date)
    work = score_work_style(talent_work_style, project_work_style)
    total = max(0, min(100, skill + rate + availability + work))
    breakdown: dict[str, Any] = {
        "skill": skill,
        "rate": rate,
        "availability": availability,
        "work_style": work,
        "skill_hits": hits,
        "preferred_hits": preferred_hits,
        "skill_required": required_points,
        "skill_preferred": preferred_points,
    }
    return ScoreResult(score=total, score_band=score_band_for(total), breakdown=breakdown)


def score_pair_job(payload: dict[str, Any]) -> dict[str, Any]:
    """プロセス並列用。pickle 可能な dict を受けて採点結果 dict を返す。"""
    result = score_pair(
        talent_skills_prepared=payload.get("talent_skills_prepared"),
        required_skills_prepared=payload.get("required_skills_prepared"),
        preferred_skills_prepared=payload.get("preferred_skills_prepared"),
        desired_rate=payload.get("desired_rate"),
        rate_min=payload.get("rate_min"),
        rate_max=payload.get("rate_max"),
        available_from=payload.get("available_from"),
        start_date=payload.get("start_date"),
        talent_work_style=payload.get("talent_work_style"),
        project_work_style=payload.get("project_work_style"),
        project_foreign_nationality_ng=bool(payload.get("project_foreign_nationality_ng", False)),
        talent_is_foreign_national=payload.get("talent_is_foreign_national"),
        project_commerce_flow_limit=payload.get("project_commerce_flow_limit"),
        talent_commerce_flow=payload.get("talent_commerce_flow"),
        talent_affiliation=payload.get("talent_affiliation"),
    )
    return {
        "talent_id": payload["talent_id"],
        "project_id": payload["project_id"],
        "score": result.score,
        "score_band": result.score_band,
        "score_breakdown": result.breakdown,
    }
