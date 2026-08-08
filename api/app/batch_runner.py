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
) -> None:
    """バッチをバックグラウンド起動する（API を待たせない）。"""
    global _last_run_log_offset

    if not BATCH_ROOT.is_dir():
        raise FileNotFoundError(f"Batch root not found: {BATCH_ROOT}")

    env = os.environ.copy()
    env["PYTHONPATH"] = str(BATCH_ROOT)
    env.setdefault("BATCH_LOG_PATH", str(BATCH_LOG_PATH))
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
