"""メール取込状況 API。"""

from __future__ import annotations

import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Email, Project, Talent
from app.schemas import EmailDetail, EmailListItem

router = APIRouter(prefix="/api/emails", tags=["emails"])


@router.get("", response_model=list[EmailListItem])
def list_emails(session: Session = Depends(get_db)) -> list[EmailListItem]:
    emails = session.scalars(select(Email).order_by(Email.received_at.desc()).limit(200)).all()
    talent_by_email = {
        row.email_id: row.id
        for row in session.scalars(select(Talent)).all()
    }
    project_by_email = {
        row.email_id: row.id
        for row in session.scalars(select(Project)).all()
    }
    items: list[EmailListItem] = []
    for email in emails:
        items.append(
            EmailListItem(
                id=str(email.id),
                gmail_message_id=email.gmail_message_id,
                subject=email.subject,
                from_address=email.from_address,
                label=email.label,
                email_type=email.email_type,
                status=email.status,
                received_at=email.received_at.isoformat(),
                talent_id=str(talent_by_email[email.id]) if email.id in talent_by_email else None,
                project_id=str(project_by_email[email.id]) if email.id in project_by_email else None,
            )
        )
    return items


def _email_body_text(email: Email) -> str:
    """取込元メールの原文を返す。

    過去の取込では body_text に AI 要約を上書き保存していたため、
    body_html（原文）があればそちらを優先する。
    """
    if email.body_html and email.body_html.strip():
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", email.body_html)
        text = re.sub(r"(?i)<br\s*/?>", "\n", text)
        text = re.sub(r"(?i)</p\s*>", "\n", text)
        text = re.sub(r"(?s)<[^>]+>", "", text)
        cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
        if cleaned:
            return cleaned
    if email.body_text and email.body_text.strip():
        return email.body_text
    return ""


@router.get("/{email_id}", response_model=EmailDetail)
def get_email(email_id: str, session: Session = Depends(get_db)) -> EmailDetail:
    try:
        email_uuid = UUID(email_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Email not found") from exc

    email = session.get(Email, email_uuid)
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")

    return EmailDetail(
        id=str(email.id),
        gmail_message_id=email.gmail_message_id,
        subject=email.subject,
        from_address=email.from_address,
        label=email.label,
        email_type=email.email_type,
        status=email.status,
        received_at=email.received_at.isoformat(),
        body_text=_email_body_text(email),
    )
