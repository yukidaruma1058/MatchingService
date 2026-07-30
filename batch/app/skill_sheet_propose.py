"""要員提案メール用スキルシート添付の組み立て。"""

from __future__ import annotations

from collections import Counter
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.drive_client import DriveClient
from app.email_attachments import (
    PreparedAttachment,
    apply_attachment_size_limit,
)
from app.gmail_client import GmailConfigError
from app.models import Talent, TalentSkillSheet
from app.skill_sheet_names import extension_from_filename_or_mime, proposal_attachment_filename

__all__ = [
    "PreparedAttachment",
    "apply_attachment_size_limit",
    "load_ok_skill_sheets",
    "prepare_proposal_attachments",
]


def load_ok_skill_sheets(session: Session, talent_ids: list[UUID]) -> list[tuple[Talent, TalentSkillSheet]]:
    if not talent_ids:
        return []
    talents = {
        t.id: t
        for t in session.scalars(select(Talent).where(Talent.id.in_(talent_ids))).all()
    }
    sheets = list(
        session.scalars(
            select(TalentSkillSheet).where(
                TalentSkillSheet.talent_id.in_(talent_ids),
                TalentSkillSheet.access_status == "ok",
                TalentSkillSheet.drive_file_id.is_not(None),
            )
        ).all()
    )
    out: list[tuple[Talent, TalentSkillSheet]] = []
    for sheet in sheets:
        talent = talents.get(sheet.talent_id)
        if talent is None:
            continue
        out.append((talent, sheet))
    return out


def prepare_proposal_attachments(
    session: Session,
    *,
    talent_ids: list[UUID],
    drive: DriveClient,
) -> tuple[list[PreparedAttachment], list[str]]:
    """添付リストと、サイズ超過時に本文へ載せるリンク行を返す。"""
    pairs = load_ok_skill_sheets(session, talent_ids)
    prepared: list[PreparedAttachment] = []
    name_counts: Counter[str] = Counter()

    for talent, sheet in pairs:
        if not sheet.drive_file_id:
            continue
        try:
            data = drive.download_file(sheet.drive_file_id)
        except GmailConfigError:
            continue
        ext = extension_from_filename_or_mime(sheet.filename, sheet.content_type)
        base_name = proposal_attachment_filename(display_name=talent.display_name, ext=ext, index=1)
        name_counts[base_name] += 1
        index = name_counts[base_name]
        attach_name = proposal_attachment_filename(
            display_name=talent.display_name,
            ext=ext,
            index=index,
        )
        prepared.append(
            PreparedAttachment(
                filename=attach_name,
                content_type=sheet.content_type or "application/octet-stream",
                data=data,
                display_name=talent.display_name,
                web_view_link=sheet.web_view_link,
            )
        )

    return apply_attachment_size_limit(prepared)
