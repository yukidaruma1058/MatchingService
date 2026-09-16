"""pipeline_progress: batch.log から進捗を組み立てる。"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from app.pipeline_progress import (
    _DEFAULT_PIPELINE_STEPS,
    _HIDDEN_PIPELINE_STEPS,
    find_latest_active_pipeline_job_id,
    parse_pipeline_progress,
)


def _write_rows(log_path: Path, rows: list[dict]) -> None:
    log_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


class PipelineProgressTests(unittest.TestCase):
    def test_default_steps_include_match_not_ai_judge(self) -> None:
        self.assertIn("match", _DEFAULT_PIPELINE_STEPS)
        self.assertNotIn("ai_judge", _DEFAULT_PIPELINE_STEPS)
        self.assertEqual(_HIDDEN_PIPELINE_STEPS, {"ai_judge"})

    def test_parse_ingest_talent_step_progress(self) -> None:
        started = datetime(2026, 8, 28, 7, 0, 0, tzinfo=UTC)
        job_id = "pipeline_test123"
        rows = [
            {
                "timestamp": started.isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.started",
                "extra": {
                    "steps": [
                        "ingest_talent",
                        "ingest_project",
                        "cleanup",
                        "match",
                        "reply_sync",
                    ]
                },
            },
            {
                "timestamp": (started + timedelta(seconds=1)).isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.step_started",
                "extra": {"step": "ingest_talent"},
            },
            {
                "timestamp": (started + timedelta(seconds=5)).isoformat(),
                "job_id": job_id,
                "event": "gmail_ingest.label_targets",
                "extra": {"label_type": "talent", "source_label": "人材情報", "targets": 4, "listed": 4},
            },
            {
                "timestamp": (started + timedelta(seconds=8)).isoformat(),
                "job_id": job_id,
                "event": "gmail_ingest.fetch_progress",
                "extra": {"label_type": "talent", "done": 4, "total": 4},
            },
            {
                "timestamp": (started + timedelta(seconds=12)).isoformat(),
                "job_id": job_id,
                "event": "gmail_ingest.ai_progress",
                "extra": {"label_type": "talent", "done": 2, "total": 4},
            },
            {
                "timestamp": (started + timedelta(seconds=20)).isoformat(),
                "job_id": job_id,
                "event": "gmail_ingest.message_fetched",
                "extra": {"label_type": "talent"},
            },
        ]
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            _write_rows(log_path, rows)
            with mock.patch("app.pipeline_progress.is_batch_job_running", return_value=True):
                progress = parse_pipeline_progress(job_id, log_path=log_path)

        self.assertEqual(progress.status, "running")
        self.assertEqual(progress.phase, "ingest_talent")
        self.assertGreater(progress.progress_percent, 0)
        self.assertLess(progress.progress_percent, 100)
        self.assertEqual(len(progress.steps), 5)
        talent_step = next(step for step in progress.steps if step.id == "ingest_talent")
        self.assertEqual(talent_step.status, "running")
        self.assertGreater(talent_step.progress_percent, 0)
        self.assertIn("AI要約", talent_step.detail or "")
        self.assertTrue(any(step.id == "match" for step in progress.steps))
        self.assertFalse(any(step.id == "ai_judge" for step in progress.steps))

    def test_parse_ingest_expands_and_runs_talent_and_project_in_parallel(self) -> None:
        started = datetime(2026, 8, 28, 7, 30, 0, tzinfo=UTC)
        job_id = "pipeline_parallel"
        rows = [
            {
                "timestamp": started.isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.started",
                "extra": {"steps": ["ingest", "cleanup", "reply_sync"]},
            },
            {
                "timestamp": (started + timedelta(seconds=1)).isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.step_started",
                "extra": {"step": "ingest"},
            },
            {
                "timestamp": (started + timedelta(seconds=3)).isoformat(),
                "job_id": job_id,
                "event": "gmail_ingest.label_targets",
                "extra": {"label_type": "talent", "source_label": "人材情報", "targets": 2, "listed": 2},
            },
            {
                "timestamp": (started + timedelta(seconds=3)).isoformat(),
                "job_id": job_id,
                "event": "gmail_ingest.label_targets",
                "extra": {"label_type": "project", "source_label": "案件情報", "targets": 3, "listed": 3},
            },
            {
                "timestamp": (started + timedelta(seconds=8)).isoformat(),
                "job_id": job_id,
                "event": "gmail_ingest.ai_progress",
                "extra": {"label_type": "talent", "done": 2, "total": 2},
            },
            {
                "timestamp": (started + timedelta(seconds=9)).isoformat(),
                "job_id": job_id,
                "event": "gmail_ingest.ai_progress",
                "extra": {"label_type": "project", "done": 1, "total": 3},
            },
        ]
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            _write_rows(log_path, rows)
            with mock.patch("app.pipeline_progress.is_batch_job_running", return_value=True):
                progress = parse_pipeline_progress(job_id, log_path=log_path)

        self.assertEqual([step.id for step in progress.steps], ["ingest_talent", "ingest_project", "cleanup", "reply_sync"])
        talent_step = next(step for step in progress.steps if step.id == "ingest_talent")
        project_step = next(step for step in progress.steps if step.id == "ingest_project")
        self.assertEqual(talent_step.status, "running")
        self.assertEqual(project_step.status, "running")
        self.assertFalse(any(step.id in {"match", "ai_judge"} for step in progress.steps))

    def test_parse_completed_pipeline_with_steps(self) -> None:
        started = datetime(2026, 8, 28, 8, 0, 0, tzinfo=UTC)
        job_id = "pipeline_done456"
        rows = [
            {
                "timestamp": started.isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.started",
                "extra": {"steps": ["ingest_talent", "cleanup", "reply_sync"]},
            },
            {
                "timestamp": (started + timedelta(minutes=5)).isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.finished",
                "extra": {"status": "ok"},
            },
        ]
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            _write_rows(log_path, rows)
            progress = parse_pipeline_progress(job_id, log_path=log_path)

        self.assertEqual(progress.status, "completed")
        self.assertEqual(progress.progress_percent, 100)
        self.assertEqual(progress.phase, "done")

    def test_parse_cancelled_pipeline(self) -> None:
        started = datetime(2026, 8, 28, 8, 30, 0, tzinfo=UTC)
        job_id = "pipeline_cancel789"
        rows = [
            {
                "timestamp": started.isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.started",
                "extra": {"steps": ["ingest_talent", "reply_sync"]},
            },
            {
                "timestamp": (started + timedelta(minutes=1)).isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.finished",
                "extra": {"status": "cancelled"},
            },
        ]
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            _write_rows(log_path, rows)
            progress = parse_pipeline_progress(job_id, log_path=log_path)

        self.assertEqual(progress.status, "failed")
        self.assertEqual(progress.error_message, "処理が停止されました")

    def test_parse_orphaned_pipeline_without_process(self) -> None:
        started = datetime(2026, 8, 28, 8, 45, 0, tzinfo=UTC)
        job_id = "pipeline_orphan000"
        rows = [
            {
                "timestamp": started.isoformat(),
                "job_id": job_id,
                "event": "batch.pipeline.started",
                "extra": {"steps": ["ingest_talent"]},
            },
        ]
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            _write_rows(log_path, rows)
            with mock.patch("app.pipeline_progress.is_batch_job_running", return_value=False):
                progress = parse_pipeline_progress(job_id, log_path=log_path)

        self.assertEqual(progress.status, "failed")
        self.assertEqual(progress.error_message, "処理が中断されました")

    def test_find_latest_active_pipeline_job_id(self) -> None:
        started = datetime(2026, 8, 28, 9, 0, 0, tzinfo=UTC)
        active_id = "pipeline_active"
        done_id = "pipeline_done"
        rows = [
            {
                "timestamp": started.isoformat(),
                "job_id": done_id,
                "event": "batch.pipeline.started",
                "extra": {"steps": ["ingest_talent"]},
            },
            {
                "timestamp": (started + timedelta(minutes=1)).isoformat(),
                "job_id": done_id,
                "event": "batch.pipeline.finished",
                "extra": {"status": "ok"},
            },
            {
                "timestamp": (started + timedelta(minutes=2)).isoformat(),
                "job_id": active_id,
                "event": "batch.pipeline.started",
                "extra": {"steps": ["ingest_talent"]},
            },
        ]
        with TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "batch.log"
            _write_rows(log_path, rows)
            found = find_latest_active_pipeline_job_id(log_path=log_path)

        self.assertEqual(found, active_id)


if __name__ == "__main__":
    unittest.main()
