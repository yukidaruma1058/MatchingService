"""スキルマスタの正規化・照合・シード。"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Skill, SkillCategory

UNCATEGORIZED_CATEGORY_NAME = "未分類"

DEFAULT_SKILL_GROUPS: list[tuple[str, int, list[str]]] = [
    ("開発言語", 10, ["Java", "Kotlin", "TypeScript", "Python"]),
    ("環境", 20, ["AWS", "Docker", "Linux"]),
    ("フレームワーク/パッケージ", 30, ["Spring", "Vue.js", "React", "Next.js"]),
    ("工程", 40, ["要件定義", "基本設計", "詳細設計", "製造", "単体試験", "結合試験", "システム試験", "リリース"]),
    (UNCATEGORIZED_CATEGORY_NAME, 999, []),
]


def skill_name_key(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").strip().lower()
    text = re.sub(r"[\s　_\-]+", " ", text)
    text = text.replace("．", ".").strip()
    return text


def ensure_uncategorized_category(session: Session) -> SkillCategory:
    row = session.scalar(
        select(SkillCategory).where(SkillCategory.is_uncategorized.is_(True))
    )
    if row is not None:
        return row
    by_name = session.scalar(
        select(SkillCategory).where(SkillCategory.name == UNCATEGORIZED_CATEGORY_NAME)
    )
    if by_name is not None:
        by_name.is_uncategorized = True
        by_name.sort_order = max(by_name.sort_order, 999)
        session.flush()
        return by_name
    now = datetime.now().astimezone()
    row = SkillCategory(
        id=uuid.uuid4(),
        name=UNCATEGORIZED_CATEGORY_NAME,
        sort_order=999,
        is_uncategorized=True,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row


def seed_skill_master(session: Session) -> None:
    """初期カテゴリ・スキルを投入（既存があればスキップ）。"""
    ensure_uncategorized_category(session)
    now = datetime.now().astimezone()
    for name, sort_order, skill_names in DEFAULT_SKILL_GROUPS:
        category = session.scalar(select(SkillCategory).where(SkillCategory.name == name))
        if category is None:
            category = SkillCategory(
                id=uuid.uuid4(),
                name=name,
                sort_order=sort_order,
                is_uncategorized=(name == UNCATEGORIZED_CATEGORY_NAME),
                created_at=now,
                updated_at=now,
            )
            session.add(category)
            session.flush()
        else:
            if name == UNCATEGORIZED_CATEGORY_NAME:
                category.is_uncategorized = True
            if category.sort_order != sort_order and name != UNCATEGORIZED_CATEGORY_NAME:
                category.sort_order = sort_order

        for skill_name in skill_names:
            key = skill_name_key(skill_name)
            if not key:
                continue
            existing = session.scalar(select(Skill).where(Skill.name_key == key))
            if existing is None:
                session.add(
                    Skill(
                        id=uuid.uuid4(),
                        category_id=category.id,
                        name=skill_name.strip(),
                        name_key=key,
                        created_at=now,
                        updated_at=now,
                    )
                )
    session.flush()


def ensure_skills_in_master(
    session: Session,
    raw_skills: Sequence[Any] | None,
) -> list[str]:
    """抽出スキルをマスタ照合し、なければ未分類で追加。正式名称のリストを返す。"""
    uncategorized = ensure_uncategorized_category(session)
    now = datetime.now().astimezone()
    result: list[str] = []
    seen_keys: set[str] = set()

    for value in raw_skills or []:
        display = str(value).strip()
        key = skill_name_key(display)
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)

        existing = session.scalar(select(Skill).where(Skill.name_key == key))
        if existing is None:
            existing = Skill(
                id=uuid.uuid4(),
                category_id=uncategorized.id,
                name=display,
                name_key=key,
                created_at=now,
                updated_at=now,
            )
            session.add(existing)
            session.flush()
        result.append(existing.name)

    return result


def move_skills_to_uncategorized(session: Session, category_id: UUID) -> int:
    uncategorized = ensure_uncategorized_category(session)
    if category_id == uncategorized.id:
        return 0
    rows = list(session.scalars(select(Skill).where(Skill.category_id == category_id)).all())
    now = datetime.now().astimezone()
    for skill in rows:
        skill.category_id = uncategorized.id
        skill.updated_at = now
    session.flush()
    return len(rows)
