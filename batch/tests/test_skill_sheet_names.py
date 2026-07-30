"""スキルシート命名・URL 抽出・添付判定の単体テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from uuid import UUID

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.skill_sheet_names import (  # noqa: E402
    attachment_source_hint,
    company_folder_name,
    drive_storage_filename,
    extract_spreadsheet_ids,
    is_skill_sheet_attachment,
    proposal_attachment_filename,
    sanitize_filename_part,
    spreadsheet_drive_filename,
)


class SkillSheetNamesTests(unittest.TestCase):
    def test_sanitize_and_company_folder(self) -> None:
        self.assertEqual(sanitize_filename_part("a/b:c"), "a_b_c")
        self.assertEqual(company_folder_name(None), "未設定")
        self.assertEqual(company_folder_name("株式会社アストロ"), "株式会社アストロ")

    def test_drive_storage_filename(self) -> None:
        tid = UUID("a1b2c3d4-0000-0000-0000-000000000001")
        name = drive_storage_filename(
            display_name="ST",
            talent_id=tid,
            source_hint="職務経歴書_2026",
            ext="pdf",
        )
        self.assertEqual(name, "ST_a1b2c3d4_職務経歴書_2026.pdf")

    def test_spreadsheet_drive_filename(self) -> None:
        tid = "e5f6g7h8-1111-1111-1111-111111111111"
        self.assertEqual(
            spreadsheet_drive_filename(display_name="AB", talent_id=tid),
            "AB_e5f6g7h8_spreadsheet.xlsx",
        )

    def test_proposal_attachment_filename_collision(self) -> None:
        self.assertEqual(
            proposal_attachment_filename(display_name="ST", ext="pdf"),
            "【ST】_スキルシート.pdf",
        )
        self.assertEqual(
            proposal_attachment_filename(display_name="ST", ext="pdf", index=2),
            "【ST】_スキルシート_2.pdf",
        )

    def test_attachment_source_hint(self) -> None:
        self.assertEqual(attachment_source_hint("職務経歴書_2026.pdf"), "職務経歴書_2026")
        self.assertEqual(attachment_source_hint(""), "skill")

    def test_extract_spreadsheet_ids(self) -> None:
        body = (
            "シート: https://docs.google.com/spreadsheets/d/AbC123_xy/edit#gid=0\n"
            "同じ: https://docs.google.com/spreadsheets/d/AbC123_xy/edit\n"
            "別: https://docs.google.com/spreadsheets/d/Zz99/view"
        )
        self.assertEqual(extract_spreadsheet_ids(body), ["AbC123_xy", "Zz99"])

    def test_is_skill_sheet_attachment(self) -> None:
        self.assertTrue(is_skill_sheet_attachment(filename="a.xlsx", mime_type=None))
        self.assertTrue(is_skill_sheet_attachment(filename="resume.pdf", mime_type=None))
        self.assertTrue(
            is_skill_sheet_attachment(filename="職務経歴.docx", mime_type="application/octet-stream")
        )
        self.assertFalse(is_skill_sheet_attachment(filename="photo.png", mime_type="image/png"))


if __name__ == "__main__":
    unittest.main()
