"""バッチ手動起動 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.batch_runner import BatchRunTimeoutError, read_last_batch_error, run_batch_job


class BatchRunResponse(BaseModel):
    status: str
    job: str
    message: str


router = APIRouter(prefix="/api/batches", tags=["batches"])


def _raise_batch_error(*, fallback_code: str = "ERR-0030", fallback_message: str) -> None:
    error = read_last_batch_error()
    if error:
        raise HTTPException(status_code=500, detail=error)
    raise HTTPException(
        status_code=500,
        detail={
            "error_code": fallback_code,
            "error_message": fallback_message,
        },
    )


@router.post("/gmail-pipeline", response_model=BatchRunResponse)
def trigger_gmail_pipeline() -> dict[str, str]:
    """BAT-001（振り分け）→ BAT-002（取込）→ BAT-006（削除）→ BAT-003（ルール採点）を連続実行する。"""
    try:
        result = run_batch_job("pipeline", timeout_seconds=900)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-0030",
                "error_message": str(exc),
            },
        ) from exc
    except BatchRunTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error_code": "ERR-0029",
                "error_message": "外部サービスへの接続がタイムアウトしました。",
            },
        ) from exc

    if result.exit_code != 0:
        _raise_batch_error(fallback_message="メール振り分け・取込・ルール採点に失敗しました。")

    return {
        "status": "ok",
        "job": "pipeline",
        "message": "メール振り分け・取込・ルール採点が完了しました",
    }


@router.post("/ingest-cleanup", response_model=BatchRunResponse)
def trigger_ingest_cleanup() -> dict[str, str]:
    """BAT-006（過去取込データ削除）を手動実行する。"""
    try:
        result = run_batch_job("cleanup")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-0030",
                "error_message": str(exc),
            },
        ) from exc
    except BatchRunTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "error_code": "ERR-0029",
                "error_message": "外部サービスへの接続がタイムアウトしました。",
            },
        ) from exc

    if result.exit_code != 0:
        _raise_batch_error(fallback_message="過去データ削除に失敗しました。")

    return {
        "status": "ok",
        "job": "cleanup",
        "message": "過去データ削除が完了しました",
    }
