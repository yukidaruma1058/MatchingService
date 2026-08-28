"""スキルシート Drive 保存経路・フォルダキャッシュの単体テスト。"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))


class _GmailConfigError(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


def _install_import_stubs() -> None:
    """google / sqlalchemy 依存を避けて skill_sheet_ingest の純粋関数を検証する。"""
    gmail_mod = types.ModuleType("app.gmail_client")
    gmail_mod.GmailClient = object  # type: ignore[attr-defined]
    gmail_mod.GmailConfigError = _GmailConfigError  # type: ignore[attr-defined]
    sys.modules["app.gmail_client"] = gmail_mod

    drive_mod = types.ModuleType("app.drive_client")
    drive_mod.XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"  # type: ignore[attr-defined]
    drive_mod.SKILL_SHEET_ROOT_NAME = "スキルシート"  # type: ignore[attr-defined]
    drive_mod.DriveClient = object  # type: ignore[attr-defined]
    sys.modules["app.drive_client"] = drive_mod

    for name in (
        "app.logging_util",
        "app.models",
        "app.skill_sheet_extract",
        "app.skill_sheet_names",
        "sqlalchemy",
        "sqlalchemy.orm",
    ):
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)

    sys.modules["app.logging_util"].log_error_event = MagicMock()  # type: ignore[attr-defined]
    sys.modules["app.logging_util"].log_event = MagicMock()  # type: ignore[attr-defined]
    sys.modules["app.models"].Company = object  # type: ignore[attr-defined]
    sys.modules["app.models"].Talent = object  # type: ignore[attr-defined]
    sys.modules["app.models"].TalentSkillSheet = object  # type: ignore[attr-defined]
    sys.modules["app.skill_sheet_extract"].extract_and_apply_to_row = MagicMock()  # type: ignore[attr-defined]
    names = sys.modules["app.skill_sheet_names"]
    for attr in (
        "attachment_source_hint",
        "company_folder_name",
        "drive_storage_filename",
        "extension_from_filename_or_mime",
        "extract_spreadsheet_ids",
        "is_skill_sheet_attachment",
        "spreadsheet_drive_filename",
    ):
        setattr(names, attr, MagicMock())
    sys.modules["sqlalchemy"].select = MagicMock()  # type: ignore[attr-defined]
    sys.modules["sqlalchemy.orm"].Session = object  # type: ignore[attr-defined]


_install_import_stubs()

from app.skill_sheet_ingest import (  # noqa: E402
    SkillSheetDriveContext,
    _apply_web_view_link,
    _save_bytes_to_drive,
)


class SaveBytesToDriveTests(unittest.TestCase):
    def test_existing_file_id_updates_without_find(self) -> None:
        drive = MagicMock()
        drive.update_file_media.return_value = {"id": "file-1", "webViewLink": "https://example/1"}
        result = _save_bytes_to_drive(
            drive,
            folder_id="folder",
            filename="a.xlsx",
            mime_type="application/xlsx",
            data=b"data",
            existing_file_id="file-1",
        )
        self.assertEqual(result["id"], "file-1")
        drive.update_file_media.assert_called_once_with(
            "file-1", mime_type="application/xlsx", data=b"data"
        )
        drive.find_file_in_folder.assert_not_called()
        drive.upload_file.assert_not_called()

    def test_existing_file_id_update_failure_uploads_without_find(self) -> None:
        drive = MagicMock()
        drive.update_file_media.side_effect = _GmailConfigError("ERR-0021", "gone")
        drive.upload_file.return_value = {"id": "new-1", "webViewLink": "https://example/new"}
        result = _save_bytes_to_drive(
            drive,
            folder_id="folder",
            filename="a.xlsx",
            mime_type="application/xlsx",
            data=b"data",
            existing_file_id="stale-id",
        )
        self.assertEqual(result["id"], "new-1")
        drive.find_file_in_folder.assert_not_called()
        drive.upload_file.assert_called_once()

    def test_no_existing_id_finds_then_updates(self) -> None:
        drive = MagicMock()
        drive.find_file_in_folder.return_value = "found-1"
        drive.update_file_media.return_value = {"id": "found-1"}
        _save_bytes_to_drive(
            drive,
            folder_id="folder",
            filename="a.xlsx",
            mime_type="application/xlsx",
            data=b"data",
            existing_file_id=None,
        )
        drive.find_file_in_folder.assert_called_once_with("folder", "a.xlsx")
        drive.update_file_media.assert_called_once()
        drive.upload_file.assert_not_called()


class WebViewLinkTests(unittest.TestCase):
    def test_applies_link_from_upload_response_only(self) -> None:
        row = SimpleNamespace(web_view_link="https://old")
        _apply_web_view_link(row, {"id": "x", "webViewLink": "https://new"})
        self.assertEqual(row.web_view_link, "https://new")

    def test_keeps_previous_when_response_has_no_link(self) -> None:
        row = SimpleNamespace(web_view_link="https://old")
        _apply_web_view_link(row, {"id": "x"})
        self.assertEqual(row.web_view_link, "https://old")


class FolderCacheTests(unittest.TestCase):
    def test_company_folder_cached(self) -> None:
        drive = MagicMock()
        drive.ensure_child_folder.side_effect = ["skill-root", "company-a", "company-b"]
        ctx = SkillSheetDriveContext(drive=drive, root_folder_id="root")
        first = ctx.company_folder_id("株式会社A")
        second = ctx.company_folder_id("株式会社A")
        other = ctx.company_folder_id("株式会社B")
        self.assertEqual(first, "company-a")
        self.assertEqual(second, "company-a")
        self.assertEqual(other, "company-b")
        self.assertEqual(drive.ensure_child_folder.call_count, 3)


if __name__ == "__main__":
    unittest.main()
