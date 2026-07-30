"""振り分け対象ラベル件数のプロセス内キャッシュ（TTL 15 分）。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

CACHE_TTL = timedelta(minutes=15)


@dataclass
class SortQueueCacheEntry:
    label: str
    count: int
    capped: bool
    fetched_at: datetime
    error_code: str | None = None
    error_message: str | None = None

    @property
    def expires_at(self) -> datetime:
        return self.fetched_at + CACHE_TTL

    def is_fresh(self, *, now: datetime | None = None) -> bool:
        current = now or datetime.now(UTC)
        return current < self.expires_at

    def to_payload(self, *, cached: bool) -> dict[str, Any]:
        return {
            "label": self.label,
            "count": self.count,
            "capped": self.capped,
            "cached": cached,
            "fetched_at": self.fetched_at.isoformat().replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat().replace("+00:00", "Z"),
            "cache_ttl_seconds": int(CACHE_TTL.total_seconds()),
            "error_code": self.error_code,
            "error_message": self.error_message,
        }


_lock = threading.Lock()
_entry: SortQueueCacheEntry | None = None


def get_cached_sort_queue() -> SortQueueCacheEntry | None:
    with _lock:
        return _entry


def set_cached_sort_queue(entry: SortQueueCacheEntry) -> None:
    global _entry
    with _lock:
        _entry = entry


def clear_cached_sort_queue() -> None:
    global _entry
    with _lock:
        _entry = None
