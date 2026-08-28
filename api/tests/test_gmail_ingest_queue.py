"""gmail_ingest_queue: 取込ラベル件数の取得。"""

from __future__ import annotations

import unittest
from unittest import mock

from app import gmail_ingest_queue


class GmailIngestQueueTests(unittest.TestCase):
    def test_returns_defaults_when_gmail_not_configured(self) -> None:
        with mock.patch.object(gmail_ingest_queue, "ensure_gmail_credentials_file", return_value=False):
            result = gmail_ingest_queue.fetch_gmail_ingest_queue_counts(
                {
                    "gmail_sort_label_talent": "人材情報",
                    "gmail_sort_label_project": "案件情報",
                }
            )
        self.assertEqual(result.talent_label, "人材情報")
        self.assertEqual(result.project_label, "案件情報")
        self.assertIsNone(result.talent_count)
        self.assertIsNone(result.project_count)
        self.assertEqual(result.pending_total, 0)

    def test_counts_messages_per_label(self) -> None:
        client = mock.Mock()
        client.connect = mock.Mock()
        client.count_messages_with_label = mock.Mock(side_effect=[(12, False), (8, True)])

        mock_token = mock.Mock()
        mock_token.exists.return_value = True

        with (
            mock.patch.object(gmail_ingest_queue, "ensure_gmail_credentials_file", return_value=True),
            mock.patch.object(gmail_ingest_queue.settings, "gmail_token_path", mock_token),
            mock.patch.object(gmail_ingest_queue, "GmailClient", return_value=client),
        ):
            result = gmail_ingest_queue.fetch_gmail_ingest_queue_counts({})

        self.assertEqual(result.talent_count, 12)
        self.assertEqual(result.project_count, 8)
        self.assertFalse(result.talent_count_capped)
        self.assertTrue(result.project_count_capped)
        self.assertEqual(result.pending_total, 20)
        client.count_messages_with_label.assert_any_call(
            "SES人材紹介",
            max_count=gmail_ingest_queue.GMAIL_INGEST_QUEUE_COUNT_CAP,
        )
        client.count_messages_with_label.assert_any_call(
            "SES案件配信",
            max_count=gmail_ingest_queue.GMAIL_INGEST_QUEUE_COUNT_CAP,
        )
        self.assertEqual(gmail_ingest_queue.GMAIL_INGEST_QUEUE_COUNT_CAP, 1000)


if __name__ == "__main__":
    unittest.main()
