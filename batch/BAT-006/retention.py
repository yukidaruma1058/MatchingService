"""BAT-006: 保持日数の正規化（DB 非依存）。"""

from __future__ import annotations

from typing import Any


def coerce_non_negative_int(raw: Any, fallback: int) -> int:
    if isinstance(raw, bool):
        return max(fallback, 0)
    if isinstance(raw, dict):
        for key in ("value", "days", "ingest_data_retention_days"):
            if key in raw:
                return coerce_non_negative_int(raw[key], fallback)
        return max(fallback, 0)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return max(fallback, 0)
    return max(value, 0)
