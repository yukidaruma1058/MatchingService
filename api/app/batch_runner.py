"""API からバッチコンテナ相当のジョブを subprocess で起動する。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_BATCH_ROOT = Path(__file__).resolve().parents[2] / "batch"
BATCH_ROOT = Path(os.environ.get("BATCH_ROOT", str(_DEFAULT_BATCH_ROOT)))
BATCH_LOG_PATH = Path(os.environ.get("BATCH_LOG_PATH", "log/batch.log"))


class BatchRunTimeoutError(TimeoutError):
    """バッチ実行がタイムアウトした。"""


@dataclass(frozen=True)
class BatchRunResult:
    job: str
    exit_code: int
    stdout: str
    stderr: str


def read_last_batch_error() -> dict[str, str] | None:
    """バッチログから直近の ERROR 行の error_code / error_message を返す。"""
    if not BATCH_LOG_PATH.is_file():
        return None
    for line in reversed(BATCH_LOG_PATH.read_text(encoding="utf-8").splitlines()):
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
    if not BATCH_ROOT.is_dir():
        raise FileNotFoundError(f"Batch root not found: {BATCH_ROOT}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BATCH_ROOT)
    env.setdefault("BATCH_LOG_PATH", str(BATCH_LOG_PATH))
    if extra_env:
        env.update(extra_env)

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
    )
