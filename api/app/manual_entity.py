"""画面からの人材・案件の手動登録用ヘルパー。

talents / projects は email_id が必須のため、取込元のない手入力では
プレースホルダ emails 行を先に作成する。
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import Email

MANUAL_EMAIL_LABEL = "手動登録"


def create_manual_placeholder_email(
    session: Session,
    *,
    email_type: str,
    subject: str,
    body_text: str | None = None,
    from_address: str = "manual@local",
) -> Email:
    """手動登録用の emails 行を作成して返す（flush 済み）。"""
    now = datetime.now().astimezone()
    email_id = uuid4()
    row = Email(
        id=email_id,
        gmail_message_id=f"manual-{email_id}",
        thread_id=None,
        label=MANUAL_EMAIL_LABEL,
        from_address=(from_address or "manual@local").strip()[:255] or "manual@local",
        subject=(subject or "手動登録").strip() or "手動登録",
        received_at=now,
        body_text=(body_text.strip() if body_text and body_text.strip() else None),
        body_html=None,
        email_type=email_type,
        status="pending",
        source_company_id=None,
        cc_addresses=[],
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    session.flush()
    return row
