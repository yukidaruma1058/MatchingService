"""画面からのタイトル+本文登録: AI 要約して人材/案件へ保存する（Gmail 非依存）。

環境変数:
  MANUAL_EMAIL_ID … 事前に作成済みの emails.id（UUID）
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from uuid import UUID

from app.company_contact_db import extract_email_address, link_company_contact_for_ingest
from app.config import settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.email_db import (
    mark_email_status,
    upsert_project_from_email,
    upsert_talent_from_email,
)
from app.logging_util import get_batch_logger, log_error_event, log_event
from app.models import Email
from summarizer import extract_email_fields

MANUAL_PROCESSED_LABEL = "手動登録（処理済み）"


@dataclass
class ManualRegisterResult:
    email_id: UUID
    email_type: str
    entity_id: UUID | None
    email_status: str
    needs_review: bool
    ok: bool
    error_message: str | None = None


def run_manual_register_batch() -> ManualRegisterResult:
    """MANUAL_EMAIL_ID のメールを AI 要約し、人材または案件へ登録する。"""
    logger = get_batch_logger()
    job_id = "manual_register"
    raw_id = (os.environ.get("MANUAL_EMAIL_ID") or "").strip()
    if not raw_id:
        raise ValueError("MANUAL_EMAIL_ID is required")

    email_id = UUID(raw_id)
    session_factory, engine = create_session_factory(settings.database_url)
    ensure_schema(engine)

    with session_factory() as session:
        email = session.get(Email, email_id)
        if email is None:
            raise ValueError(f"email not found: {email_id}")
        email_type = email.email_type
        if email_type not in {"talent", "project"}:
            raise ValueError(f"unsupported email_type: {email_type}")
        subject = email.subject or ""
        body = email.body_text or email.body_html or ""
        from_address = email.from_address or "manual@local"
        gmail_message_id = email.gmail_message_id

    log_event(
        logger,
        logging.INFO,
        event="manual_register.started",
        message="Manual register started",
        operation="手動登録・AI要約",
        method_name="run_manual_register_batch",
        job_id=job_id,
        function_id="BAT-002",
        module_name="BAT-002.manual_register",
        extra={"email_id": str(email_id), "email_type": email_type},
    )

    try:
        extraction = extract_email_fields(
            email_type,  # type: ignore[arg-type]
            subject,
            body,
            settings,
            from_header=from_address,
        )
    except Exception as exc:  # noqa: BLE001
        with session_factory() as session:
            mark_email_status(session, gmail_message_id=gmail_message_id, status="failed")
            session.commit()
        log_error_event(
            logger,
            event="manual_register.extract_failed",
            error_code="ERR-0025",
            detail=str(exc),
            operation="AI要約",
            method_name="extract_email_fields",
            job_id=job_id,
            function_id="BAT-002",
            module_name="BAT-002.manual_register",
        )
        return ManualRegisterResult(
            email_id=email_id,
            email_type=email_type,
            entity_id=None,
            email_status="failed",
            needs_review=False,
            ok=False,
            error_message=str(exc),
        )

    if extraction is None or not extraction.data:
        with session_factory() as session:
            mark_email_status(session, gmail_message_id=gmail_message_id, status="failed")
            session.commit()
        return ManualRegisterResult(
            email_id=email_id,
            email_type=email_type,
            entity_id=None,
            email_status="failed",
            needs_review=False,
            ok=False,
            error_message="AI extraction returned empty payload",
        )

    needs_review = bool(extraction.needs_review)
    email_status = "needs_review" if needs_review else "summarized"
    entity_data = dict(extraction.data)
    entity_data["proposal_cc_emails"] = []

    try:
        with session_factory() as session:
            email_row = session.get(Email, email_id)
            if email_row is None:
                raise RuntimeError("email row missing")

            if email_type == "talent":
                entity_id = upsert_talent_from_email(
                    session,
                    email_id=email_row.id,
                    data=entity_data,
                    status="inactive" if needs_review else "active",
                )
                link_company_contact_for_ingest(
                    session,
                    email_id=email_row.id,
                    email_type="talent",
                    company_name=extraction.data.get("source_company_name"),
                    contact_name=extraction.data.get("contact_name"),
                    contact_email=extract_email_address(from_address) or from_address,
                    from_header=from_address,
                    talent_id=entity_id,
                )
            else:
                entity_id = upsert_project_from_email(
                    session,
                    email_id=email_row.id,
                    data=entity_data,
                    status="closed" if needs_review else "open",
                )
                link_company_contact_for_ingest(
                    session,
                    email_id=email_row.id,
                    email_type="project",
                    company_name=extraction.data.get("source_company_name"),
                    contact_name=extraction.data.get("contact_name"),
                    contact_email=extract_email_address(from_address) or from_address,
                    from_header=from_address,
                    project_id=entity_id,
                )

            mark_email_status(
                session,
                gmail_message_id=gmail_message_id,
                status=email_status,
                label=MANUAL_PROCESSED_LABEL,
                body_text=body,
            )
            session.commit()
    except Exception as exc:  # noqa: BLE001
        with session_factory() as session:
            mark_email_status(session, gmail_message_id=gmail_message_id, status="failed")
            session.commit()
        log_error_event(
            logger,
            event="manual_register.persist_failed",
            error_code="ERR-0015",
            detail=str(exc),
            operation="DB保存",
            method_name="run_manual_register_batch",
            job_id=job_id,
            function_id="BAT-002",
            module_name="BAT-002.manual_register",
        )
        return ManualRegisterResult(
            email_id=email_id,
            email_type=email_type,
            entity_id=None,
            email_status="failed",
            needs_review=needs_review,
            ok=False,
            error_message=str(exc),
        )

    log_event(
        logger,
        logging.INFO,
        event="manual_register.finished",
        message="Manual register finished",
        operation="手動登録・AI要約",
        method_name="run_manual_register_batch",
        job_id=job_id,
        function_id="BAT-002",
        module_name="BAT-002.manual_register",
        extra={
            "email_id": str(email_id),
            "entity_id": str(entity_id),
            "email_status": email_status,
            "needs_review": needs_review,
        },
    )
    return ManualRegisterResult(
        email_id=email_id,
        email_type=email_type,
        entity_id=entity_id,
        email_status=email_status,
        needs_review=needs_review,
        ok=True,
    )
