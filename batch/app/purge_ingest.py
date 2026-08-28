"""取込メールと、そこから生成された関連データをすべて削除する。"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.drive_client import DriveClient
from app.gmail_client import GmailConfigError
from app.models import (
    Email,
    Match,
    MatchRun,
    OutreachMessage,
    OutreachMessageTalent,
    OutreachReply,
    Project,
    Talent,
    TalentSkillSheet,
)


def purge_all_ingest_data(
    session_factory: sessionmaker[Session] | None = None,
    *,
    cfg: Settings | None = None,
    skip_drive: bool = False,
) -> dict[str, int]:
    """取込メール・人材・案件・採点・提案データをすべて削除する（企業マスタ等は残す）。"""
    app_settings = cfg or settings
    if session_factory is None:
        session_factory, engine = create_session_factory(app_settings.database_url)
        ensure_schema(engine)

    with session_factory() as session:
        before = {
            "emails": session.scalar(select(func.count()).select_from(Email)) or 0,
            "talents": session.scalar(select(func.count()).select_from(Talent)) or 0,
            "projects": session.scalar(select(func.count()).select_from(Project)) or 0,
            "matches": session.scalar(select(func.count()).select_from(Match)) or 0,
            "match_runs": session.scalar(select(func.count()).select_from(MatchRun)) or 0,
            "outreach_messages": session.scalar(select(func.count()).select_from(OutreachMessage)) or 0,
            "outreach_replies": session.scalar(select(func.count()).select_from(OutreachReply)) or 0,
            "talent_skill_sheets": session.scalar(select(func.count()).select_from(TalentSkillSheet)) or 0,
        }

        drive_ids = list(
            session.scalars(
                select(TalentSkillSheet.drive_file_id).where(TalentSkillSheet.drive_file_id.is_not(None))
            ).all()
        )

        deleted_replies = session.execute(delete(OutreachReply)).rowcount or 0
        deleted_links = session.execute(delete(OutreachMessageTalent)).rowcount or 0
        deleted_outreach = session.execute(delete(OutreachMessage)).rowcount or 0
        deleted_matches = session.execute(delete(Match)).rowcount or 0
        deleted_match_runs = session.execute(delete(MatchRun)).rowcount or 0
        deleted_sheets = session.execute(delete(TalentSkillSheet)).rowcount or 0
        deleted_emails = session.execute(delete(Email)).rowcount or 0

        session.commit()

        after = {
            "emails": session.scalar(select(func.count()).select_from(Email)) or 0,
            "talents": session.scalar(select(func.count()).select_from(Talent)) or 0,
            "projects": session.scalar(select(func.count()).select_from(Project)) or 0,
        }

    if drive_ids and not skip_drive:
        try:
            drive = DriveClient(
                str(app_settings.gmail_credentials_path),
                str(app_settings.gmail_token_path),
            )
            drive.connect()
            for file_id in drive_ids:
                try:
                    drive.delete_file(file_id)
                except GmailConfigError:
                    continue
        except Exception:  # noqa: BLE001
            pass

    return {
        "before_emails": int(before["emails"]),
        "before_talents": int(before["talents"]),
        "before_projects": int(before["projects"]),
        "deleted_emails": int(deleted_emails),
        "deleted_talents": int(before["talents"]),
        "deleted_projects": int(before["projects"]),
        "deleted_matches": int(deleted_matches),
        "deleted_match_runs": int(deleted_match_runs),
        "deleted_outreach_messages": int(deleted_outreach),
        "deleted_outreach_replies": int(deleted_replies),
        "deleted_outreach_links": int(deleted_links),
        "deleted_talent_skill_sheets": int(deleted_sheets),
        "remaining_emails": int(after["emails"]),
        "remaining_talents": int(after["talents"]),
        "remaining_projects": int(after["projects"]),
        "drive_files_attempted": len(drive_ids),
    }
