"""Gmail 取込ラベルに残っているメール件数の取得。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.gmail_client import GmailClient, GmailConfigError
from app.gmail_credentials import ensure_gmail_credentials_file
from app.setting_keys import (
    DEFAULT_SETTINGS,
    SETTING_KEY_GMAIL_SORT_LABEL_PROJECT,
    SETTING_KEY_GMAIL_SORT_LABEL_TALENT,
)


# ダッシュボード表示用のラベル件数上限（超えたら N+ 表示）
GMAIL_INGEST_QUEUE_COUNT_CAP = 1000


def _label_name(db_settings: dict[str, Any], key: str) -> str:
    raw = db_settings.get(key)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    default = DEFAULT_SETTINGS.get(key)
    return str(default) if default is not None else ""


@dataclass
class GmailIngestQueueCounts:
    talent_label: str
    project_label: str
    talent_count: int | None = None
    project_count: int | None = None
    talent_count_capped: bool = False
    project_count_capped: bool = False

    @property
    def pending_total(self) -> int:
        if self.talent_count is None or self.project_count is None:
            return 0
        return self.talent_count + self.project_count


def fetch_gmail_ingest_queue_counts(db_settings: dict[str, Any] | None = None) -> GmailIngestQueueCounts:
    """人材用 / 案件用取込ラベルに付いた Gmail メール件数を返す。"""
    raw = db_settings or {}
    result = GmailIngestQueueCounts(
        talent_label=_label_name(raw, SETTING_KEY_GMAIL_SORT_LABEL_TALENT),
        project_label=_label_name(raw, SETTING_KEY_GMAIL_SORT_LABEL_PROJECT),
    )

    if not ensure_gmail_credentials_file(raw):
        return result
    if not settings.gmail_token_path.exists():
        return result

    client = GmailClient(str(settings.gmail_credentials_path), str(settings.gmail_token_path))
    try:
        client.connect()
    except GmailConfigError:
        return result
    except Exception:
        return result

    for label_name, count_attr, capped_attr in (
        (result.talent_label, "talent_count", "talent_count_capped"),
        (result.project_label, "project_count", "project_count_capped"),
    ):
        if not label_name:
            continue
        try:
            count, capped = client.count_messages_with_label(
                label_name,
                max_count=GMAIL_INGEST_QUEUE_COUNT_CAP,
            )
            setattr(result, count_attr, count)
            setattr(result, capped_attr, capped)
        except GmailConfigError:
            continue
        except Exception:
            continue

    return result
