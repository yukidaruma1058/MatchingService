"""バッチ手動起動 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.batch_purge import purge_all_ingest_data_via_batch, purge_summary_message
from app.batch_runner import (
    BatchRunTimeoutError,
    list_running_batch_jobs,
    read_last_batch_error,
    run_batch_job,
    start_batch_job,
    stop_running_batch_jobs,
    stop_all_batch_jobs,
)
from app.pipeline_progress import find_latest_active_pipeline_job_id, parse_pipeline_progress
from app.schemas import (
    BatchRunResponse,
    BatchRunningResponse,
    BatchStopResponse,
    PipelineProgressResponse,
    PurgeIngestResponse,
)


router = APIRouter(prefix="/api/batches", tags=["batches"])


def _raise_batch_error(
    *,
    fallback_code: str = "ERR-0030",
    fallback_message: str,
    after_byte_offset: int | None = None,
) -> None:
    error = read_last_batch_error(after_byte_offset=after_byte_offset)
    if error:
        raise HTTPException(status_code=500, detail=error)
    raise HTTPException(
        status_code=500,
        detail={
            "error_code": fallback_code,
            "error_message": fallback_message,
        },
    )


def _progress_response(job_id: str) -> PipelineProgressResponse:
    progress = parse_pipeline_progress(job_id)
    return PipelineProgressResponse(**progress.to_dict())


@router.post("/gmail-pipeline", response_model=BatchRunResponse, status_code=202)
def trigger_gmail_pipeline() -> BatchRunResponse:
    """BAT-002（取込）→ BAT-006 → BAT-003 →（任意 BAT-004）→ BAT-008 をバックグラウンド実行する。"""
    try:
        job_id = start_batch_job("pipeline")
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-0030",
                "error_message": str(exc),
            },
        ) from exc

    return BatchRunResponse(
        status="running",
        job="pipeline",
        job_id=job_id,
        message="メール取込パイプラインを開始しました",
    )


@router.get("/running", response_model=BatchRunningResponse)
def get_running_batch_jobs() -> BatchRunningResponse:
    """実行中のバッチプロセス一覧を返す。"""
    jobs = list_running_batch_jobs()
    return BatchRunningResponse(
        running=bool(jobs),
        jobs=[{"pid": item.pid, "job": item.job, "job_label": item.job_label} for item in jobs],
    )


@router.post("/stop", response_model=BatchStopResponse)
def stop_batch_jobs() -> BatchStopResponse:
    """実行中のバッチ（取込・採点・削除など）をすべて停止する。"""
    stopped, orphaned = stop_all_batch_jobs()
    if stopped:
        labels = "、".join(dict.fromkeys(item.job_label for item in stopped))
        return BatchStopResponse(
            stopped=True,
            killed_count=len(stopped),
            jobs=[{"pid": item.pid, "job": item.job, "job_label": item.job_label} for item in stopped],
            message=f"{labels} を停止しました",
        )
    if orphaned:
        return BatchStopResponse(
            stopped=True,
            killed_count=0,
            jobs=[{"pid": 0, "job": "pipeline", "job_label": "メール取込パイプライン"}],
            message="メール取込の実行表示を解除しました（プロセスは既に終了していました）",
        )
    return BatchStopResponse(
        stopped=False,
        killed_count=0,
        jobs=[],
        message="停止対象の処理はありません",
    )


@router.post("/purge-ingest-data", response_model=PurgeIngestResponse)
def purge_all_ingest_data() -> PurgeIngestResponse:
    """取込メール・人材・案件・採点・提案データをすべて削除する（企業マスタ等は残す）。"""
    try:
        result = purge_all_ingest_data_via_batch(skip_drive=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-0030",
                "error_message": f"取込データの削除に失敗しました: {exc}",
            },
        ) from exc

    return PurgeIngestResponse(
        deleted_emails=int(result["deleted_emails"]),
        deleted_talents=int(result["deleted_talents"]),
        deleted_projects=int(result["deleted_projects"]),
        deleted_matches=int(result["deleted_matches"]),
        deleted_match_runs=int(result["deleted_match_runs"]),
        deleted_outreach_messages=int(result["deleted_outreach_messages"]),
        deleted_outreach_replies=int(result["deleted_outreach_replies"]),
        deleted_talent_skill_sheets=int(result["deleted_talent_skill_sheets"]),
        message=purge_summary_message(result),
    )


@router.get("/gmail-pipeline/progress", response_model=PipelineProgressResponse)
def get_gmail_pipeline_progress(
    job_id: str | None = Query(default=None, description="pipeline job id。省略時は実行中の最新を返す"),
) -> PipelineProgressResponse:
    """メール取込パイプラインの進捗を返す。"""
    resolved_job_id = job_id or find_latest_active_pipeline_job_id()
    if not resolved_job_id:
        return PipelineProgressResponse(job_id=job_id or "", status="not_found")
    return _progress_response(resolved_job_id)


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
        _raise_batch_error(
            fallback_message="過去データ削除に失敗しました。",
            after_byte_offset=result.log_offset_before,
        )

    return {
        "status": "ok",
        "job": "cleanup",
        "message": "過去データ削除が完了しました",
    }
