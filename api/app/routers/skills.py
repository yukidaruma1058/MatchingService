"""スキルマスタ API。"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Skill, SkillCategory
from app.skill_catalog import (
    UNCATEGORIZED_CATEGORY_NAME,
    ensure_uncategorized_category,
    move_skills_to_uncategorized,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillItem(BaseModel):
    id: str
    name: str
    category_id: str
    category_name: str


class SkillCategoryItem(BaseModel):
    id: str
    name: str
    sort_order: int
    is_uncategorized: bool
    skill_count: int = 0


class SkillCatalogGroup(BaseModel):
    id: str
    label: str
    sort_order: int
    is_uncategorized: bool
    options: list[str]


class SkillCategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    sort_order: int | None = Field(None, ge=0, le=9999)


class SkillCategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=128)
    sort_order: int | None = Field(None, ge=0, le=9999)


class SkillUpdate(BaseModel):
    category_id: str


def _parse_uuid(value: str, field: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field}") from exc


@router.get("/catalog", response_model=list[SkillCatalogGroup])
def get_skill_catalog(session: Session = Depends(get_db)) -> list[SkillCatalogGroup]:
    """一覧検索フォーム用。カテゴリ順のスキル一覧。"""
    ensure_uncategorized_category(session)
    session.commit()
    categories = list(
        session.scalars(
            select(SkillCategory).order_by(SkillCategory.sort_order.asc(), SkillCategory.name.asc())
        ).all()
    )
    skills = list(session.scalars(select(Skill).order_by(Skill.name.asc())).all())
    by_cat: dict[UUID, list[str]] = {c.id: [] for c in categories}
    for skill in skills:
        by_cat.setdefault(skill.category_id, []).append(skill.name)
    return [
        SkillCatalogGroup(
            id=str(cat.id),
            label=cat.name,
            sort_order=cat.sort_order,
            is_uncategorized=cat.is_uncategorized,
            options=by_cat.get(cat.id, []),
        )
        for cat in categories
        if by_cat.get(cat.id)
    ]


@router.get("/categories", response_model=list[SkillCategoryItem])
def list_categories(session: Session = Depends(get_db)) -> list[SkillCategoryItem]:
    ensure_uncategorized_category(session)
    session.commit()
    categories = list(
        session.scalars(
            select(SkillCategory).order_by(SkillCategory.sort_order.asc(), SkillCategory.name.asc())
        ).all()
    )
    skills = list(session.scalars(select(Skill)).all())
    counts: dict[UUID, int] = {}
    for skill in skills:
        counts[skill.category_id] = counts.get(skill.category_id, 0) + 1
    return [
        SkillCategoryItem(
            id=str(cat.id),
            name=cat.name,
            sort_order=cat.sort_order,
            is_uncategorized=cat.is_uncategorized,
            skill_count=counts.get(cat.id, 0),
        )
        for cat in categories
    ]


@router.get("", response_model=list[SkillItem])
def list_skills(session: Session = Depends(get_db)) -> list[SkillItem]:
    ensure_uncategorized_category(session)
    session.commit()
    categories = {
        c.id: c
        for c in session.scalars(select(SkillCategory)).all()
    }
    skills = list(session.scalars(select(Skill).order_by(Skill.name.asc())).all())
    return [
        SkillItem(
            id=str(skill.id),
            name=skill.name,
            category_id=str(skill.category_id),
            category_name=categories[skill.category_id].name
            if skill.category_id in categories
            else UNCATEGORIZED_CATEGORY_NAME,
        )
        for skill in skills
    ]


@router.post("/categories", response_model=SkillCategoryItem)
def create_category(
    body: SkillCategoryCreate,
    session: Session = Depends(get_db),
) -> SkillCategoryItem:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Category name is required")
    if name == UNCATEGORIZED_CATEGORY_NAME:
        raise HTTPException(status_code=400, detail="Cannot create reserved category name")
    existing = session.scalar(select(SkillCategory).where(SkillCategory.name == name))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Category already exists")
    now = datetime.now().astimezone()
    row = SkillCategory(
        id=uuid.uuid4(),
        name=name,
        sort_order=body.sort_order if body.sort_order is not None else 100,
        is_uncategorized=False,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return SkillCategoryItem(
        id=str(row.id),
        name=row.name,
        sort_order=row.sort_order,
        is_uncategorized=False,
        skill_count=0,
    )


@router.patch("/categories/{category_id}", response_model=SkillCategoryItem)
def update_category(
    category_id: str,
    body: SkillCategoryUpdate,
    session: Session = Depends(get_db),
) -> SkillCategoryItem:
    row = session.get(SkillCategory, _parse_uuid(category_id, "category_id"))
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Category name is required")
        if row.is_uncategorized and name != UNCATEGORIZED_CATEGORY_NAME:
            raise HTTPException(status_code=400, detail="Cannot rename uncategorized category")
        conflict = session.scalar(
            select(SkillCategory).where(SkillCategory.name == name, SkillCategory.id != row.id)
        )
        if conflict is not None:
            raise HTTPException(status_code=409, detail="Category already exists")
        row.name = name
    if body.sort_order is not None:
        row.sort_order = body.sort_order
    row.updated_at = datetime.now().astimezone()
    session.commit()
    count = len(list(session.scalars(select(Skill).where(Skill.category_id == row.id)).all()))
    return SkillCategoryItem(
        id=str(row.id),
        name=row.name,
        sort_order=row.sort_order,
        is_uncategorized=row.is_uncategorized,
        skill_count=count,
    )


@router.delete("/categories/{category_id}")
def delete_category(category_id: str, session: Session = Depends(get_db)) -> dict[str, object]:
    row = session.get(SkillCategory, _parse_uuid(category_id, "category_id"))
    if row is None:
        raise HTTPException(status_code=404, detail="Category not found")
    if row.is_uncategorized:
        raise HTTPException(status_code=400, detail="Cannot delete uncategorized category")
    moved = move_skills_to_uncategorized(session, row.id)
    session.delete(row)
    session.commit()
    return {"status": "ok", "moved_skills": moved}


@router.patch("/{skill_id}", response_model=SkillItem)
def update_skill(
    skill_id: str,
    body: SkillUpdate,
    session: Session = Depends(get_db),
) -> SkillItem:
    skill = session.get(Skill, _parse_uuid(skill_id, "skill_id"))
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    category = session.get(SkillCategory, _parse_uuid(body.category_id, "category_id"))
    if category is None:
        raise HTTPException(status_code=404, detail="Category not found")
    skill.category_id = category.id
    skill.updated_at = datetime.now().astimezone()
    session.commit()
    return SkillItem(
        id=str(skill.id),
        name=skill.name,
        category_id=str(category.id),
        category_name=category.name,
    )
