"""スキルシート経験テキストの取込・抽出（AI 採点時）。"""

from __future__ import annotations

import logging
import threading
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_concurrency import map_parallel
from app.drive_client import DriveClient
from app.email_db import load_all_settings
from app.gmail_client import GmailClient, GmailConfigError
from app.gmail_credentials import ensure_gmail_credentials_file
from app.models import Email, Talent, TalentSkillSheet
from app.skill_sheet_extract import (
    experience_text_for_prompt,
    extract_and_apply_to_row,
)
from app.skill_sheet_ingest import (
    SKILL_SHEET_CONCURRENCY,
    SkillSheetDriveContext,
    connect_skill_sheet_drive,
    ingest_talent_skill_sheets,
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
            from datetime import datetime

            row.experience_extract_status = "failed"
            row.experience_extracted_at = datetime.now().astimezone()
            return

    if payload is None:
        return

    extract_and_apply_to_row(row, payload)


def ensure_talent_skill_sheets_ingested(
    session: Session,
    talent: Talent,
    *,
    gmail: GmailClient,
    root_folder_id: str,
    logger: logging.Logger,
    job_id: str,
    drive_context: SkillSheetDriveContext | None = None,
    gmail_lock: threading.Lock | None = None,
) -> int:
    """未取込の人材について Gmail/Drive からスキルシートを取り込む。

    既に access_status=ok の行があればスキップ（0 を返す）。
    """
    if _latest_ok_sheet(session, talent.id) is not None:
        return 0
    email = session.get(Email, talent.email_id)
    if email is None:
        return 0
    gmail_message_id = (email.gmail_message_id or "").strip()
    if not gmail_message_id:
        return 0
    return ingest_talent_skill_sheets(
        session=session,
        gmail=gmail,
        talent=talent,
        gmail_message_id=gmail_message_id,
        body_text=email.body_text,
        body_html=email.body_html,
        root_folder_id=root_folder_id,
        logger=logger,
        job_id=job_id,
        drive_context=drive_context,
        gmail_lock=gmail_lock,
    )


def prepare_skill_sheets_for_talent_ids(
    *,
    session_factory,
    talent_ids: list[UUID],
    cfg: object,
    logger: logging.Logger,
    job_id: str,
) -> dict[str, int]:
    """AI 採点対象の人材についてスキルシートを一括取込する。

    Drive / Gmail 接続を共有し、SKILL_SHEET_CONCURRENCY で並列実行する。
    """
    unique_ids = list(dict.fromkeys(talent_ids))
    stats = {"talents": len(unique_ids), "ingested": 0, "skipped_existing": 0, "failed": 0}
    if not unique_ids:
        return stats

    credentials_path = str(getattr(cfg, "gmail_credentials_path", "") or "")
    token_path = str(getattr(cfg, "gmail_token_path", "") or "")

    with session_factory() as session:
        settings_map = load_all_settings(session)
        folder_id = str(settings_map.get("skill_sheet_drive_folder_id") or "").strip()
        try:
            ensure_gmail_credentials_file(cfg, settings_map)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            pass

    if not folder_id:
        logger.warning("skill_sheet_drive_folder_id is empty; skip skill sheet ingest at AI judge")
        return stats

    try:
        gmail = GmailClient(credentials_path, token_path)
        gmail.connect()
    except GmailConfigError as exc:
        logger.warning("Gmail unavailable for skill sheet ingest: %s", exc.message)
        return stats

    try:
        drive_context = connect_skill_sheet_drive(
            credentials_path=credentials_path,
            token_path=token_path,
            root_folder_id=folder_id,
        )
    except GmailConfigError as exc:
        logger.warning("Drive unavailable for skill sheet ingest: %s", exc.message)
        return stats

    gmail_lock = threading.Lock()
    counters_lock = threading.Lock()

    def _one(talent_id: UUID) -> None:
        with session_factory() as session:
            talent = session.get(Talent, talent_id)
            if talent is None:
                return
            try:
                with session.begin_nested():
                    if _latest_ok_sheet(session, talent_id) is not None:
                        with counters_lock:
                            stats["skipped_existing"] += 1
                        return
                    processed = ensure_talent_skill_sheets_ingested(
                        session,
                        talent,
                        gmail=gmail,
                        root_folder_id=folder_id,
                        logger=logger,
                        job_id=job_id,
                        drive_context=drive_context,
                        gmail_lock=gmail_lock,
                    )
                session.commit()
                with counters_lock:
                    if processed > 0:
                        stats["ingested"] += 1
                    else:
                        stats["skipped_existing"] += 1
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                with counters_lock:
                    stats["failed"] += 1
                logger.warning(
                    "skill sheet ingest at AI judge failed talent=%s detail=%s",
                    talent_id,
                    exc,
                )

    map_parallel(unique_ids, _one, concurrency=SKILL_SHEET_CONCURRENCY)
    return stats


def load_skill_sheet_experience(
    session: Session,
    talent_id: UUID,
    *,
    credentials_path: str,
    token_path: str,
    logger: logging.Logger | None = None,
    drive: DriveClient | None = None,
) -> str | None:
    """AI プロンプト用の経験抜粋。無ければ None（メール情報のみ）。

    取込自体は prepare_skill_sheets_for_talent_ids 側で先行実施する想定。
    ここでは ok 行のテキスト抽出のみ行う。
    """
    row = _latest_ok_sheet(session, talent_id)
    if row is None:
        return None

    if _needs_extraction(row) and row.drive_file_id:
        local_drive = drive
        if local_drive is None:
            try:
                local_drive = DriveClient(credentials_path, token_path)
                local_drive.connect()
            except GmailConfigError:
                local_drive = None
        ensure_sheet_experience_extracted(session, row, drive=local_drive, logger=logger)
        session.flush()

    if (row.experience_extract_status or "") != "ok":
        return None
    return experience_text_for_prompt(row.experience_text)
