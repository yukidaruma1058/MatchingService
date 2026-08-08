"""バッチ全体のエントリポイント。

画面 API や ``docker compose ... run batch`` から ``python -m app.main <job>`` で起動する。
ジョブ名とバッチ ID の対応:
  - ``sort`` → BAT-001（メール振り分け）
  - ``ingest`` → BAT-002（メール取込・要約）
  - ``manual_register`` → BAT-002（画面のタイトル+本文から AI 要約登録。MANUAL_EMAIL_ID 必須）
  - ``pipeline`` → BAT-001 → BAT-002 → BAT-006 → BAT-003 →（設定ONなら BAT-004）→ BAT-008
    （振り分け・取込・採点・任意でAI判定・返信同期）
  - ``cleanup`` → BAT-006（取込データ削除）
  - ``match`` → BAT-003（ルールスコア採点）
  - ``talent_propose`` → BAT-007（要員側へ案件提案・手動）
  - ``reply_sync`` → BAT-008（返信同期・OK/NG）
  - ``ai_judge`` → BAT-004（AI判定）
  - ``project_propose`` → BAT-009（案件側へ要員提案・手動）
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

_BATCH_ROOT = Path(__file__).resolve().parent.parent


def _is_ai_assist_enabled() -> bool:
    """system_settings.ai_assist_enabled を読む。"""
    from app.config import settings as app_settings
    from app.db_bootstrap import create_session_factory, ensure_schema
    from app.models import SystemSetting

    session_factory, engine = create_session_factory(app_settings.database_url)
    ensure_schema(engine)
    with session_factory() as session:
        row = session.get(SystemSetting, "ai_assist_enabled")
        if row is None or row.value is None:
            return False
        value = row.value
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)


def _ensure_batch_path(folder_name: str) -> None:
    """ハイフン付きバッチフォルダを import 可能にする。"""
    batch_dir = _BATCH_ROOT / folder_name
    path = str(batch_dir)
    if path not in sys.path:
        sys.path.insert(0, path)


def _clear_batch_modules(*module_names: str) -> None:
    """同名モジュール（db 等）の import 衝突を避けるためキャッシュを消す。"""
    for module_name in module_names:
        sys.modules.pop(module_name, None)


def _load_batch_callable(folder_name: str, module_name: str, attr_name: str, *, clear_modules: tuple[str, ...]) -> Callable[..., Any]:
    """指定バッチフォルダから実行関数を遅延 import する。"""
    _ensure_batch_path(folder_name)
    _clear_batch_modules(*clear_modules)
    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


from app.config import settings
from app.gmail_client import GmailConfigError
from app.logging_util import configure_logging, get_batch_logger, log_error_event, log_event

_JOB_CHOICES = [
    "sort",
    "ingest",
    "manual_register",
    "pipeline",
    "cleanup",
    "match",
    "talent_propose",
    "reply_sync",
    "ai_judge",
    "project_propose",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """コマンドライン引数を解析し、実行するジョブ名を返す。"""
    parser = argparse.ArgumentParser(description="MatchingService batch runner")
    parser.add_argument(
        "job",
        nargs="?",
        default=settings.batch_job,
        choices=_JOB_CHOICES,
        help="Batch job id",
    )
    return parser.parse_args(argv)


def run(job: str, *, match_trigger: str = "manual") -> int:
    """指定ジョブを実行し、終了コード（0=成功, 1=失敗）を返す。"""
    logger = get_batch_logger()
    log_event(
        logger,
        logging.INFO,
        event="batch.run.started",
        message=f"Batch job started: {job}",
        operation="バッチジョブ開始",
        method_name="run",
        job_id="run",
        function_id="BATCH",
        module_name="app.main",
        extra={"job": job},
    )

    if job == "sort":
        try:
            run_sort_batch = _load_batch_callable(
                "BAT-001",
                "gmail_sort",
                "run_sort_batch",
                clear_modules=("db", "classifier", "gmail_sort"),
            )
            stats = run_sort_batch()
            log_event(
                logger,
                logging.INFO,
                event="batch.run.finished",
                message="Batch job finished: sort",
                operation="バッチジョブ完了",
                method_name="run",
                job_id="run",
                function_id="BATCH",
                module_name="app.main",
                extra={
                    "job": job,
                    "scanned": stats.scanned,
                    "sorted": stats.sorted_count,
                    "skipped": stats.skipped,
                    "failed": stats.failed,
                },
            )
        except GmailConfigError as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code=exc.error_code,
                detail=exc.message,
                operation="メール振り分け",
                method_name="run",
                job_id="unknown",
            )
            return 1
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="メール振り分け",
                method_name="run",
                job_id="unknown",
            )
            return 1
        return 0 if stats.failed == 0 or stats.sorted_count > 0 else 1

    if job == "ingest":
        try:
            run_ingest_batch = _load_batch_callable(
                "BAT-002",
                "gmail_ingest",
                "run_ingest_batch",
                clear_modules=("db", "summarizer", "gmail_ingest"),
            )
            stats = run_ingest_batch()
        except GmailConfigError as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code=exc.error_code,
                detail=exc.message,
                operation="メール取込",
                method_name="run",
                job_id="unknown",
                function_id="BAT-002",
                module_name="BAT-002.gmail_ingest",
            )
            return 1
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="メール取込",
                method_name="run",
                job_id="unknown",
                function_id="BAT-002",
                module_name="BAT-002.gmail_ingest",
            )
            return 1
        return 0 if stats.failed == 0 or stats.ingested > 0 else 1

    if job == "manual_register":
        try:
            run_manual_register_batch = _load_batch_callable(
                "BAT-002",
                "manual_register",
                "run_manual_register_batch",
                clear_modules=("db", "summarizer", "manual_register", "gmail_ingest"),
            )
            result = run_manual_register_batch()
            log_event(
                logger,
                logging.INFO,
                event="batch.run.finished",
                message="Batch job finished: manual_register",
                operation="バッチジョブ完了",
                method_name="run",
                job_id="run",
                function_id="BATCH",
                module_name="app.main",
                extra={
                    "job": job,
                    "ok": result.ok,
                    "email_id": str(result.email_id),
                    "entity_id": str(result.entity_id) if result.entity_id else None,
                    "email_status": result.email_status,
                },
            )
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="手動登録",
                method_name="run",
                job_id="unknown",
                function_id="BAT-002",
                module_name="BAT-002.manual_register",
            )
            return 1
        return 0 if result.ok else 1

    if job == "pipeline":
        # 基本セット: BAT-001 → BAT-002 → BAT-006 → BAT-003 →（任意 BAT-004）→ BAT-008
        import time
        import uuid as _uuid

        pipeline_job_id = f"pipeline_{_uuid.uuid4().hex[:12]}"
        pipeline_started = time.perf_counter()
        step_timings: list[dict[str, object]] = []

        def _run_step(step_name: str, *args: object, **kwargs: object) -> int:
            step_started = time.perf_counter()
            code = run(step_name, **kwargs)  # type: ignore[arg-type]
            step_ms = int((time.perf_counter() - step_started) * 1000)
            step_timings.append(
                {
                    "step": step_name,
                    "exit_code": code,
                    "duration_ms": step_ms,
                }
            )
            log_event(
                logger,
                logging.INFO,
                event="batch.pipeline.step_finished",
                message=f"Pipeline step finished: {step_name}",
                operation="パイプライン工程完了",
                method_name="run",
                job_id=pipeline_job_id,
                function_id="BATCH",
                module_name="app.main",
                duration_ms=step_ms,
                extra={"step": step_name, "exit_code": code},
            )
            return code

        log_event(
            logger,
            logging.INFO,
            event="batch.pipeline.started",
            message="Pipeline started",
            operation="パイプライン開始",
            method_name="run",
            job_id=pipeline_job_id,
            function_id="BATCH",
            module_name="app.main",
            extra={
                "steps": ["sort", "ingest", "cleanup", "match", "ai_judge?", "reply_sync"],
            },
        )

        failed_step: str | None = None
        if _run_step("sort") != 0:
            failed_step = "sort"
        elif _run_step("ingest") != 0:
            failed_step = "ingest"
        elif _run_step("cleanup") != 0:
            failed_step = "cleanup"
        elif _run_step("match", match_trigger="batch_auto") != 0:
            failed_step = "match"
        else:
            if _is_ai_assist_enabled():
                if _run_step("ai_judge") != 0:
                    failed_step = "ai_judge"
            if failed_step is None and _run_step("reply_sync") != 0:
                failed_step = "reply_sync"

        total_ms = int((time.perf_counter() - pipeline_started) * 1000)
        log_event(
            logger,
            logging.INFO if failed_step is None else logging.ERROR,
            event="batch.pipeline.finished",
            message="Pipeline finished",
            operation="パイプライン完了",
            method_name="run",
            job_id=pipeline_job_id,
            function_id="BATCH",
            module_name="app.main",
            duration_ms=total_ms,
            extra={
                "status": "ok" if failed_step is None else "failed",
                "failed_step": failed_step,
                "total_duration_ms": total_ms,
                "steps": step_timings,
            },
        )
        return 0 if failed_step is None else 1

    if job == "cleanup":
        try:
            run_cleanup_batch = _load_batch_callable(
                "BAT-006",
                "cleanup",
                "run_cleanup_batch",
                clear_modules=("cleanup_db", "retention", "cleanup"),
            )
            run_cleanup_batch()
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="取込データ削除",
                method_name="run",
                job_id="unknown",
                function_id="BAT-006",
                module_name="BAT-006.cleanup",
            )
            return 1
        return 0

    if job == "match":
        try:
            run_match_score_batch = _load_batch_callable(
                "BAT-003",
                "match_score",
                "run_match_score_batch",
                clear_modules=("db", "scorer", "google_routes", "commute", "match_score"),
            )
            stats = run_match_score_batch(trigger=match_trigger)  # type: ignore[arg-type]
            log_event(
                logger,
                logging.INFO,
                event="batch.run.finished",
                message="Batch job finished: match",
                operation="バッチジョブ完了",
                method_name="run",
                job_id="run",
                function_id="BATCH",
                module_name="app.main",
                extra={
                    "job": job,
                    "match_count": stats.match_count,
                    "scored_count": getattr(stats, "scored_count", None),
                    "reused_count": getattr(stats, "reused_count", None),
                    "talent_count": stats.talent_count,
                    "project_count": stats.project_count,
                },
            )
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="ルールスコア採点",
                method_name="run",
                job_id="unknown",
                function_id="BAT-003",
                module_name="BAT-003.match_score",
            )
            return 1
        return 0 if stats.match_count > 0 else 1

    if job == "talent_propose":
        try:
            import os

            run_talent_propose_batch = _load_batch_callable(
                "BAT-007",
                "talent_propose",
                "run_talent_propose_batch",
                clear_modules=("talent_propose",),
            )
            match_ids_raw = os.environ.get("OUTREACH_MATCH_IDS", "").strip()
            if not match_ids_raw:
                raise ValueError("OUTREACH_MATCH_IDS is required for talent_propose")
            match_ids = [UUID(part) for part in match_ids_raw.split(",") if part.strip()]
            body_by_match_id: dict[UUID, str] | None = None
            body_text: str | None = None
            to_address: str | None = None
            cc_addresses: list[str] | None = None
            to_by_match_id: dict[UUID, str] | None = None
            cc_by_match_id: dict[UUID, list[str]] | None = None
            import json
            from pathlib import Path

            bodies_json = os.environ.get("OUTREACH_BODIES_JSON", "").strip()
            bodies_file = os.environ.get("OUTREACH_BODIES_FILE", "").strip()
            body_env = os.environ.get("OUTREACH_BODY_TEXT", "").strip()
            to_env = os.environ.get("OUTREACH_TO_ADDRESS", "").strip()
            cc_env = os.environ.get("OUTREACH_CC_ADDRESSES", "").strip()
            pending_file = Path(__file__).resolve().parents[1] / "tmp" / "pending_talent_propose_bodies.json"
            raw: object | None = None
            pending_used = False
            if body_env:
                body_text = body_env
            if to_env:
                to_address = to_env
            if cc_env:
                cc_addresses = [part.strip() for part in cc_env.replace(";", ",").split(",") if part.strip()]
            if bodies_json:
                raw = json.loads(bodies_json)
            elif bodies_file:
                raw = json.loads(Path(bodies_file).read_text(encoding="utf-8"))
            elif pending_file.is_file():
                raw = json.loads(pending_file.read_text(encoding="utf-8"))
                pending_used = True
            if raw is not None:
                if not isinstance(raw, dict):
                    raise ValueError("OUTREACH_BODIES_JSON/FILE must contain a JSON object")
                by_match_raw = raw.get("by_match_id")
                if isinstance(by_match_raw, dict) and by_match_raw:
                    body_by_match_id = {}
                    to_by_match_id = {}
                    cc_by_match_id = {}
                    for key, value in by_match_raw.items():
                        mid = UUID(str(key))
                        if isinstance(value, dict):
                            body_val = value.get("body")
                            if isinstance(body_val, str) and body_val.strip():
                                body_by_match_id[mid] = body_val
                            to_val = value.get("to_address")
                            if isinstance(to_val, str) and to_val.strip():
                                to_by_match_id[mid] = to_val.strip()
                            cc_val = value.get("cc_addresses")
                            if isinstance(cc_val, list):
                                cc_by_match_id[mid] = [
                                    str(addr).strip() for addr in cc_val if str(addr).strip()
                                ]
                        elif isinstance(value, str) and value.strip():
                            body_by_match_id[mid] = value
                    if not body_by_match_id:
                        body_by_match_id = None
                    if not to_by_match_id:
                        to_by_match_id = None
                    if not cc_by_match_id:
                        cc_by_match_id = None
                elif "body" in raw and isinstance(raw.get("body"), str) and raw["body"].strip():
                    body_text = str(raw["body"])
                else:
                    body_by_match_id = {
                        UUID(str(key)): str(value)
                        for key, value in raw.items()
                        if str(key) not in {"body", "to_address", "cc_addresses", "by_match_id"}
                        and isinstance(value, str)
                    }
                if isinstance(raw.get("to_address"), str) and str(raw["to_address"]).strip():
                    to_address = str(raw["to_address"]).strip()
                if isinstance(raw.get("cc_addresses"), list):
                    cc_addresses = [
                        str(addr).strip() for addr in raw["cc_addresses"] if str(addr).strip()
                    ]
            try:
                stats = run_talent_propose_batch(
                    match_ids=match_ids,
                    body_text=body_text,
                    body_by_match_id=body_by_match_id,
                    to_address=to_address,
                    cc_addresses=cc_addresses,
                    to_by_match_id=to_by_match_id,
                    cc_by_match_id=cc_by_match_id,
                )
            finally:
                if pending_used:
                    try:
                        pending_file.unlink(missing_ok=True)
                    except OSError:
                        pass
            log_event(
                logger,
                logging.INFO,
                event="batch.run.finished",
                message="Batch job finished: talent_propose",
                operation="バッチジョブ完了",
                method_name="run",
                job_id="run",
                function_id="BATCH",
                module_name="app.main",
                extra={"job": job, "sent": stats.sent, "skipped": stats.skipped, "failed": stats.failed},
            )
            print(
                json.dumps(
                    {"sent": stats.sent, "skipped": stats.skipped, "failed": stats.failed},
                    ensure_ascii=False,
                )
            )
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="要員提案送信",
                method_name="run",
                job_id="unknown",
                function_id="BAT-007",
                module_name="BAT-007.talent_propose",
            )
            return 1
        return 0 if stats.failed == 0 else 1

    if job == "reply_sync":
        try:
            run_reply_sync_batch = _load_batch_callable(
                "BAT-008",
                "reply_sync",
                "run_reply_sync_batch",
                clear_modules=("reply_sync",),
            )
            stats = run_reply_sync_batch()
            log_event(
                logger,
                logging.INFO,
                event="batch.run.finished",
                message="Batch job finished: reply_sync",
                operation="バッチジョブ完了",
                method_name="run",
                job_id="run",
                function_id="BATCH",
                module_name="app.main",
                extra={"job": job, "new_replies": stats.new_replies, "failed": stats.failed},
            )
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="返信同期",
                method_name="run",
                job_id="unknown",
                function_id="BAT-008",
                module_name="BAT-008.reply_sync",
            )
            return 1
        return 0 if stats.failed == 0 else 1

    if job == "ai_judge":
        try:
            import os

            run_ai_judge_batch = _load_batch_callable(
                "BAT-004",
                "ai_judge",
                "run_ai_judge_batch",
                clear_modules=("ai_judge",),
            )
            run_id_raw = os.environ.get("AI_JUDGE_MATCH_RUN_ID", "").strip()
            project_id_raw = os.environ.get("AI_JUDGE_PROJECT_ID", "").strip()
            match_ids_raw = os.environ.get("AI_JUDGE_MATCH_IDS", "").strip()
            match_ids = (
                [UUID(part) for part in match_ids_raw.split(",") if part.strip()] if match_ids_raw else None
            )
            stats = run_ai_judge_batch(
                match_run_id=UUID(run_id_raw) if run_id_raw else None,
                project_id=UUID(project_id_raw) if project_id_raw else None,
                match_ids=match_ids,
            )
            log_event(
                logger,
                logging.INFO,
                event="batch.run.finished",
                message="Batch job finished: ai_judge",
                operation="バッチジョブ完了",
                method_name="run",
                job_id="run",
                function_id="BATCH",
                module_name="app.main",
                extra={
                    "job": job,
                    "ai_judged": stats.ai_judged,
                    "ng_zeroed": stats.ng_zeroed,
                    "hard_rejected": getattr(stats, "hard_rejected", 0),
                },
            )
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="AI判定",
                method_name="run",
                job_id="unknown",
                function_id="BAT-004",
                module_name="BAT-004.ai_judge",
            )
            return 1
        return 0 if stats.failed == 0 else 1

    if job == "project_propose":
        try:
            import os

            run_project_propose_batch = _load_batch_callable(
                "BAT-009",
                "project_propose",
                "run_project_propose_batch",
                clear_modules=("project_propose",),
            )
            project_id_raw = os.environ.get("OUTREACH_PROJECT_ID", "").strip()
            match_ids_raw = os.environ.get("OUTREACH_MATCH_IDS", "").strip()
            if not project_id_raw or not match_ids_raw:
                raise ValueError("OUTREACH_PROJECT_ID and OUTREACH_MATCH_IDS are required")
            match_ids = [UUID(part) for part in match_ids_raw.split(",") if part.strip()]
            body_text: str | None = None
            to_address: str | None = None
            cc_addresses: list[str] | None = None
            import json
            from pathlib import Path

            bodies_json = os.environ.get("OUTREACH_BODIES_JSON", "").strip()
            bodies_file = os.environ.get("OUTREACH_BODIES_FILE", "").strip()
            body_env = os.environ.get("OUTREACH_BODY_TEXT", "").strip()
            to_env = os.environ.get("OUTREACH_TO_ADDRESS", "").strip()
            cc_env = os.environ.get("OUTREACH_CC_ADDRESSES", "").strip()
            pending_file = Path(__file__).resolve().parents[1] / "tmp" / "pending_project_propose_bodies.json"
            raw: object | None = None
            pending_used = False
            if body_env:
                body_text = body_env
            if to_env:
                to_address = to_env
            if cc_env:
                cc_addresses = [part.strip() for part in cc_env.replace(";", ",").split(",") if part.strip()]
            if bodies_json:
                raw = json.loads(bodies_json)
            elif bodies_file:
                raw = json.loads(Path(bodies_file).read_text(encoding="utf-8"))
            elif pending_file.is_file():
                raw = json.loads(pending_file.read_text(encoding="utf-8"))
                pending_used = True
            if raw is not None:
                if not isinstance(raw, dict):
                    raise ValueError("OUTREACH_BODIES_JSON/FILE must contain a JSON object")
                if "body" in raw and isinstance(raw.get("body"), str) and raw["body"].strip():
                    body_text = str(raw["body"])
                if isinstance(raw.get("to_address"), str) and str(raw["to_address"]).strip():
                    to_address = str(raw["to_address"]).strip()
                if isinstance(raw.get("cc_addresses"), list):
                    cc_addresses = [
                        str(addr).strip() for addr in raw["cc_addresses"] if str(addr).strip()
                    ]
            try:
                stats = run_project_propose_batch(
                    project_id=UUID(project_id_raw),
                    match_ids=match_ids,
                    body_text=body_text,
                    to_address=to_address,
                    cc_addresses=cc_addresses,
                )
            finally:
                if pending_used:
                    try:
                        pending_file.unlink(missing_ok=True)
                    except OSError:
                        pass
            if stats.failed or stats.sent == 0:
                raise RuntimeError(stats.errors[0] if stats.errors else "project propose failed")
            log_event(
                logger,
                logging.INFO,
                event="batch.run.finished",
                message="Batch job finished: project_propose",
                operation="バッチジョブ完了",
                method_name="run",
                job_id="run",
                function_id="BATCH",
                module_name="app.main",
                extra={"job": job, "sent": stats.sent},
            )
        except Exception as exc:
            log_error_event(
                logger,
                event="batch.job.failed",
                error_code="ERR-0030",
                detail=str(exc),
                operation="案件提案送信",
                method_name="run",
                job_id="unknown",
                function_id="BAT-009",
                module_name="BAT-009.project_propose",
            )
            return 1
        return 0

    log_error_event(
        logger,
        event="batch.job.failed",
        error_code="ERR-0028",
        detail=f"Unknown batch job: {job}",
        operation="バッチ起動",
        method_name="run",
        job_id="unknown",
        function_id="BATCH",
        module_name="app.main",
    )
    return 1


def main() -> None:
    """CLI エントリポイント。"""
    logger = configure_logging()
    log_event(
        logger,
        logging.INFO,
        event="batch.boot",
        message="Batch runner started",
        operation="バッチ起動",
        method_name="main",
        job_id="boot",
        function_id="BATCH",
        module_name="app.main",
    )
    args = parse_args()
    exit_code = run(args.job)
    logging.shutdown()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
