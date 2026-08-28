"""API からバッチコンテナ相当のジョブを subprocess で起動する。"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_BATCH_ROOT = Path(__file__).resolve().parents[2] / "batch"
BATCH_ROOT = Path(os.environ.get("BATCH_ROOT", str(_DEFAULT_BATCH_ROOT)))
BATCH_LOG_PATH = Path(os.environ.get("BATCH_LOG_PATH", "log/batch.log"))

# 直近の run_batch_job 開始時点のログ末尾オフセット（古い ERROR の誤検出防止）
_last_run_log_offset: int | None = None


class BatchRunTimeoutError(TimeoutError):
    """バッチ実行がタイムアウトした。"""


@dataclass(frozen=True)
class BatchRunResult:
    job: str
    exit_code: int
    stdout: str
    stderr: str
    log_offset_before: int = 0


def _log_byte_size() -> int:
    try:
        return BATCH_LOG_PATH.stat().st_size if BATCH_LOG_PATH.is_file() else 0
    except OSError:
        return 0


def _summarize_technical_message(raw: str) -> str | None:
    """ログの技術メッセージから画面向けの短い説明を抽出する。"""
    text = (raw or "").strip()
    if not text:
        return None
    if "number of parameters must be between 0 and 65535" in text:
        return "ルール採点の処理対象が多すぎます。時間をおいて再度お試しください。"
    if "timed out" in text.lower() or "timeout" in text.lower():
        return "外部サービスへの接続がタイムアウトしました。"
    first_line = text.split("\n", 1)[0].strip()
    if len(first_line) > 200:
        return first_line[:197] + "..."
    return first_line


def read_last_batch_error(*, after_byte_offset: int | None = None) -> dict[str, str] | None:
    """バッチログから直近の ERROR 行の error_code / error_message を返す。

    after_byte_offset を指定した場合（または直近 run_batch_job の開始オフセットがある場合）は、
    そのバイト位置より後に書かれた行だけを対象にする。これにより前回実行の古い ERR-0030 を
    今回の失敗として返さない。
    """
    if not BATCH_LOG_PATH.is_file():
        return None

    offset = after_byte_offset
    if offset is None:
        offset = _last_run_log_offset

    try:
        raw = BATCH_LOG_PATH.read_bytes()
    except OSError:
        return None

    if offset is not None and offset > 0:
        # 行途中からの読みを避けるため、オフセット以降の次の改行から見る
        start = min(offset, len(raw))
        if start < len(raw) and start > 0 and raw[start - 1 : start] != b"\n":
            nl = raw.find(b"\n", start)
            start = nl + 1 if nl >= 0 else len(raw)
        chunk = raw[start:]
    else:
        chunk = raw

    try:
        text = chunk.decode("utf-8")
    except UnicodeDecodeError:
        text = chunk.decode("utf-8", errors="replace")

    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("level") != "ERROR":
            continue
        error_code = payload.get("error_code")
        if not isinstance(error_code, str) or not error_code:
            continue
        error_message = payload.get("error_message")
        if not isinstance(error_message, str) or not error_message:
            error_message = payload.get("message", "エラーが発生しました。")
        technical = payload.get("message")
        summary = _summarize_technical_message(technical) if isinstance(technical, str) else None
        if summary and summary.strip() != error_message.strip():
            # 汎用 ERR-0030 のときは具体原因を優先表示
            if error_message.strip().startswith("システムエラーが発生しました"):
                error_message = summary
            elif len(summary) <= 200:
                error_message = f"{error_message}（{summary}）"
        return {
            "error_code": error_code,
            "error_message": error_message,
        }
    return None


def run_batch_job(
    job: str,
    *,
    timeout_seconds: int = 600,
    extra_env: dict[str, str] | None = None,
) -> BatchRunResult:
    """指定ジョブをバッチエントリポイント経由で実行する。"""
    global _last_run_log_offset

    if not BATCH_ROOT.is_dir():
        raise FileNotFoundError(f"Batch root not found: {BATCH_ROOT}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BATCH_ROOT)
    env.setdefault("BATCH_LOG_PATH", str(BATCH_LOG_PATH))
    if extra_env:
        env.update(extra_env)

    log_offset_before = _log_byte_size()
    _last_run_log_offset = log_offset_before

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "app.main", job],
            cwd=BATCH_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BatchRunTimeoutError(f"Batch job timed out: {job}") from exc
    return BatchRunResult(
        job=job,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        log_offset_before=log_offset_before,
    )


def start_batch_job(
    job: str,
    *,
    extra_env: dict[str, str] | None = None,
) -> str:
    """バッチをバックグラウンド起動する（API を待たせない）。起動した job_id を返す。"""
    global _last_run_log_offset

    if not BATCH_ROOT.is_dir():
        raise FileNotFoundError(f"Batch root not found: {BATCH_ROOT}")

    import uuid

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BATCH_ROOT)
    env.setdefault("BATCH_LOG_PATH", str(BATCH_LOG_PATH))
    pipeline_job_id = (extra_env or {}).get("PIPELINE_JOB_ID") or f"pipeline_{uuid.uuid4().hex[:12]}"
    env["PIPELINE_JOB_ID"] = pipeline_job_id
    if extra_env:
        env.update(extra_env)

    _last_run_log_offset = _log_byte_size()

    subprocess.Popen(
        [sys.executable, "-m", "app.main", job],
        cwd=BATCH_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return pipeline_job_id


_BATCH_JOB_LABELS: dict[str, str] = {
    "pipeline": "メール取込パイプライン",
    "ingest": "メール取込",
    "cleanup": "取込データ削除",
    "match": "ルール採点",
    "ai_judge": "AI判定",
    "reply_sync": "返信同期",
    "talent_propose": "要員提案",
    "project_propose": "案件提案",
    "manual_register": "手動登録",
}


@dataclass(frozen=True)
class RunningBatchJob:
    pid: int
    job: str
    job_label: str


def batch_job_label(job: str) -> str:
    return _BATCH_JOB_LABELS.get(job, job)


def parse_batch_job_from_argv(argv: list[str]) -> str | None:
    """``python -m app.main <job>`` の argv からジョブ名を取り出す。"""
    for index, part in enumerate(argv):
        if part == "-m" and index + 2 < len(argv) and argv[index + 1] == "app.main":
            return argv[index + 2]
    return None


def _read_proc_cmdline(pid: int) -> list[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            return [part.decode(errors="ignore") for part in handle.read().split(b"\0") if part]
    except OSError:
        return []


def _read_proc_environ(pid: int) -> dict[str, str]:
    env: dict[str, str] = {}
    try:
        with open(f"/proc/{pid}/environ", "rb") as handle:
            for item in handle.read().split(b"\0"):
                if b"=" not in item:
                    continue
                key, value = item.split(b"=", 1)
                env[key.decode(errors="ignore")] = value.decode(errors="ignore")
    except OSError:
        return env
    return env


def _append_batch_log(entry: dict[str, object]) -> None:
    payload = dict(entry)
    payload.setdefault("timestamp", datetime.now(UTC).isoformat())
    payload.setdefault("level", "INFO")
    try:
        BATCH_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with BATCH_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError:
        return


def _log_batch_cancellation(*, job: str, pid: int, job_id: str | None) -> None:
    resolved_job_id = job_id or f"job_{pid}"
    if job == "pipeline":
        _append_batch_log(
            {
                "event": "batch.pipeline.finished",
                "job_id": resolved_job_id,
                "message": "Pipeline cancelled by user",
                "extra": {"status": "cancelled"},
            }
        )
        return
    _append_batch_log(
        {
            "event": "batch.job.cancelled",
            "job_id": resolved_job_id,
            "message": f"Batch job cancelled: {job}",
            "extra": {"job": job},
        }
    )


def list_running_batch_jobs() -> list[RunningBatchJob]:
    """実行中の ``python -m app.main`` バッチプロセス一覧。"""
    my_pid = os.getpid()
    jobs: list[RunningBatchJob] = []
    try:
        proc_ids = os.listdir("/proc")
    except OSError:
        return jobs

    for name in proc_ids:
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == my_pid:
            continue
        argv = _read_proc_cmdline(pid)
        job = parse_batch_job_from_argv(argv)
        if job is None:
            continue
        jobs.append(RunningBatchJob(pid=pid, job=job, job_label=batch_job_label(job)))

    jobs.sort(key=lambda item: item.pid)
    return jobs


def _terminate_process(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return


def _kill_process_if_alive(pid: int) -> None:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    except OSError:
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (ProcessLookupError, OSError):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, OSError):
            return


def is_batch_job_running(job: str) -> bool:
    return any(item.job == job for item in list_running_batch_jobs())


def cancel_orphaned_pipeline_jobs() -> list[str]:
    """プロセスが存在しないのにログ上だけ未完了の pipeline をキャンセル済みにする。"""
    from app.pipeline_progress import find_latest_active_pipeline_job_id

    job_id = find_latest_active_pipeline_job_id()
    if not job_id:
        return []
    if is_batch_job_running("pipeline"):
        return []
    _log_batch_cancellation(job="pipeline", pid=0, job_id=job_id)
    return [job_id]


def stop_running_batch_jobs(*, job: str | None = None) -> list[RunningBatchJob]:
    """実行中バッチを停止する。``job`` 指定時はそのジョブのみ。"""
    targets = list_running_batch_jobs()
    if job is not None:
        targets = [item for item in targets if item.job == job]

    stopped: list[RunningBatchJob] = []
    for item in targets:
        env = _read_proc_environ(item.pid)
        job_id = (env.get("PIPELINE_JOB_ID") or "").strip() or None
        _terminate_process(item.pid)
        _log_batch_cancellation(job=item.job, pid=item.pid, job_id=job_id)
        stopped.append(item)

    if stopped:
        time.sleep(0.5)
        for item in stopped:
            _kill_process_if_alive(item.pid)

    return stopped


def stop_all_batch_jobs() -> tuple[list[RunningBatchJob], list[str]]:
    """実行中プロセスを停止し、ログだけ残った pipeline も解除する。"""
    stopped = stop_running_batch_jobs()
    orphaned = cancel_orphaned_pipeline_jobs()
    return stopped, orphaned
