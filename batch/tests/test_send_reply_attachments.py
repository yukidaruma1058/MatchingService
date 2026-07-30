"""send_reply の添付 MIME 構築テスト（Gmail API 非依存）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.email_attachments import build_reply_email_message  # noqa: E402


class SendReplyAttachmentTests(unittest.TestCase):
    def test_build_reply_includes_attachment_part(self) -> None:
        msg = build_reply_email_message(
            from_addr="me@example.com",
            to_addr="to@example.com",
            subject_text="Re: 提案",
            body_text="本文です",
            attachments=[
                {
                    "filename": "【ST】_スキルシート.pdf",
                    "content_type": "application/pdf",
                    "data": b"%PDF-1.4",
                }
            ],
        )
        filenames = [part.get_filename() for part in msg.walk() if part.get_filename()]
        self.assertIn("【ST】_スキルシート.pdf", filenames)
        self.assertEqual(msg["To"], "to@example.com")
        self.assertEqual(msg["Subject"], "Re: 提案")


if __name__ == "__main__":
    unittest.main()
