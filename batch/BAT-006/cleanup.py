"""BAT-006: 取込データ削除バッチ。

処理概要:
  1. ``ingest_data_retention_days`` 設定を読み込む
  2. 0 の場合は削除せず終了
  3. ``created_at`` が保持日数より古い ``emails`` を削除
     （talents / projects は ON DELETE CASCADE で連動）
     送信済み提案に紐づく人材・案件・返信元メールは削除対象外

起動:
  - ``python -m app.main cleanup``（Ofelia 日次 / 手動）
  - 取込パイプライン（BAT-002 の後）からも実行
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from cleanup_db import delete_expired_ingest_data, load_retention_days

from app.batch_job_id import resolve_batch_job_id
from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.logging_util import get_batch_logger, log_event


@dataclass
class CleanupBatchStats:
    retention_days: int = 0
    deleted_count: int = 0
    deleted_emails: int = 0
    deleted_talents: int = 0
    deleted_projects: int = 0
    skipped_protected: int = 0
    skipped: bool = False
    extra: dict = field(default_factory=dict)


class IngestDataCleanupBatch:
    """BAT-006 取込データ削除バッチの実行クラス。"""

    function_id = "BAT-006"

    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or settings
        self.logger = get_batch_logger()
        self.job_id = resolve_batch_job_id(default_prefix="job")

    def run(self) -> CleanupBatchStats:
        started = time.perf_counter()
        stats = CleanupBatchStats()

        log_event(
            self.logger,
            logging.INFO,
            event="ingest_cleanup.started",
            message="Ingest data cleanup batch started",
            operation="取込データ削除開始",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            module_name="BAT-006.cleanup",
        )

        session_factory, engine = create_session_factory(self.cfg.database_url)
        ensure_schema(engine)

        with session_factory() as session:
            stats.retention_days = load_retention_days(session, self.cfg)

        if stats.retention_days <= 0:
            stats.skipped = True
            log_event(
                self.logger,
                logging.INFO,
                event="ingest_cleanup.skipped",
                message="Retention disabled; cleanup skipped",
                operation="取込データ削除スキップ",
                method_name="run",
                job_id=self.job_id,
                function_id=self.function_id,
                module_name="BAT-006.cleanup",
                extra={"retention_days": stats.retention_days},
            )
            return stats

        with session_factory() as session:
            deleted = delete_expired_ingest_data(session, stats.retention_days)
            session.commit()

        stats.deleted_emails = deleted.get("emails", 0)
        stats.deleted_talents = deleted.get("talents", 0)
        stats.deleted_projects = deleted.get("projects", 0)
        stats.skipped_protected = deleted.get("skipped_protected", 0)
        stats.deleted_count = stats.deleted_emails

        duration_ms = int((time.perf_counter() - started) * 1000)
        log_event(
            self.logger,
            logging.INFO,
            event="ingest_cleanup.finished",
            message="Ingest data cleanup batch finished",
            operation="取込データ削除完了",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            module_name="BAT-006.cleanup",
            duration_ms=duration_ms,
            extra={
                "retention_days": stats.retention_days,
                "deleted": stats.deleted_count,
                "deleted_emails": stats.deleted_emails,
                "deleted_talents": stats.deleted_talents,
                "deleted_projects": stats.deleted_projects,
                "skipped_protected": stats.skipped_protected,
            },
        )
        return stats


def run_cleanup_batch(cfg: Settings | None = None) -> CleanupBatchStats:
    """BAT-006 を実行する公開関数。"""
    return IngestDataCleanupBatch(cfg).run()
