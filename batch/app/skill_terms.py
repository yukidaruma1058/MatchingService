"""スキル文から技術名と工程を切り出す（DB 非依存）。

「基本設計以降」は工程を細分化し、「Java開発の経験5年程度」は技術名だけにする。
採点・メール抽出の両方から同じ関数を使う。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable

PHASE_ORDER: tuple[str, ...] = (
    "要件定義",
    "基本設計",
    "詳細設計",
    "製造",
    "単体試験",
    "結合試験",
    "システム試験",
    "リリース",
)

# 長い別名を先に照合する。裸の「試験」「テスト」は結合/システムを飲み込まない
_PHASE_ALIASES: tuple[tuple[str, str], ...] = (
    ("リリース作業", "リリース"),
    ("本番リリース", "リリース"),
    ("システムテスト", "システム試験"),
    ("システム試験", "システム試験"),
    ("総合テスト", "システム試験"),
    ("総合試験", "システム試験"),
    ("結合テスト", "結合試験"),
    ("結合試験", "結合試験"),
    ("単体テスト", "単体試験"),
    ("単体試験", "単体試験"),
    ("プログラミング", "製造"),
    ("コーディング", "製造"),
    ("外部設計", "基本設計"),
    ("内部設計", "詳細設計"),
    ("要件定義", "要件定義"),
    ("基本設計", "基本設計"),
    ("詳細設計", "詳細設計"),
    ("実装", "製造"),
    ("製造", "製造"),
    ("本番", "リリース"),
    ("リリース", "リリース"),
)

_ONWARD_RE = re.compile(r"^(?:以降|以上|以後)")

# 長い名前を先に照合して Java ⊂ JavaScript を防ぐ
_TECH_CANONICAL: tuple[str, ...] = (
    "TypeScript",
    "JavaScript",
    "PostgreSQL",
    "SQL Server",
    "Spring Boot",
    "Objective-C",
    "Kubernetes",
    "Terraform",
    "MongoDB",
    "Next.js",
    "Vue.js",
    "Node.js",
    "Angular",
    "Oracle",
    "MySQL",
    "Redis",
    "Docker",
    "Linux",
    "Azure",
    "Kotlin",
    "Python",
    "React",
    "Spring",
    "Ansible",
    "Java",
    "AWS",
    "GCP",
    "PHP",
    "Ruby",
    "Scala",
    "Swift",
    "HTML",
    "CSS",
    "Git",
    "C#",
    "Go",
)

_TECH_LOOKUP: dict[str, str] = {}
for _name in _TECH_CANONICAL:
    _key = unicodedata.normalize("NFKC", _name).strip().lower()
    _TECH_LOOKUP[_key] = _name
    _TECH_LOOKUP[_key.replace(" ", "")] = _name
    _TECH_LOOKUP[_key.replace(".", "")] = _name

_TECH_LOOKUP.update(
    {
        "js": "JavaScript",
        "ts": "TypeScript",
        "postgres": "PostgreSQL",
        "pgsql": "PostgreSQL",
        "golang": "Go",
        "k8s": "Kubernetes",
        "reactjs": "React",
        "vuejs": "Vue.js",
        "nodejs": "Node.js",
        "node": "Node.js",
        "springboot": "Spring Boot",
    }
)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").strip()


def _phase_index(canonical: str) -> int:
    return PHASE_ORDER.index(canonical)


def _find_phase_spans(text: str) -> list[tuple[int, int, str]]:
    """出現位置付きで工程を拾う。重複開始位置は長い別名を優先。"""
    spans: list[tuple[int, int, str]] = []
    occupied: list[tuple[int, int]] = []
    lower = text
    for alias, canonical in sorted(_PHASE_ALIASES, key=lambda row: len(row[0]), reverse=True):
        start = 0
        while True:
            idx = lower.find(alias, start)
            if idx < 0:
                break
            end = idx + len(alias)
            if any(not (end <= left or idx >= right) for left, right in occupied):
                start = idx + 1
                continue
            spans.append((idx, end, canonical))
            occupied.append((idx, end))
            start = end
    spans.sort(key=lambda row: row[0])
    return spans


def _expand_onward(canonical: str) -> list[str]:
    index = _phase_index(canonical)
    return list(PHASE_ORDER[index:])


def _extract_tech_names(text: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for name in _TECH_CANONICAL:
        if name == "Go":
            pattern = re.compile(r"(?<![A-Za-z0-9])Go(?:言語)?(?![A-Za-z0-9])")
        elif name == "C#":
            pattern = re.compile(r"(?<![A-Za-z0-9])C#(?![A-Za-z0-9])", re.IGNORECASE)
        elif re.fullmatch(r"[A-Za-z0-9.+#\- ]+", name):
            escaped = re.escape(name).replace(r"\ ", r"[\s　]*")
            pattern = re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(name), re.IGNORECASE)
        if not pattern.search(text):
            continue
        if name not in seen:
            seen.add(name)
            found.append(name)
    return found


def expand_skill_term(raw: str) -> list[str]:
    """1スキル文を技術名と工程のリストにする。"""
    text = _nfc(raw)
    if not text:
        return []

    compact = re.sub(r"[\s　]+", "", text).lower()
    if compact in _TECH_LOOKUP:
        return [_TECH_LOOKUP[compact]]

    phases: list[str] = []
    spans = _find_phase_spans(text)
    onward_from: str | None = None
    for _start, end, canonical in spans:
        rest = text[end:].lstrip(" 　・,、/｜|")
        if _ONWARD_RE.match(rest):
            onward_from = canonical
            break
    if onward_from is not None:
        phases = _expand_onward(onward_from)
    else:
        seen_phase: set[str] = set()
        for _start, _end, canonical in spans:
            if canonical not in seen_phase:
                seen_phase.add(canonical)
                phases.append(canonical)

    techs = _extract_tech_names(text)
    # 工程・技術が取れた文は原文を捨てる（年数や「ご経験」をスキルに残さない）
    combined = techs + [p for p in phases if p not in techs]
    if combined:
        return combined
    kept = (raw or "").strip()
    return [kept] if kept else []


def expand_skill_items(values: Iterable[Any] | None) -> list[str]:
    """スキル配列を分解し、重複を除いて元の順で返す。"""
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        for item in expand_skill_term(str(value)):
            key = _nfc(item).lower()
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def expand_skills_from_text(text: str | None) -> list[str]:
    """summary など自由文から技術名・工程を拾う。"""
    if not text or not str(text).strip():
        return []
    return expand_skill_items([text])
