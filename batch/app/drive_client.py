"""Google Drive クライアント（共有ドライブ対応・スキルシート保存用）。"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from app.gmail_client import GMAIL_SCOPES, GmailConfigError

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FOLDER_MIME = "application/vnd.google-apps.folder"
SKILL_SHEET_ROOT_NAME = "スキルシート"


class DriveClient:
    """Drive API の薄いラッパー（共有ドライブ対応）。"""

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self._service = None

    def connect(self) -> None:
        if not self.credentials_path.exists():
            raise GmailConfigError("ERR-0018", "Gmail credentials file not found")
        if not self.token_path.exists():
            raise GmailConfigError("ERR-0018", "Gmail token file not found")

        creds = Credentials.from_authorized_user_file(str(self.token_path), GMAIL_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_path.write_text(creds.to_json())
            else:
                raise GmailConfigError("ERR-0019", "Gmail token is invalid or expired")

        # Drive スコープがトークンに無い場合は明確に失敗させる
        granted = set(creds.scopes or [])
        if "https://www.googleapis.com/auth/drive" not in granted and "https://www.googleapis.com/auth/drive.file" not in granted:
            raise GmailConfigError(
                "ERR-0019",
                "Drive scope missing; reconnect Gmail OAuth to grant drive access",
            )

        self._service = build("drive", "v3", credentials=creds, cache_discovery=False)

    @property
    def service(self):
        if self._service is None:
            raise RuntimeError("Drive client is not connected")
        return self._service

    def ensure_child_folder(self, parent_id: str, name: str) -> str:
        """親配下に同名フォルダがあればその ID、無ければ作成して返す。"""
        safe_name = (name or "").strip() or "folder"
        query = (
            f"name = '{safe_name.replace(chr(39), chr(92) + chr(39))}' "
            f"and mimeType = '{FOLDER_MIME}' "
            f"and '{parent_id}' in parents "
            f"and trashed = false"
        )
        try:
            result = (
                self.service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(id, name)",
                    pageSize=10,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                )
                .execute()
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to list Drive folder: {safe_name}") from exc

        files = result.get("files") or []
        if files:
            return str(files[0]["id"])

        metadata = {
            "name": safe_name,
            "mimeType": FOLDER_MIME,
            "parents": [parent_id],
        }
        try:
            created = (
                self.service.files()
                .create(body=metadata, fields="id", supportsAllDrives=True)
                .execute()
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to create Drive folder: {safe_name}") from exc
        return str(created["id"])

    def ensure_skill_sheet_company_folder(self, root_folder_id: str, company_name: str) -> str:
        """root/スキルシート/{会社名} を ensure して会社フォルダ ID を返す。"""
        skill_root = self.ensure_child_folder(root_folder_id, SKILL_SHEET_ROOT_NAME)
        return self.ensure_child_folder(skill_root, company_name)

    def upload_file(
        self,
        folder_id: str,
        *,
        name: str,
        mime_type: str,
        data: bytes,
    ) -> dict[str, Any]:
        """フォルダへファイルを作成（同名があれば新規作成で増える。呼び出し側で upsert 制御）。"""
        metadata = {"name": name, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type or "application/octet-stream", resumable=False)
        try:
            created = (
                self.service.files()
                .create(
                    body=metadata,
                    media_body=media,
                    fields="id, name, mimeType, size, webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to upload Drive file: {name}") from exc
        return created

    def update_file_media(self, file_id: str, *, mime_type: str, data: bytes) -> dict[str, Any]:
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type or "application/octet-stream", resumable=False)
        try:
            updated = (
                self.service.files()
                .update(
                    fileId=file_id,
                    media_body=media,
                    fields="id, name, mimeType, size, webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to update Drive file: {file_id}") from exc
        return updated

    def find_file_in_folder(self, folder_id: str, name: str) -> str | None:
        safe_name = name.replace("'", "\\'")
        query = f"name = '{safe_name}' and '{folder_id}' in parents and trashed = false"
        try:
            result = (
                self.service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="files(id, name)",
                    pageSize=5,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                )
                .execute()
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to find Drive file: {name}") from exc
        files = result.get("files") or []
        if not files:
            return None
        return str(files[0]["id"])

    def export_spreadsheet_xlsx(self, file_id: str) -> bytes:
        try:
            request = self.service.files().export_media(fileId=file_id, mimeType=XLSX_MIME)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buffer.getvalue()
        except HttpError as exc:
            status = getattr(exc, "status_code", None) or getattr(getattr(exc, "resp", None), "status", None)
            if status in (403, 404):
                raise GmailConfigError("ERR-0021", f"Cannot export spreadsheet (need_access): {file_id}") from exc
            raise GmailConfigError("ERR-0021", f"Failed to export spreadsheet: {file_id}") from exc

    def download_file(self, file_id: str) -> bytes:
        try:
            request = self.service.files().get_media(fileId=file_id, supportsAllDrives=True)
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            return buffer.getvalue()
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to download Drive file: {file_id}") from exc

    def get_web_view_link(self, file_id: str) -> str | None:
        try:
            meta = (
                self.service.files()
                .get(fileId=file_id, fields="webViewLink", supportsAllDrives=True)
                .execute()
            )
        except HttpError:
            return None
        link = meta.get("webViewLink")
        return str(link) if link else None

    def delete_file(self, file_id: str) -> None:
        try:
            self.service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
        except HttpError as exc:
            status = getattr(getattr(exc, "resp", None), "status", None)
            if status == 404:
                return
            raise GmailConfigError("ERR-0021", f"Failed to delete Drive file: {file_id}") from exc
