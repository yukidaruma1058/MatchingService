"""gmail_ingest_queue: 取込ラベルのうち未取込件数の取得。"""

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

    def test_counts_pending_minus_already_ingested(self) -> None:
        client = mock.Mock()
        client.connect = mock.Mock()
        client.list_message_ids_with_label = mock.Mock(
            side_effect=[
                ["t1", "t2", "t3"],
                ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"],
            ]
        )

        mock_token = mock.Mock()
        mock_token.exists.return_value = True
        session = mock.Mock()

        def _already(_session, ids, *, retry_failed=True):
            listed = list(ids)
            if listed and listed[0].startswith("t"):
                return {"t1", "t2"}
            return {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}

        with (
            mock.patch.object(gmail_ingest_queue, "ensure_gmail_credentials_file", return_value=True),
            mock.patch.object(gmail_ingest_queue.settings, "gmail_token_path", mock_token),
            mock.patch.object(gmail_ingest_queue, "GmailClient", return_value=client),
            mock.patch.object(
                gmail_ingest_queue,
                "already_ingested_gmail_ids",
                side_effect=_already,
            ),
        ):
            result = gmail_ingest_queue.fetch_gmail_ingest_queue_counts({}, session=session)

        self.assertEqual(result.talent_count, 1)
        self.assertEqual(result.project_count, 1)
        self.assertFalse(result.talent_count_capped)
        self.assertFalse(result.project_count_capped)
        self.assertEqual(result.pending_total, 2)
        client.list_message_ids_with_label.assert_any_call(
            "SES人材紹介",
            max_results=gmail_ingest_queue.GMAIL_INGEST_QUEUE_COUNT_CAP,
        )
        client.list_message_ids_with_label.assert_any_call(
            "SES案件配信",
            max_results=gmail_ingest_queue.GMAIL_INGEST_QUEUE_COUNT_CAP,
        )
        self.assertEqual(gmail_ingest_queue.GMAIL_INGEST_QUEUE_COUNT_CAP, 1000)

    def test_without_session_counts_all_listed(self) -> None:
        client = mock.Mock()
        client.connect = mock.Mock()
        client.list_message_ids_with_label = mock.Mock(side_effect=[["a", "b"], ["c"]])

        mock_token = mock.Mock()
        mock_token.exists.return_value = True

        with (
            mock.patch.object(gmail_ingest_queue, "ensure_gmail_credentials_file", return_value=True),
            mock.patch.object(gmail_ingest_queue.settings, "gmail_token_path", mock_token),
            mock.patch.object(gmail_ingest_queue, "GmailClient", return_value=client),
        ):
            result = gmail_ingest_queue.fetch_gmail_ingest_queue_counts({})

        self.assertEqual(result.talent_count, 2)
        self.assertEqual(result.project_count, 1)
        self.assertEqual(result.pending_total, 3)


if __name__ == "__main__":
    unittest.main()
