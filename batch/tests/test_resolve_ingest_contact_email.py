"""From が連携 Gmail 同ドメインのとき Reply-To を企業登録に使う。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))


def _ensure_deps() -> None:
    if "sqlalchemy" not in sys.modules:
        sqlalchemy = MagicMock()
        sys.modules["sqlalchemy"] = sqlalchemy
        sys.modules["sqlalchemy.orm"] = MagicMock()
        sys.modules["sqlalchemy.dialects"] = MagicMock()
        sys.modules["sqlalchemy.dialects.postgresql"] = MagicMock()
    if "httplib2" not in sys.modules:
        for name in (
            "httplib2",
            "google",
            "google.auth",
            "google.auth.transport",
            "google.auth.transport.requests",
            "google.oauth2",
            "google.oauth2.credentials",
            "google_auth_httplib2",
            "googleapiclient",
            "googleapiclient.discovery",
            "googleapiclient.errors",
            "googleapiclient.http",
        ):
            sys.modules.setdefault(name, MagicMock())
        sys.modules["googleapiclient.errors"].HttpError = type("HttpError", (Exception,), {})


_ensure_deps()

from app.company_contact_db import resolve_ingest_contact_email  # noqa: E402
from app.gmail_client import _gmail_message_from_raw  # noqa: E402


class ResolveIngestContactEmailTests(unittest.TestCase):
    def test_same_domain_uses_reply_to(self) -> None:
        addr = resolve_ingest_contact_email(
            from_address="sales@kanana-tech.jp",
            reply_to_address="sugimoto@other-co.jp",
            linked_gmail_address="sales@kanana-tech.jp",
        )
        self.assertEqual(addr, "sugimoto@other-co.jp")

    def test_same_domain_alias_uses_reply_to(self) -> None:
        addr = resolve_ingest_contact_email(
            from_address="sales@kanana-tech.jp",
            reply_to_address="taro@partner.example",
            linked_gmail_address="admin@kanana-tech.jp",
        )
        self.assertEqual(addr, "taro@partner.example")

    def test_same_domain_without_reply_to_keeps_from(self) -> None:
        addr = resolve_ingest_contact_email(
            from_address="sales@kanana-tech.jp",
            reply_to_address=None,
            linked_gmail_address="sales@kanana-tech.jp",
        )
        self.assertEqual(addr, "sales@kanana-tech.jp")

    def test_other_domain_keeps_from(self) -> None:
        addr = resolve_ingest_contact_email(
            from_address="info@other-co.jp",
            reply_to_address="other@elsewhere.jp",
            linked_gmail_address="sales@kanana-tech.jp",
        )
        self.assertEqual(addr, "info@other-co.jp")

    def test_parse_reply_to_from_raw_message(self) -> None:
        raw = {
            "id": "msg1",
            "threadId": "th1",
            "labelIds": [],
            "internalDate": "1700000000000",
            "payload": {
                "mimeType": "text/plain",
                "headers": [
                    {"name": "From", "value": "'杉本泰弘' via 営業窓口 <sales@kanana-tech.jp>"},
                    {"name": "Reply-To", "value": "杉本泰弘 <sugimoto@other-co.jp>"},
                    {"name": "Subject", "value": "人材ご紹介"},
                ],
                "body": {"data": ""},
            },
        }
        message = _gmail_message_from_raw(raw, message_id="msg1")
        self.assertEqual(message.from_address, "sales@kanana-tech.jp")
        self.assertEqual(message.reply_to_address, "sugimoto@other-co.jp")
        self.assertIn("sugimoto@other-co.jp", message.reply_to_header)
        resolved = resolve_ingest_contact_email(
            from_address=message.from_address,
            reply_to_address=message.reply_to_address,
            linked_gmail_address="sales@kanana-tech.jp",
        )
        self.assertEqual(resolved, "sugimoto@other-co.jp")


if __name__ == "__main__":
    unittest.main()
