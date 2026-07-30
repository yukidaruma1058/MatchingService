"""BAT-006: 取込データ保持期間に基づく削除処理の DB アクセス。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from sqlalchemy.sql import Select

from retention import coerce_non_negative_int

from app.config import Settings, settings as app_settings
from app.models import (
    Email,
    OutreachMessage,
    OutreachMessageTalent,
    Project,
    SystemSetting,
    Talent,
    TalentSkillSheet,
)
from app.drive_client import DriveClient
from app.gmail_client import GmailConfigError

SETTING_KEY_INGEST_RETENTION_DAYS = "ingest_data_retention_days"

# 後方互換エイリアス
_coerce_non_negative_int = coerce_non_negative_int


def load_retention_days(session: Session, cfg: Settings) -> int:
    """取込データ保持日数を読み込む。

    優先順位: system_settings > 環境変数（Settings）> 0（削除しない）。
    """
    row = session.scalar(
        select(SystemSetting).where(SystemSetting.key == SETTING_KEY_INGEST_RETENTION_DAYS)
    )
    if row is not None:
        return coerce_non_negative_int(row.value, cfg.ingest_data_retention_days)
    return max(cfg.ingest_data_retention_days, 0)


def protected_email_ids_subquery() -> Select:
    """送信済み提案に紐づく取込メール ID（削除対象外）。

    - 人材提案（talent_proposal）の talent / 返信元メール
    - 要員提案（project_proposal）の project / 含めた talent / 返信元メール
    """
    sent = OutreachMessage.status == "sent"

    talent_ids_direct = select(OutreachMessage.talent_id).where(
        sent,
        OutreachMessage.talent_id.is_not(None),
    )
    talent_ids_linked = (
        select(OutreachMessageTalent.talent_id)
        .select_from(OutreachMessageTalent)
        .join(
            OutreachMessage,
            OutreachMessage.id == OutreachMessageTalent.outreach_message_id,
        )
        .where(sent)
    )
    talent_ids = talent_ids_direct.union(talent_ids_linked)

    project_ids = select(OutreachMessage.project_id).where(
        sent,
        OutreachMessage.project_id.is_not(None),
    )

    from_talent = select(Talent.email_id).where(Talent.id.in_(talent_ids))
    from_project = select(Project.email_id).where(Project.id.in_(project_ids))
    from_reply_to = select(OutreachMessage.in_reply_to_email_id).where(
        sent,
        OutreachMessage.in_reply_to_email_id.is_not(None),
    )
    return from_talent.union(from_project, from_reply_to)


def delete_expired_ingest_data(session: Session, retention_days: int) -> dict[str, int]:
    """保持期間を超えた取込データを削除する。

    ``emails.created_at`` が基準日より古いレコードを削除する。
    ただし送信済み提案に紐づく人材・案件・返信元メールは対象外。
    talents / projects は email_id の ON DELETE CASCADE で連動削除される。
    retention_days が 0 以下の場合は何も削除せず件数 0 を返す。
    """
    empty = {
        "emails": 0,
        "talents": 0,
        "projects": 0,
        "skipped_protected": 0,
    }
    if retention_days <= 0:
        return empty

    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    protected_ids = protected_email_ids_subquery()

    expired_deletable = select(Email.id).where(
        Email.created_at < cutoff,
        ~Email.id.in_(protected_ids),
    )

    skipped_protected = (
        session.scalar(
            select(func.count())
            .select_from(Email)
            .where(Email.created_at < cutoff, Email.id.in_(protected_ids))
        )
        or 0
    )

    talent_count = (
        session.scalar(
            select(func.count()).select_from(Talent).where(Talent.email_id.in_(expired_deletable))
        )
        or 0
    )
    project_count = (
        session.scalar(
            select(func.count()).select_from(Project).where(Project.email_id.in_(expired_deletable))
        )
        or 0
    )

    # 削除対象 talent の Drive スキルシートを先に掃除
    talent_ids = list(
        session.scalars(select(Talent.id).where(Talent.email_id.in_(expired_deletable))).all()
    )
    if talent_ids:
        sheets = list(
            session.scalars(
                select(TalentSkillSheet).where(TalentSkillSheet.talent_id.in_(talent_ids))
            ).all()
        )
        drive_ids = [s.drive_file_id for s in sheets if s.drive_file_id]
        session.execute(delete(TalentSkillSheet).where(TalentSkillSheet.talent_id.in_(talent_ids)))
        if drive_ids:
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

    result = session.execute(
        delete(Email).where(Email.created_at < cutoff, ~Email.id.in_(protected_ids))
    )
    email_count = result.rowcount or 0
    return {
        "emails": email_count,
        "talents": int(talent_count),
        "projects": int(project_count),
        "skipped_protected": int(skipped_protected),
    }
