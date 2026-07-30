"""提案メール向けの企業名・担当者名解決。"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Company, Contact, Email


def resolve_source_party(
    session: Session,
    email: Email | None,
    *,
    company_name_fallback: str | None = None,
) -> tuple[str, str]:
    """取込元メールから企業名・担当者名を返す。

    Returns:
        (company_name, contact_name) — 欠落時はフォールバック文言
    """
    company_name = (company_name_fallback or "").strip()
    contact_name = ""

    if email is not None:
        if email.source_company_id:
            company = session.get(Company, email.source_company_id)
            if company and (company.name or "").strip():
                company_name = company.name.strip()

        addr = (email.from_address or "").strip().lower()
        if addr:
            contact = session.scalar(
                select(Contact).where(func.lower(Contact.email) == addr).limit(1)
            )
            if contact and (contact.name or "").strip():
                contact_name = contact.name.strip()

    return (
        company_name or "（企業名なし）",
        contact_name or "ご担当者",
    )
