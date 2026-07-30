"""スキルシート経験テキストの DB キャッシュ読み書き（ingest / AI 採点）。"""

from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.drive_client import DriveClient
from app.gmail_client import GmailConfigError
from app.models import TalentSkillSheet
from app.skill_sheet_extract import (
    experience_text_for_prompt,
    extract_and_apply_to_row,
)


def _latest_ok_sheet(session: Session, talent_id: UUID) -> TalentSkillSheet | None:
    return session.scalar(
        select(TalentSkillSheet)
        .where(
            TalentSkillSheet.talent_id == talent_id,
            TalentSkillSheet.access_status == "ok",
        )
        .order_by(TalentSkillSheet.created_at.desc())
        .limit(1)
    )


def _needs_extraction(row: TalentSkillSheet) -> bool:
    status = (row.experience_extract_status or "").strip()
    if not status:
        return True
    if status == "failed":
        return True
    return row.experience_extracted_at is None


def ensure_sheet_experience_extracted(
    session: Session,
    row: TalentSkillSheet,
    *,
    data: bytes | None = None,
    drive: DriveClient | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """未抽出なら data または Drive から抽出して row を更新する。抽出済みなら何もしない。"""
    if not _needs_extraction(row):
        return

    payload = data
    if payload is None and row.drive_file_id and drive is not None:
        try:
            payload = drive.download_file(row.drive_file_id)
        except GmailConfigError:
            if logger is not None:
                logger.warning(
                    "skill_sheet experience download failed talent_sheet=%s",
                    row.id,
                )
            from datetime import datetime

            row.experience_extract_status = "failed"
            row.experience_extracted_at = datetime.now().astimezone()
            return
        except Exception:  # noqa: BLE001
            row.experience_extract_status = "failed"
            row.experience_extracted_at = datetime.now().astimezone()
            return

    if payload is None:
        return

    extract_and_apply_to_row(row, payload)


def load_skill_sheet_experience(
    session: Session,
    talent_id: UUID,
    *,
    credentials_path: str,
    token_path: str,
    logger: logging.Logger | None = None,
) -> str | None:
    """AI プロンプト用の経験抜粋。無ければ None（メール情報のみ）。"""
    row = _latest_ok_sheet(session, talent_id)
    if row is None:
        return None

    if _needs_extraction(row) and row.drive_file_id:
        drive: DriveClient | None = None
        try:
            drive = DriveClient(credentials_path, token_path)
            drive.connect()
        except GmailConfigError:
            drive = None
        ensure_sheet_experience_extracted(session, row, drive=drive, logger=logger)
        session.flush()

    if (row.experience_extract_status or "") != "ok":
        return None
    return experience_text_for_prompt(row.experience_text)
