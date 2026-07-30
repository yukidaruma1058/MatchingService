"""BAT-001: メール種別のキーワード判定ロジック。

判定順序:
  1. 件名の SES 定型表記（【...人材】 / ?人材 等）を最優先
  2. 件名のみをキーワード照合
  3. 件名 + 本文先頭をキーワード照合
ルール:
  - 要員キーワードのみヒット → 要員（talent）
  - 案件キーワードのみヒット → 案件（project）
  - 両方ヒット / どちらもヒットしない → 要確認（unknown）
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

EmailSortType = Literal["talent", "project", "unknown"]

_TALENT_SUBJECT_MARKERS = (
    re.compile(r"【[^】\n]*人材"),
    re.compile(r"\?人材"),
    re.compile(r"【人材"),
)
_PROJECT_SUBJECT_MARKERS = (
    re.compile(r"【[^】\n]*案件"),
    re.compile(r"\?案件"),
    re.compile(r"【案件"),
)
_SHORT_KEYWORD_MAX_LEN = 3


@dataclass(frozen=True)
class SortDecision:
    """1 通のメールに対する振り分け判定結果。"""

    email_type: EmailSortType   # talent / project / unknown
    target_label: str           # 付与すべき Gmail ラベル名
    talent_hits: int            # 要員キーワードのヒット数（ログ用）
    project_hits: int           # 案件キーワードのヒット数（ログ用）


def parse_keywords(raw: str) -> list[str]:
    """設定文字列（改行 or | 区切り）をキーワードリストへ変換する。"""
    normalized = raw.replace("|", "\n")
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def _keyword_matches(text: str, keyword: str) -> bool:
    """キーワードがテキストに含まれるか判定する（大文字小文字は区別しない）。"""
    lowered_text = text.casefold()
    lowered_keyword = keyword.casefold()
    if not lowered_keyword:
        return False

    if len(keyword) <= _SHORT_KEYWORD_MAX_LEN and keyword.isascii():
        pattern = re.compile(
            rf"(?<![A-Za-z0-9]){re.escape(lowered_keyword)}(?![A-Za-z0-9])",
            re.IGNORECASE,
        )
        return pattern.search(lowered_text) is not None

    return lowered_keyword in lowered_text


def _count_hits(text: str, keywords: list[str]) -> int:
    """テキスト内に含まれるキーワードの件数を返す。"""
    return sum(1 for keyword in keywords if _keyword_matches(text, keyword))


def _detect_subject_category(subject: str) -> EmailSortType | None:
    """件名の SES 定型表記から種別を判定する。曖昧な場合は None。"""
    talent_marked = any(pattern.search(subject) for pattern in _TALENT_SUBJECT_MARKERS)
    project_marked = any(pattern.search(subject) for pattern in _PROJECT_SUBJECT_MARKERS)

    if talent_marked and not project_marked:
        return "talent"
    if project_marked and not talent_marked:
        return "project"
    return None


def _decide_from_text(
    text: str,
    *,
    talent_keywords: list[str],
    project_keywords: list[str],
    talent_label: str,
    project_label: str,
) -> SortDecision | None:
    """テキストから一意に判定できる場合のみ SortDecision を返す。"""
    talent_hits = _count_hits(text, talent_keywords)
    project_hits = _count_hits(text, project_keywords)

    if talent_hits > 0 and project_hits == 0:
        return SortDecision("talent", talent_label, talent_hits, project_hits)
    if project_hits > 0 and talent_hits == 0:
        return SortDecision("project", project_label, talent_hits, project_hits)
    return None


def classify_email(
    subject: str,
    body_preview: str,
    *,
    talent_keywords: list[str],
    project_keywords: list[str],
    talent_label: str,
    project_label: str,
    unknown_label: str,
) -> SortDecision:
    """件名優先でメール種別と付与ラベルを判定する。"""
    subject_text = subject.strip()

    marker_category = _detect_subject_category(subject_text)
    if marker_category == "talent":
        talent_hits = _count_hits(subject_text, talent_keywords)
        project_hits = _count_hits(subject_text, project_keywords)
        return SortDecision("talent", talent_label, talent_hits, project_hits)
    if marker_category == "project":
        talent_hits = _count_hits(subject_text, talent_keywords)
        project_hits = _count_hits(subject_text, project_keywords)
        return SortDecision("project", project_label, talent_hits, project_hits)

    subject_decision = _decide_from_text(
        subject_text,
        talent_keywords=talent_keywords,
        project_keywords=project_keywords,
        talent_label=talent_label,
        project_label=project_label,
    )
    if subject_decision is not None:
        return subject_decision

    combined_text = f"{subject_text}\n{body_preview}".strip()
    combined_decision = _decide_from_text(
        combined_text,
        talent_keywords=talent_keywords,
        project_keywords=project_keywords,
        talent_label=talent_label,
        project_label=project_label,
    )
    if combined_decision is not None:
        return combined_decision

    talent_hits = _count_hits(combined_text, talent_keywords)
    project_hits = _count_hits(combined_text, project_keywords)
    return SortDecision("unknown", unknown_label, talent_hits, project_hits)
