"""取込時の人材・案件の業務キー重複判定。"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, Project, Talent

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_business_key_part(value: str | None) -> str:
    """比較用に空白を正規化し、大文字小文字を揃える。"""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    return _WHITESPACE_RE.sub(" ", text).casefold()


def _normalized_sql(column):
    return func.lower(
        func.regexp_replace(func.btrim(func.coalesce(column, "")), r"\s+", " ", "g")
    )


def find_talent_by_business_key(
    session: Session,
    *,
    display_name: str,
    source_company_name: str | None,
    nearest_station: str | None,
) -> Talent | None:
    """氏名 + 配信会社 + 最寄り駅で既存人材を検索する。"""
    name_key = normalize_business_key_part(display_name)
    if not name_key:
        return None
    company_key = normalize_business_key_part(source_company_name)
    station_key = normalize_business_key_part(nearest_station)

    return session.scalar(
        select(Talent)
        .where(
            _normalized_sql(Talent.display_name) == name_key,
            _normalized_sql(Talent.source_company_name) == company_key,
            _normalized_sql(Talent.nearest_station) == station_key,
        )
        .order_by(Talent.updated_at.desc())
        .limit(1)
    )


def _project_company_name(session: Session, project: Project) -> str | None:
    if project.source_company_name:
        return project.source_company_name
    if project.distributor_company_id is None:
        return None
    company = session.get(Company, project.distributor_company_id)
    return company.name if company else None


def find_project_by_business_key(
    session: Session,
    *,
    title: str,
    source_company_name: str | None,
) -> Project | None:
    """案件名 + 配信会社で既存案件を検索する。"""
    title_key = normalize_business_key_part(title)
    if not title_key:
        return None
    company_key = normalize_business_key_part(source_company_name)

    found = session.scalar(
        select(Project)
        .where(
            _normalized_sql(Project.title) == title_key,
            _normalized_sql(Project.source_company_name) == company_key,
        )
        .order_by(Project.updated_at.desc())
        .limit(1)
    )
    if found is not None:
        return found

    rows = session.scalars(select(Project).order_by(Project.updated_at.desc())).all()
    for project in rows:
        if project.source_company_name:
            continue
        existing_company = _project_company_name(session, project)
        if (
            normalize_business_key_part(project.title) == title_key
            and normalize_business_key_part(existing_company) == company_key
        ):
            return project
    return None
