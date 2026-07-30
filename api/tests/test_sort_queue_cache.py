"""sort_queue_cache の TTL テスト。"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from app.sort_queue_cache import (
    CACHE_TTL,
    SortQueueCacheEntry,
    clear_cached_sort_queue,
    get_cached_sort_queue,
    set_cached_sort_queue,
)


class SortQueueCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_cached_sort_queue()

    def tearDown(self) -> None:
        clear_cached_sort_queue()

    def test_ttl_is_15_minutes(self) -> None:
        self.assertEqual(CACHE_TTL, timedelta(minutes=15))

    def test_fresh_within_ttl(self) -> None:
        now = datetime(2026, 7, 24, 3, 0, tzinfo=UTC)
        entry = SortQueueCacheEntry(label="SES未振り分け", count=3, capped=False, fetched_at=now)
        self.assertTrue(entry.is_fresh(now=now + timedelta(minutes=14, seconds=59)))
        self.assertFalse(entry.is_fresh(now=now + timedelta(minutes=15)))

    def test_set_and_get(self) -> None:
        entry = SortQueueCacheEntry(
            label="SES未振り分け",
            count=2,
            capped=False,
            fetched_at=datetime.now(UTC),
        )
        set_cached_sort_queue(entry)
        got = get_cached_sort_queue()
        self.assertIsNotNone(got)
        assert got is not None
        self.assertEqual(got.count, 2)
        self.assertEqual(got.label, "SES未振り分け")


if __name__ == "__main__":
    unittest.main()
