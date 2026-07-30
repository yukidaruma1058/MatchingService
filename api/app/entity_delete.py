"""人材・案件の関連データ一括削除。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import (
    Company,
    Contact,
    Email,
    Match,
    OutreachMessage,
    OutreachMessageTalent,
    OutreachReply,
    Project,
    Talent,
    TalentSkillSheet,
)
from app.config import settings as app_settings
from app.drive_client import DriveClient
from app.gmail_client import GmailConfigError


def _delete_outreach_message(session: Session, message_id: UUID) -> None:
    session.execute(delete(OutreachReply).where(OutreachReply.outreach_message_id == message_id))
    session.execute(
        delete(OutreachMessageTalent).where(OutreachMessageTalent.outreach_message_id == message_id)
    )
    session.execute(delete(OutreachMessage).where(OutreachMessage.id == message_id))


def delete_talent_cascade(session: Session, talent_id: UUID) -> dict[str, int]:
    """人材と、マッチ・提案・返信・取込元メールを削除する。"""
    talent = session.get(Talent, talent_id)
    if talent is None:
        raise LookupError("talent_not_found")

    email_id = talent.email_id
    match_ids = list(session.scalars(select(Match.id).where(Match.talent_id == talent_id)).all())

    # 案件提案（人材紹介メールへ）: この人材に紐づくメッセージを削除
    talent_proposal_filters = [OutreachMessage.talent_id == talent_id]
    if match_ids:
        talent_proposal_filters.append(OutreachMessage.match_id.in_(match_ids))
    talent_proposal_ids = list(
        session.scalars(
            select(OutreachMessage.id).where(
                OutreachMessage.kind == "talent_proposal",
                or_(*talent_proposal_filters),
            )
        ).all()
    )
    for message_id in talent_proposal_ids:
        _delete_outreach_message(session, message_id)

    # 人材提案（案件配信元へ）: リンクを外し、他要員がいなければメッセージごと削除
    linked_message_ids = list(
        session.scalars(
            select(OutreachMessageTalent.outreach_message_id).where(
                OutreachMessageTalent.talent_id == talent_id
            )
        ).all()
    )
    session.execute(
        delete(OutreachMessageTalent).where(OutreachMessageTalent.talent_id == talent_id)
    )
    orphan_project_proposals = 0
    for message_id in linked_message_ids:
        remaining = session.scalar(
            select(func.count())
            .select_from(OutreachMessageTalent)
            .where(OutreachMessageTalent.outreach_message_id == message_id)
        )
        if int(remaining or 0) == 0:
            _delete_outreach_message(session, message_id)
            orphan_project_proposals += 1

    deleted_matches = session.execute(delete(Match).where(Match.talent_id == talent_id)).rowcount or 0

    sheet_rows = list(
        session.scalars(select(TalentSkillSheet).where(TalentSkillSheet.talent_id == talent_id)).all()
    )
    drive_ids = [row.drive_file_id for row in sheet_rows if row.drive_file_id]
    session.execute(delete(TalentSkillSheet).where(TalentSkillSheet.talent_id == talent_id))

    session.delete(talent)
    session.flush()

    deleted_email = 0
    email = session.get(Email, email_id)
    if email is not None:
        session.delete(email)
        deleted_email = 1

    session.commit()

    if drive_ids:
        try:
            drive = DriveClient(str(app_settings.gmail_credentials_path), str(app_settings.gmail_token_path))
            drive.connect()
            for file_id in drive_ids:
                try:
                    drive.delete_file(file_id)
                except GmailConfigError:
                    continue
        except Exception:  # noqa: BLE001
            pass

    return {
        "talent": 1,
        "matches": int(deleted_matches),
        "talent_proposals": len(talent_proposal_ids),
        "project_proposal_messages": orphan_project_proposals,
        "email": deleted_email,
        "skill_sheets": len(sheet_rows),
    }


def delete_project_cascade(session: Session, project_id: UUID) -> dict[str, int]:
    """案件と、マッチ・提案・返信・取込元メールを削除する。"""
    project = session.get(Project, project_id)
    if project is None:
        raise LookupError("project_not_found")

    email_id = project.email_id
    match_ids = list(session.scalars(select(Match.id).where(Match.project_id == project_id)).all())

    # この案件の人材提案メッセージ
    project_proposal_ids = list(
        session.scalars(
            select(OutreachMessage.id).where(
                OutreachMessage.kind == "project_proposal",
                OutreachMessage.project_id == project_id,
            )
        ).all()
    )
    for message_id in project_proposal_ids:
        _delete_outreach_message(session, message_id)

    # 案件提案（人材側）でこの案件に紐づくもの
    talent_proposal_filters = [OutreachMessage.project_id == project_id]
    if match_ids:
        talent_proposal_filters.append(OutreachMessage.match_id.in_(match_ids))
    talent_proposal_ids = list(
        session.scalars(
            select(OutreachMessage.id).where(
                OutreachMessage.kind == "talent_proposal",
                or_(*talent_proposal_filters),
            )
        ).all()
    )
    for message_id in talent_proposal_ids:
        _delete_outreach_message(session, message_id)

    deleted_matches = session.execute(delete(Match).where(Match.project_id == project_id)).rowcount or 0
    session.delete(project)
    session.flush()

    deleted_email = 0
    email = session.get(Email, email_id)
    if email is not None:
        session.delete(email)
        deleted_email = 1

    session.commit()
    return {
        "project": 1,
        "matches": int(deleted_matches),
        "project_proposals": len(project_proposal_ids),
        "talent_proposals": len(talent_proposal_ids),
        "email": deleted_email,
    }


def delete_company_cascade(session: Session, company_id: UUID) -> dict[str, int]:
    """企業と担当者を削除し、人材・案件・メールからの参照を外す。"""
    company = session.get(Company, company_id)
    if company is None:
        raise LookupError("company_not_found")

    deleted_contacts = session.execute(
        delete(Contact).where(Contact.company_id == company_id)
    ).rowcount or 0

    cleared_talents = session.execute(
        update(Talent)
        .where(Talent.introducer_company_id == company_id)
        .values(introducer_company_id=None)
    ).rowcount or 0
    cleared_projects = session.execute(
        update(Project)
        .where(Project.distributor_company_id == company_id)
        .values(distributor_company_id=None)
    ).rowcount or 0
    cleared_emails = session.execute(
        update(Email)
        .where(Email.source_company_id == company_id)
        .values(source_company_id=None)
    ).rowcount or 0

    session.delete(company)
    session.commit()
    return {
        "company": 1,
        "contacts": int(deleted_contacts),
        "cleared_talents": int(cleared_talents),
        "cleared_projects": int(cleared_projects),
        "cleared_emails": int(cleared_emails),
    }
