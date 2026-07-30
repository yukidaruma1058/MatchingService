"""人材メールのスキルシートを共有ドライブへ保存する。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.drive_client import XLSX_MIME, DriveClient
from app.gmail_client import GmailClient, GmailConfigError
from app.logging_util import log_error_event, log_event
from app.models import Company, Talent, TalentSkillSheet
from app.skill_sheet_extract import extract_and_apply_to_row
from app.skill_sheet_names import (
    attachment_source_hint,
    company_folder_name,
    drive_storage_filename,
    extension_from_filename_or_mime,
    extract_spreadsheet_ids,
    is_skill_sheet_attachment,
    spreadsheet_drive_filename,
)


@dataclass
class GmailAttachmentMeta:
    attachment_id: str
    filename: str
    mime_type: str
    size: int = 0


def list_message_attachments(client: GmailClient, message_id: str) -> list[GmailAttachmentMeta]:
    """Gmail メッセージの添付メタを列挙する。"""
    try:
        raw = client.service.users().messages().get(userId="me", id=message_id, format="full").execute()
    except Exception as exc:  # noqa: BLE001
        raise GmailConfigError("ERR-0021", f"Failed to fetch message for attachments: {message_id}") from exc

    found: list[GmailAttachmentMeta] = []

    def walk(part: dict[str, Any]) -> None:
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        filename = (part.get("filename") or "").strip()
        mime_type = (part.get("mimeType") or "").strip()
        if attachment_id and filename:
            found.append(
                GmailAttachmentMeta(
                    attachment_id=str(attachment_id),
                    filename=filename,
                    mime_type=mime_type,
                    size=int(body.get("size") or 0),
                )
            )
        for child in part.get("parts") or []:
            walk(child)

    walk(raw.get("payload") or {})
    return found


def download_gmail_attachment(client: GmailClient, message_id: str, attachment_id: str) -> bytes:
    try:
        result = (
            client.service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise GmailConfigError("ERR-0021", f"Failed to download attachment: {attachment_id}") from exc
    import base64

    data = result.get("data") or ""
    return base64.urlsafe_b64decode(data + "==")


def resolve_talent_company_name(session: Session, talent: Talent) -> str:
    if talent.introducer_company_id:
        company = session.get(Company, talent.introducer_company_id)
        if company and (company.name or "").strip():
            return company.name.strip()
    return (talent.source_company_name or "").strip() or "未設定"


def _upsert_sheet_row(
    session: Session,
    *,
    talent_id: UUID,
    email_id: UUID,
    source_type: str,
    source_url: str | None,
    original_attachment_id: str | None,
) -> TalentSkillSheet:
    query = select(TalentSkillSheet).where(TalentSkillSheet.talent_id == talent_id)
    if original_attachment_id:
        existing = session.scalar(query.where(TalentSkillSheet.original_attachment_id == original_attachment_id))
    elif source_url:
        existing = session.scalar(query.where(TalentSkillSheet.source_url == source_url))
    else:
        existing = None
    if existing is not None:
        return existing
    row = TalentSkillSheet(
        id=uuid.uuid4(),
        talent_id=talent_id,
        email_id=email_id,
        source_type=source_type,
        source_url=source_url,
        original_attachment_id=original_attachment_id,
        filename="",
        access_status="failed",
        created_at=datetime.now().astimezone(),
        updated_at=datetime.now().astimezone(),
    )
    session.add(row)
    session.flush()
    return row


def _save_bytes_to_drive(
    drive: DriveClient,
    *,
    folder_id: str,
    filename: str,
    mime_type: str,
    data: bytes,
    existing_file_id: str | None,
) -> dict[str, Any]:
    if existing_file_id:
        try:
            return drive.update_file_media(existing_file_id, mime_type=mime_type, data=data)
        except GmailConfigError:
            pass
    found = drive.find_file_in_folder(folder_id, filename)
    if found:
        return drive.update_file_media(found, mime_type=mime_type, data=data)
    return drive.upload_file(folder_id, name=filename, mime_type=mime_type, data=data)


def ingest_talent_skill_sheets(
    *,
    session: Session,
    gmail: GmailClient,
    talent: Talent,
    gmail_message_id: str,
    body_text: str | None,
    body_html: str | None,
    root_folder_id: str,
    logger: logging.Logger,
    job_id: str,
) -> int:
    """人材のスキルシート候補を共有ドライブへ保存する。戻り値は処理件数。"""
    folder_id_setting = (root_folder_id or "").strip()
    if not folder_id_setting:
        log_event(
            logger,
            logging.WARNING,
            event="gmail_ingest.skill_sheet_skipped",
            message="skill_sheet_drive_folder_id is empty; skip skill sheet ingest",
            operation="スキルシート保存",
            method_name="ingest_talent_skill_sheets",
            job_id=job_id,
            function_id="BAT-002",
            extra={"talent_id": str(talent.id)},
        )
        return 0

    drive = DriveClient(str(gmail.credentials_path), str(gmail.token_path))
    try:
        drive.connect()
    except GmailConfigError as exc:
        log_error_event(
            logger,
            event="gmail_ingest.skill_sheet_drive_unavailable",
            error_code=exc.error_code,
            detail=exc.message,
            operation="スキルシート Drive接続",
            method_name="ingest_talent_skill_sheets",
            job_id=job_id,
            function_id="BAT-002",
        )
        return 0

    company = company_folder_name(resolve_talent_company_name(session, talent))
    try:
        company_folder_id = drive.ensure_skill_sheet_company_folder(folder_id_setting, company)
    except GmailConfigError as exc:
        log_error_event(
            logger,
            event="gmail_ingest.skill_sheet_folder_failed",
            error_code=exc.error_code,
            detail=exc.message,
            operation="スキルシートフォルダ作成",
            method_name="ingest_talent_skill_sheets",
            job_id=job_id,
            function_id="BAT-002",
        )
        return 0

    processed = 0
    try:
        attachments = list_message_attachments(gmail, gmail_message_id)
    except GmailConfigError as exc:
        log_error_event(
            logger,
            event="gmail_ingest.skill_sheet_list_failed",
            error_code=exc.error_code,
            detail=exc.message,
            operation="スキルシート添付一覧",
            method_name="ingest_talent_skill_sheets",
            job_id=job_id,
            function_id="BAT-002",
        )
        attachments = []

    for att in attachments:
        if not is_skill_sheet_attachment(filename=att.filename, mime_type=att.mime_type):
            continue
        processed += 1
        row = _upsert_sheet_row(
            session,
            talent_id=talent.id,
            email_id=talent.email_id,
            source_type="gmail_attachment",
            source_url=None,
            original_attachment_id=att.attachment_id,
        )
        ext = extension_from_filename_or_mime(att.filename, att.mime_type)
        filename = drive_storage_filename(
            display_name=talent.display_name,
            talent_id=talent.id,
            source_hint=attachment_source_hint(att.filename),
            ext=ext,
        )
        try:
            data = download_gmail_attachment(gmail, gmail_message_id, att.attachment_id)
            mime = att.mime_type or "application/octet-stream"
            uploaded = _save_bytes_to_drive(
                drive,
                folder_id=company_folder_id,
                filename=filename,
                mime_type=mime,
                data=data,
                existing_file_id=row.drive_file_id,
            )
            row.drive_file_id = str(uploaded.get("id") or "")
            row.drive_folder_id = company_folder_id
            row.filename = filename
            row.content_type = mime
            row.size_bytes = len(data)
            row.access_status = "ok"
            row.error_message = None
            row.web_view_link = uploaded.get("webViewLink") or drive.get_web_view_link(row.drive_file_id)
            row.updated_at = datetime.now().astimezone()
            try:
                extract_and_apply_to_row(row, data)
            except Exception:  # noqa: BLE001 — 取込成功は維持
                pass
        except Exception as exc:  # noqa: BLE001
            row.access_status = "failed"
            row.error_message = str(exc)[:500]
            row.filename = filename
            row.updated_at = datetime.now().astimezone()
            log_error_event(
                logger,
                event="gmail_ingest.skill_sheet_attachment_failed",
                error_code="ERR-0021",
                detail=str(exc),
                operation="スキルシート添付保存",
                method_name="ingest_talent_skill_sheets",
                job_id=job_id,
                function_id="BAT-002",
                gmail_message_id=gmail_message_id,
            )

    for sheet_id in extract_spreadsheet_ids(body_text, body_html):
        processed += 1
        source_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        row = _upsert_sheet_row(
            session,
            talent_id=talent.id,
            email_id=talent.email_id,
            source_type="google_sheet",
            source_url=source_url,
            original_attachment_id=None,
        )
        filename = spreadsheet_drive_filename(display_name=talent.display_name, talent_id=talent.id)
        try:
            data = drive.export_spreadsheet_xlsx(sheet_id)
            uploaded = _save_bytes_to_drive(
                drive,
                folder_id=company_folder_id,
                filename=filename,
                mime_type=XLSX_MIME,
                data=data,
                existing_file_id=row.drive_file_id,
            )
            row.drive_file_id = str(uploaded.get("id") or "")
            row.drive_folder_id = company_folder_id
            row.filename = filename
            row.content_type = XLSX_MIME
            row.size_bytes = len(data)
            row.access_status = "ok"
            row.error_message = None
            row.web_view_link = uploaded.get("webViewLink") or drive.get_web_view_link(row.drive_file_id)
            row.updated_at = datetime.now().astimezone()
            try:
                extract_and_apply_to_row(row, data)
            except Exception:  # noqa: BLE001
                pass
        except GmailConfigError as exc:
            status = "need_access" if "need_access" in (exc.message or "") else "failed"
            row.access_status = status
            row.error_message = exc.message[:500]
            row.filename = filename
            row.source_url = source_url
            row.updated_at = datetime.now().astimezone()
            log_error_event(
                logger,
                event="gmail_ingest.skill_sheet_spreadsheet_failed",
                error_code=exc.error_code,
                detail=exc.message,
                operation="スキルシートSheets保存",
                method_name="ingest_talent_skill_sheets",
                job_id=job_id,
                function_id="BAT-002",
            )
        except Exception as exc:  # noqa: BLE001
            row.access_status = "failed"
            row.error_message = str(exc)[:500]
            row.filename = filename
            row.updated_at = datetime.now().astimezone()

    return processed
