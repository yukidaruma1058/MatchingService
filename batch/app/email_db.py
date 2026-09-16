"""メール関連の DB アクセス（BAT-001 / BAT-002 共通）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Email, Project, SystemSetting, Talent
from app.ingest_dedup import find_project_by_business_key, find_talent_by_business_key
from app.skill_catalog import ensure_skills_in_master


def load_all_settings(session: Session) -> dict[str, object]:
    return {row.key: row.value for row in session.scalars(select(SystemSetting)).all()}


def already_ingested_gmail_ids(
    session: Session,
    gmail_message_ids: Iterable[str],
    *,
    retry_failed: bool = True,
) -> set[str]:
    """取込済みとみなす gmail_message_id 集合を返す。

    retry_failed=True のとき status=failed は含まない（再取込対象）。
    """
    ids = [mid.strip() for mid in gmail_message_ids if (mid or "").strip()]
    if not ids:
        return set()
    stmt = select(Email.gmail_message_id, Email.status).where(Email.gmail_message_id.in_(ids))
    out: set[str] = set()
    for gmail_id, status in session.execute(stmt).all():
        if retry_failed and status == "failed":
            continue
        out.add(str(gmail_id))
    return out


def upsert_sorted_email(
    session: Session,
    *,
    gmail_message_id: str,
    thread_id: str | None,
    label: str,
    from_address: str,
    subject: str,
    received_at: datetime,
    body_text: str | None,
    body_html: str | None,
    email_type: str,
    cc_addresses: list[str] | None = None,
) -> None:
    """メールを emails テーブルへ upsert する。"""
    now = datetime.now().astimezone()
    cc_list = list(cc_addresses or [])
    stmt = insert(Email).values(
        id=uuid4(),
        gmail_message_id=gmail_message_id,
        thread_id=thread_id,
        label=label,
        from_address=from_address,
        subject=subject,
        received_at=received_at,
        body_text=body_text,
        body_html=body_html,
        email_type=email_type,
        status="pending",
        cc_addresses=cc_list,
        created_at=now,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Email.gmail_message_id],
        set_={
            "label": label,
            "email_type": email_type,
            "updated_at": now,
            "thread_id": thread_id,
            "from_address": from_address,
            "subject": subject,
            "received_at": received_at,
            "body_text": body_text,
            "body_html": body_html,
            "cc_addresses": cc_list,
        },
    )
    session.execute(stmt)


def get_email_by_gmail_id(session: Session, gmail_message_id: str) -> Email | None:
    return session.scalar(select(Email).where(Email.gmail_message_id == gmail_message_id))


def mark_email_status(
    session: Session,
    *,
    gmail_message_id: str,
    status: str,
    label: str | None = None,
    body_text: str | None = None,
    body_html: str | None = None,
) -> None:
    now = datetime.now().astimezone()
    values: dict[str, Any] = {"status": status, "updated_at": now}
    if label is not None:
        values["label"] = label
    if body_text is not None:
        values["body_text"] = body_text
    if body_html is not None:
        values["body_html"] = body_html
    stmt = update(Email).where(Email.gmail_message_id == gmail_message_id).values(**values)
    session.execute(stmt)


def mark_email_summarized(
    session: Session,
    *,
    gmail_message_id: str,
    label: str,
    body_text: str | None,
    body_html: str | None,
) -> None:
    mark_email_status(
        session,
        gmail_message_id=gmail_message_id,
        status="summarized",
        label=label,
        body_text=body_text,
        body_html=body_html,
    )


def upsert_talent_from_email(
    session: Session,
    *,
    email_id: UUID,
    data: dict[str, Any],
    status: str = "active",
) -> UUID:
    now = datetime.now().astimezone()
    skills = ensure_skills_in_master(session, data.get("skills") or [])
    proposal_cc = list(data.get("proposal_cc_emails") or [])
    source_company_name = data.get("source_company_name")

    existing = find_talent_by_business_key(
        session,
        display_name=data["display_name"],
        source_company_name=source_company_name,
        nearest_station=data.get("nearest_station"),
    )
    if existing is not None:
        existing.email_id = email_id
        existing.display_name = data["display_name"]
        existing.affiliation = data.get("affiliation")
        existing.age = data.get("age")
        existing.gender = data.get("gender")
        existing.experience_years = data.get("experience_years")
        existing.desired_rate = data.get("desired_rate")
        existing.available_from = data.get("available_from")
        existing.work_style = data.get("work_style")
        existing.nearest_station = data.get("nearest_station")
        existing.is_foreign_national = data.get("is_foreign_national")
        existing.commerce_flow = data.get("commerce_flow")
        existing.skills = skills
        existing.source_company_name = source_company_name
        existing.summary = data.get("summary")
        existing.proposal_cc_emails = proposal_cc
        existing.status = status
        existing.updated_at = now
        session.flush()
        return existing.id

    talent_id = uuid4()
    session.add(
        Talent(
            id=talent_id,
            email_id=email_id,
            display_name=data["display_name"],
            affiliation=data.get("affiliation"),
            age=data.get("age"),
            gender=data.get("gender"),
            experience_years=data.get("experience_years"),
            desired_rate=data.get("desired_rate"),
            available_from=data.get("available_from"),
            work_style=data.get("work_style"),
            nearest_station=data.get("nearest_station"),
            is_foreign_national=data.get("is_foreign_national"),
            commerce_flow=data.get("commerce_flow"),
            skills=skills,
            source_company_name=source_company_name,
            summary=data.get("summary"),
            proposal_cc_emails=proposal_cc,
            status=status,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    return talent_id


def upsert_project_from_email(
    session: Session,
    *,
    email_id: UUID,
    data: dict[str, Any],
    status: str = "open",
) -> UUID:
    now = datetime.now().astimezone()
    required_skills = ensure_skills_in_master(session, data.get("required_skills") or [])
    preferred_skills = ensure_skills_in_master(session, data.get("preferred_skills") or [])
    proposal_cc = list(data.get("proposal_cc_emails") or [])
    source_company_name = data.get("source_company_name")

    existing = find_project_by_business_key(
        session,
        title=data["title"],
        source_company_name=source_company_name,
    )
    if existing is not None:
        existing.email_id = email_id
        existing.project_code = data.get("project_code")
        existing.title = data["title"]
        existing.required_skills = required_skills
        existing.preferred_skills = preferred_skills
        existing.rate_min = data.get("rate_min")
        existing.rate_max = data.get("rate_max")
        existing.location = data.get("location")
        existing.work_style = data.get("work_style")
        existing.working_hours = data.get("working_hours")
        existing.start_date = data.get("start_date")
        existing.foreign_nationality_ng = data.get("foreign_nationality_ng")
        existing.commerce_flow_limit = data.get("commerce_flow_limit")
        existing.settlement_range = data.get("settlement_range")
        existing.interview_count = data.get("interview_count")
        existing.headcount = data.get("headcount")
        existing.summary = data.get("summary")
        existing.proposal_cc_emails = proposal_cc
        existing.source_company_name = source_company_name
        existing.status = status
        existing.updated_at = now
        session.flush()
        return existing.id

    project_id = uuid4()
    session.add(
        Project(
            id=project_id,
            email_id=email_id,
            project_code=data.get("project_code"),
            title=data["title"],
            required_skills=required_skills,
            preferred_skills=preferred_skills,
            rate_min=data.get("rate_min"),
            rate_max=data.get("rate_max"),
            location=data.get("location"),
            work_style=data.get("work_style"),
            working_hours=data.get("working_hours"),
            start_date=data.get("start_date"),
            foreign_nationality_ng=data.get("foreign_nationality_ng"),
            commerce_flow_limit=data.get("commerce_flow_limit"),
            settlement_range=data.get("settlement_range"),
            interview_count=data.get("interview_count"),
            headcount=data.get("headcount"),
            summary=data.get("summary"),
            proposal_cc_emails=proposal_cc,
            source_company_name=source_company_name,
            status=status,
            created_at=now,
            updated_at=now,
        )
    )
    session.flush()
    return project_id
