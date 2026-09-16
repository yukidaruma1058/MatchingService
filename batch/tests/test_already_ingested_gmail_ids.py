"""already_ingested_gmail_ids: 取込済み判定。"""

from __future__ import annotations

import unittest
from unittest import mock

from app.email_db import already_ingested_gmail_ids


class AlreadyIngestedGmailIdsTests(unittest.TestCase):
    def test_skips_failed_when_retry_failed(self) -> None:
        session = mock.Mock()
        session.execute.return_value.all.return_value = [
            ("m1", "summarized"),
            ("m2", "failed"),
            ("m3", "needs_review"),
        ]
        result = already_ingested_gmail_ids(session, ["m1", "m2", "m3"], retry_failed=True)
        self.assertEqual(result, {"m1", "m3"})

    def test_includes_failed_when_not_retrying(self) -> None:
        session = mock.Mock()
        session.execute.return_value.all.return_value = [
            ("m1", "summarized"),
            ("m2", "failed"),
        ]
        result = already_ingested_gmail_ids(session, ["m1", "m2"], retry_failed=False)
        self.assertEqual(result, {"m1", "m2"})

    def test_empty_input(self) -> None:
        session = mock.Mock()
        self.assertEqual(already_ingested_gmail_ids(session, []), set())
        session.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
