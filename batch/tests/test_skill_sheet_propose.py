"""提案添付名・サイズフォールバックの単体テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.email_attachments import (  # noqa: E402
    MAX_ATTACHMENTS_BYTES,
    PreparedAttachment,
    apply_attachment_size_limit,
)
from app.skill_sheet_names import proposal_attachment_filename  # noqa: E402


class SkillSheetProposeTests(unittest.TestCase):
    def test_under_limit_keeps_attachments(self) -> None:
        prepared = [
            PreparedAttachment(
                filename="【ST】_スキルシート.pdf",
                content_type="application/pdf",
                data=b"%PDF-fake",
                display_name="ST",
                web_view_link="https://drive.google.com/file/d/file1/view",
            )
        ]
        attachments, link_lines = apply_attachment_size_limit(prepared)
        self.assertEqual(attachments, prepared)
        self.assertEqual(link_lines, [])

    def test_over_limit_uses_links(self) -> None:
        prepared = [
            PreparedAttachment(
                filename="【AB】_スキルシート.xlsx",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                data=b"x" * (MAX_ATTACHMENTS_BYTES + 1),
                display_name="AB",
                web_view_link="https://drive.google.com/file/d/file2/view",
            )
        ]
        attachments, link_lines = apply_attachment_size_limit(prepared)
        self.assertEqual(attachments, [])
        self.assertTrue(any("AB" in line and "https://" in line for line in link_lines))

    def test_collision_suffix(self) -> None:
        names = [
            proposal_attachment_filename(display_name="ST", ext="pdf", index=i)
            for i in range(1, 4)
        ]
        self.assertEqual(
            names,
            [
                "【ST】_スキルシート.pdf",
                "【ST】_スキルシート_2.pdf",
                "【ST】_スキルシート_3.pdf",
            ],
        )


if __name__ == "__main__":
    unittest.main()
