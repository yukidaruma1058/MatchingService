"""batch_runner: 古い ERROR を今回の失敗として返さないこと。"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app import batch_runner


class ReadLastBatchErrorTests(unittest.TestCase):
    def test_ignores_errors_before_offset(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            old = {
                "level": "ERROR",
                "error_code": "ERR-0030",
                "error_message": "システムエラーが発生しました。時間をおいて再度お試しください。",
                "message": "[SSL] record layer failure",
            }
            log_path.write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")
            offset = log_path.stat().st_size
            # 今回の実行では ERROR が無い
            log_path.write_text(
                log_path.read_text(encoding="utf-8")
                + json.dumps(
                    {
                        "level": "INFO",
                        "event": "gmail_sort.messages_loaded",
                        "message": "Gmail messages loaded",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(batch_runner, "BATCH_LOG_PATH", log_path):
                with mock.patch.object(batch_runner, "_last_run_log_offset", offset):
                    self.assertIsNone(batch_runner.read_last_batch_error())
                    self.assertIsNone(batch_runner.read_last_batch_error(after_byte_offset=offset))

    def test_returns_error_after_offset_with_technical_detail(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            old = {
                "level": "ERROR",
                "error_code": "ERR-0030",
                "error_message": "システムエラーが発生しました。時間をおいて再度お試しください。",
                "message": "stale ssl",
            }
            log_path.write_text(json.dumps(old, ensure_ascii=False) + "\n", encoding="utf-8")
            offset = log_path.stat().st_size
            fresh = {
                "level": "ERROR",
                "error_code": "ERR-0030",
                "error_message": "システムエラーが発生しました。時間をおいて再度お試しください。",
                "message": "The read operation timed out",
            }
            log_path.write_text(
                log_path.read_text(encoding="utf-8") + json.dumps(fresh, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(batch_runner, "BATCH_LOG_PATH", log_path):
                got = batch_runner.read_last_batch_error(after_byte_offset=offset)
            self.assertIsNotNone(got)
            assert got is not None
            self.assertEqual(got["error_code"], "ERR-0030")
            self.assertIn("タイムアウト", got["error_message"])
            self.assertNotIn("stale ssl", got["error_message"])

    def test_summarize_long_db_error(self) -> None:
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            msg = (
                "(psycopg.OperationalError) number of parameters must be between 0 and 65535\n"
                + "[SQL: SELECT ... very long ...]"
            )
            entry = {
                "level": "ERROR",
                "error_code": "ERR-0030",
                "error_message": "システムエラーが発生しました。時間をおいて再度お試しください。",
                "message": msg,
            }
            log_path.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
            with mock.patch.object(batch_runner, "BATCH_LOG_PATH", log_path):
                got = batch_runner.read_last_batch_error()
            self.assertIsNotNone(got)
            assert got is not None
            self.assertIn("ルール採点", got["error_message"])
            self.assertNotIn("65535", got["error_message"])


class BatchJobProcessTests(unittest.TestCase):
    def test_parse_batch_job_from_argv(self) -> None:
        self.assertEqual(
            batch_runner.parse_batch_job_from_argv(["python", "-m", "app.main", "pipeline"]),
            "pipeline",
        )
        self.assertEqual(
            batch_runner.parse_batch_job_from_argv(["python", "-m", "app.main", "match"]),
            "match",
        )
        self.assertIsNone(batch_runner.parse_batch_job_from_argv(["uvicorn", "app.main:app"]))

    def test_batch_job_label(self) -> None:
        self.assertEqual(batch_runner.batch_job_label("cleanup"), "取込データ削除")
        self.assertEqual(batch_runner.batch_job_label("unknown_job"), "unknown_job")

    def test_cancel_orphaned_pipeline_jobs(self) -> None:
        started = datetime(2026, 8, 28, 10, 0, 0, tzinfo=UTC)
        job_id = "pipeline_orphan111"
        rows = [
            {
                "timestamp": started.isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.started",
                "extra": {"steps": ["ingest"]},
            },
        ]
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            log_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )
            with mock.patch("app.pipeline_progress.BATCH_LOG_PATH", log_path):
                with mock.patch.object(batch_runner, "BATCH_LOG_PATH", log_path):
                    with mock.patch.object(batch_runner, "is_batch_job_running", return_value=False):
                        cancelled = batch_runner.cancel_orphaned_pipeline_jobs()
            self.assertEqual(cancelled, [job_id])
            text = log_path.read_text(encoding="utf-8")
            self.assertIn('"status": "cancelled"', text)


if __name__ == "__main__":
    unittest.main()
