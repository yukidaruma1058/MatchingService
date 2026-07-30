"""skill_sheet_extract のユニットテスト。"""

from __future__ import annotations

import io
import unittest

from app.skill_sheet_extract import extract_experience_from_bytes


def _minimal_xlsx_with_career() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["氏名", "テスト太郎"])
    ws.append(["職務経歴", ""])
    ws.append(["期間", "案件", "使用スキル", "業務内容"])
    ws.append(["2020-2022", "基幹刷新", "Java, Spring", "API 設計・実装"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


class SkillSheetExtractTests(unittest.TestCase):
    def test_xlsx_extracts_career_section(self) -> None:
        data = _minimal_xlsx_with_career()
        result = extract_experience_from_bytes(
            data,
            filename="skill.xlsx",
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(result.status, "ok")
        self.assertIsNotNone(result.text)
        assert result.text is not None
        self.assertIn("Java", result.text)
        self.assertIn("職務経歴", result.text)

    def test_empty_pdf_is_empty_status(self) -> None:
        try:
            from pypdf import PdfWriter
        except ImportError:
            self.skipTest("pypdf not installed")

        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buffer = io.BytesIO()
        writer.write(buffer)
        result = extract_experience_from_bytes(buffer.getvalue(), filename="scan.pdf", content_type="application/pdf")
        self.assertEqual(result.status, "empty")

    def test_unsupported_extension(self) -> None:
        result = extract_experience_from_bytes(b"hello", filename="notes.txt", content_type="text/plain")
        self.assertEqual(result.status, "unsupported")


if __name__ == "__main__":
    unittest.main()
