"""企業・担当者マスタの upsert（BAT-002 取込時）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Company, Contact, Email, Project, Talent

CompanyKind = Literal["introducer", "distributor", "both"]


@dataclass(frozen=True)
class CompanyContactLink:
    company_id: UUID
    contact_id: UUID | None
    company_name: str | None


_EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)


def extract_email_address(raw: str | None) -> str | None:
    if not raw:
        return None
    match = _EMAIL_RE.search(raw)
    return match.group(0).lower() if match else None


def extract_email_domain(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[-1].strip().lower()
    # フリーメールは企業ドメインとして弱いので名前突合を優先
    if not domain or domain in {"gmail.com", "yahoo.co.jp", "outlook.com", "hotmail.com", "icloud.com"}:
        return None
    return domain


def _merge_kind(existing: str | None, incoming: CompanyKind) -> str:
    if not existing or existing == incoming:
        return incoming
    if existing == "both" or incoming == "both":
        return "both"
    if {existing, incoming} == {"introducer", "distributor"}:
        return "both"
    return incoming


def upsert_company(
    session: Session,
    *,
    name: str | None,
    domain: str | None,
    default_email: str | None,
    kind: CompanyKind,
) -> Company | None:
    """ドメイン → 名前の順で突合し、なければ新規作成。"""
    cleaned_name = (name or "").strip()[:255] or None
    cleaned_domain = (domain or "").strip().lower()[:255] or None
    cleaned_email = (default_email or "").strip().lower()[:255] or None
    if not cleaned_name and not cleaned_domain and not cleaned_email:
        return None
    if not cleaned_name:
        cleaned_name = cleaned_domain or (cleaned_email.split("@")[-1] if cleaned_email else "不明な企業")

    now = datetime.now().astimezone()
    company: Company | None = None
    if cleaned_domain:
        company = session.scalar(select(Company).where(Company.domain == cleaned_domain).limit(1))
    if company is None and cleaned_name:
        company = session.scalar(select(Company).where(Company.name == cleaned_name).limit(1))

    if company is None:
        company = Company(
            id=uuid4(),
            name=cleaned_name,
            kind=kind,
            domain=cleaned_domain,
            default_email=cleaned_email,
            notes=None,
            created_at=now,
            updated_at=now,
        )
        session.add(company)
        session.flush()
        return company

    company.kind = _merge_kind(company.kind, kind)
    if cleaned_name and (not company.name or company.name == company.domain):
        company.name = cleaned_name
    if cleaned_domain and not company.domain:
        company.domain = cleaned_domain
    if cleaned_email and not company.default_email:
        company.default_email = cleaned_email
    company.updated_at = now
    session.flush()
    return company


def upsert_contact(
    session: Session,
    *,
    company_id: UUID,
    name: str | None,
    email: str | None,
) -> Contact | None:
    cleaned_email = extract_email_address(email)
    if not cleaned_email:
        return None
    cleaned_name = (name or "").strip()[:128] or cleaned_email.split("@")[0][:128]
    now = datetime.now().astimezone()
    existing = session.scalar(select(Contact).where(Contact.email == cleaned_email).limit(1))
    if existing is None:
        row = Contact(
            id=uuid4(),
            company_id=company_id,
            name=cleaned_name,
            email=cleaned_email,
            role="primary",
            phone=None,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        session.flush()
        return row

    existing.company_id = company_id
    if cleaned_name:
        existing.name = cleaned_name
    existing.is_active = True
    existing.updated_at = now
    session.flush()
    return existing


def _guess_contact_name_from_header(from_header: str | None) -> str | None:
    if not from_header:
        return None
    match = re.match(r'^"?([^"<]+)"?\s*<', from_header.strip())
    if not match:
        return None
    name = match.group(1).strip().strip("'")
    if not name or "@" in name:
        return None
    if re.search(r"(株式会社|有限会社|合同会社|Inc|Corp|Ltd)", name, re.IGNORECASE):
        return None
    return name[:128]


def link_company_contact_for_ingest(
    session: Session,
    *,
    email_id: UUID,
    email_type: str,
    company_name: str | None,
    contact_name: str | None,
    contact_email: str | None,
    from_header: str | None = None,
    talent_id: UUID | None = None,
    project_id: UUID | None = None,
) -> CompanyContactLink | None:
    """取込結果から企業・担当者を upsert し、emails / talents / projects に紐付ける。"""
    kind: CompanyKind = "introducer" if email_type == "talent" else "distributor"
    addr = extract_email_address(contact_email) or extract_email_address(from_header)
    domain = extract_email_domain(addr)
    resolved_contact_name = (contact_name or "").strip() or _guess_contact_name_from_header(from_header)
    company = upsert_company(
        session,
        name=company_name,
        domain=domain,
        default_email=addr,
        kind=kind,
    )
    if company is None:
        return None

    contact = upsert_contact(
        session,
        company_id=company.id,
        name=resolved_contact_name,
        email=addr,
    )

    now = datetime.now().astimezone()
    session.execute(
        update(Email)
        .where(Email.id == email_id)
        .values(source_company_id=company.id, updated_at=now)
    )
    if email_type == "talent" and talent_id is not None:
        session.execute(
            update(Talent)
            .where(Talent.id == talent_id)
            .values(
                introducer_company_id=company.id,
                source_company_name=company.name,
                updated_at=now,
            )
        )
    if email_type == "project" and project_id is not None:
        session.execute(
            update(Project)
            .where(Project.id == project_id)
            .values(distributor_company_id=company.id, updated_at=now)
        )
    session.flush()
    return CompanyContactLink(
        company_id=company.id,
        contact_id=contact.id if contact else None,
        company_name=company.name,
    )
