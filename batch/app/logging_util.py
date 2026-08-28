"""バッチ共通の構造化ログ出力（JSON Lines 形式）。

共通機能設計書に準拠し、``function_id`` / ``event`` / ``operation`` などを
1 行 JSON としてログファイルへ出力する。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.error_messages import resolve_error_message

_LOGGER_NAME = "batch"
_logging_configured = False


class JsonLineFormatter(logging.Formatter):
    """LogRecord を共通ログスキーマの JSON 1 行へ変換する。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "service": getattr(record, "service", "batch"),
            "function_id": getattr(record, "function_id", "BATCH"),
            "module": getattr(record, "module_name", record.module),
            "method": getattr(record, "method_name", record.funcName),
            "operation": getattr(record, "operation", record.getMessage()),
            "event": getattr(record, "event", "batch.log"),
            "message": record.getMessage(),
        }
        # 任意フィールド（存在する場合のみ出力）
        for key in ("job_id", "gmail_message_id", "error_code", "error_message", "duration_ms", "extra"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> logging.Logger:
    """ログファイルへ JSON Lines を出力するロガーを初期化して返す（1プロセス1回）。"""
    global _logging_configured
    logger = logging.getLogger(_LOGGER_NAME)
    if _logging_configured:
        return logger

    log_path = Path(settings.batch_log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(JsonLineFormatter())
    handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    _logging_configured = True
    return logger


def get_batch_logger() -> logging.Logger:
    """初期化済みバッチロガーを返す。"""
    return configure_logging()


def log_event(
    logger: logging.Logger,
    level: int,
    *,
    event: str,
    message: str,
    operation: str,
    method_name: str,
    job_id: str,
    function_id: str = "BATCH",
    module_name: str = "app.main",
    **fields: Any,
) -> None:
    """共通ログスキーマに沿ったイベントログを 1 件出力する。"""
    extra = {
        "event": event,
        "operation": operation,
        "method_name": method_name,
        "module_name": module_name,
        "function_id": function_id,
        "job_id": job_id,
        **fields,
    }
    logger.log(level, message, extra=extra)
    for handler in logger.handlers + logging.getLogger().handlers:
        if hasattr(handler, "flush"):
            handler.flush()


def log_error_event(
    logger: logging.Logger,
    *,
    event: str,
    error_code: str,
    operation: str,
    method_name: str,
    job_id: str,
    detail: str = "",
    error_message: str | None = None,
    message: str | None = None,
    function_id: str = "BATCH",
    module_name: str = "app.main",
    **fields: Any,
) -> None:
    """エラーコードと利用者向けメッセージをセットでログ出力する。"""
    catalog_message = error_message or resolve_error_message(error_code, detail=detail)
    technical_message = (message or detail or catalog_message).strip()
    log_event(
        logger,
        logging.ERROR,
        event=event,
        message=technical_message,
        operation=operation,
        method_name=method_name,
        job_id=job_id,
        function_id=function_id,
        module_name=module_name,
        error_code=error_code,
        error_message=catalog_message,
        **fields,
    )
