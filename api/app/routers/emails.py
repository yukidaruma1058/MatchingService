"""メール取込状況 API。"""

from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import load_settings
from app.deps import get_db
from app.gmail_client import GmailClient, GmailConfigError
from app.gmail_credentials import ensure_gmail_credentials_file
from app.models import Email, Project, Talent
from app.schemas import EmailDetail, EmailListItem, EmailReclassifyRequest, EmailReclassifyResponse
from app.setting_keys import (
    DEFAULT_SETTINGS,
    SETTING_KEY_GMAIL_SORT_LABEL_PROJECT,
    SETTING_KEY_GMAIL_SORT_LABEL_TALENT,
    SETTING_KEY_GMAIL_SORT_SOURCE_LABEL,
    SETTING_KEY_GMAIL_SORT_UNKNOWN_LABEL,
)

router = APIRouter(prefix="/api/emails", tags=["emails"])


def _setting_str(raw: dict, key: str) -> str:
    value = raw.get(key, DEFAULT_SETTINGS.get(key, ""))
    if isinstance(value, str) and value.strip():
        return value.strip()
    fallback = DEFAULT_SETTINGS.get(key, "")
    return str(fallback).strip() if fallback is not None else ""


def _gmail_http_error(exc: GmailConfigError) -> HTTPException:
    message = exc.message
    if exc.error_code == "ERR-0020" and "Gmail label not found:" in message:
        raw = message.split("Gmail label not found:", 1)[1].strip()
        names = "、".join(f"「{part.strip()}」" for part in raw.split(",") if part.strip())
        message = f"Gmail ラベルが見つかりません: {names}" if names else "Gmail ラベルが見つかりません。"
    elif exc.error_code == "ERR-0018":
        message = "Gmail が連携されていません。"
    elif exc.error_code == "ERR-0019":
        message = "Gmail 認証の有効期限が切れています。再連携してください。"
    return HTTPException(
        status_code=500,
        detail={"error_code": exc.error_code, "error_message": message},
    )


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


@router.post("/{email_id}/reclassify", response_model=EmailReclassifyResponse)
def reclassify_unknown_email(
    email_id: str,
    body: EmailReclassifyRequest,
    session: Session = Depends(get_db),
) -> EmailReclassifyResponse:
    """判別不能メールを人材 / 案件ラベルへ手動で振り分ける。"""
    try:
        email_uuid = UUID(email_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Email not found") from exc

    email = session.get(Email, email_uuid)
    if email is None:
        raise HTTPException(status_code=404, detail="Email not found")

    raw = load_settings(session)
    unknown_label = _setting_str(raw, SETTING_KEY_GMAIL_SORT_UNKNOWN_LABEL)
    talent_label = _setting_str(raw, SETTING_KEY_GMAIL_SORT_LABEL_TALENT)
    project_label = _setting_str(raw, SETTING_KEY_GMAIL_SORT_LABEL_PROJECT)
    source_label = _setting_str(raw, SETTING_KEY_GMAIL_SORT_SOURCE_LABEL)

    is_unknown = email.email_type == "unknown" or email.label == unknown_label
    if not is_unknown:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "ERR-0030",
                "error_message": "判別不能メールのみ手動振り分けできます。",
            },
        )

    target_label = talent_label if body.email_type == "talent" else project_label
    remove_labels = [name for name in (unknown_label, source_label) if name and name != target_label]

    if not ensure_gmail_credentials_file(raw):
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-0018",
                "error_message": "Gmail が連携されていません。",
            },
        )

    client = GmailClient(str(settings.gmail_credentials_path), str(settings.gmail_token_path))
    try:
        client.connect()
        client.require_labels([target_label, *remove_labels])
        client.relabel_message(
            email.gmail_message_id,
            add_label_names=[target_label],
            remove_label_names=remove_labels,
        )
    except GmailConfigError as exc:
        raise _gmail_http_error(exc) from exc

    email.email_type = body.email_type
    email.label = target_label
    email.status = "pending"
    email.updated_at = datetime.now().astimezone()
    session.commit()

    kind_label = "人材" if body.email_type == "talent" else "案件"
    return EmailReclassifyResponse(
        id=str(email.id),
        email_type=email.email_type,
        label=email.label,
        status=email.status,
        message=f"{kind_label}へ振り分けました。「振り分け・取込・採点」で要約登録とルール採点まで実行できます。",
    )
