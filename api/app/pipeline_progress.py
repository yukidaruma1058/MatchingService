"""メール取込パイプラインの進捗を batch.log から解析する。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.batch_runner import BATCH_LOG_PATH, is_batch_job_running

_STEP_META: dict[str, dict[str, Any]] = {
    "ingest_talent": {"label": "人材メール取込", "weight": 0.18, "default_seconds": 600},
    "ingest_project": {"label": "案件メール取込", "weight": 0.18, "default_seconds": 600},
    "ingest_skill_sheets": {"label": "スキルシート取込", "weight": 0.04, "default_seconds": 120},
    "cleanup": {"label": "古い取込データ削除", "weight": 0.05, "default_seconds": 30},
    "match": {"label": "ルール採点", "weight": 0.35, "default_seconds": 300},
    "ai_judge": {"label": "AI判定", "weight": 0.05, "default_seconds": 180},
    "reply_sync": {"label": "返信同期", "weight": 0.15, "default_seconds": 60},
    "ingest": {"label": "メール取込・AI要約", "weight": 0.40, "default_seconds": 900},
}
_INGEST_SUB_WEIGHTS = {
    "list": 0.05,
    "fetch": 0.15,
    "ai": 0.55,
    "persist": 0.25,
}
_LABEL_TYPE_TO_STEP = {
    "talent": "ingest_talent",
    "project": "ingest_project",
}


@dataclass
class PipelineStepProgress:
    id: str
    label: str
    status: str = "pending"
    progress_percent: int = 0
    elapsed_seconds: int = 0
    eta_seconds: int | None = None
    eta_label: str | None = None
    detail: str | None = None
    weight: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "progress_percent": self.progress_percent,
            "elapsed_seconds": self.elapsed_seconds,
            "eta_seconds": self.eta_seconds,
            "eta_label": self.eta_label,
            "detail": self.detail,
            "weight": self.weight,
        }


@dataclass
class _StepRuntime:
    status: str = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    listed: int = 0
    targets: int = 0
    fetch_done: int = 0
    fetch_total: int = 0
    ai_done: int = 0
    ai_total: int = 0
    persist_done: int = 0
    persist_total: int = 0
    skill_total: int = 0
    skill_done: int = 0
    detail: str | None = None


@dataclass
class PipelineProgress:
    job_id: str
    status: str = "not_found"
    phase: str = "starting"
    phase_label: str = "準備中"
    current_step: int = 0
    total_steps: int = 0
    progress_percent: int = 0
    processed_messages: int = 0
    total_messages: int | None = None
    ingested: int = 0
    skipped: int = 0
    failed: int = 0
    started_at: str | None = None
    updated_at: str | None = None
    elapsed_seconds: int = 0
    eta_seconds: int | None = None
    eta_label: str | None = None
    total_estimated_seconds: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    detail: str | None = None
    steps: list[PipelineStepProgress] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "phase": self.phase,
            "phase_label": self.phase_label,
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "progress_percent": self.progress_percent,
            "processed_messages": self.processed_messages,
            "total_messages": self.total_messages,
            "ingested": self.ingested,
            "skipped": self.skipped,
            "failed": self.failed,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "elapsed_seconds": self.elapsed_seconds,
            "eta_seconds": self.eta_seconds,
            "eta_label": self.eta_label,
            "total_estimated_seconds": self.total_estimated_seconds,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "detail": self.detail,
            "steps": [step.to_dict() for step in self.steps],
        }


def _parse_ts(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_eta(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    if seconds <= 0:
        return "まもなく完了"
    minutes = max(1, round(seconds / 60))
    if minutes < 60:
        return f"約{minutes}分"
    hours = minutes // 60
    rem = minutes % 60
    if rem == 0:
        return f"約{hours}時間"
    return f"約{hours}時間{rem}分"


def _iter_log_rows(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.is_file():
        return []
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def find_latest_active_pipeline_job_id(*, log_path: Path | None = None) -> str | None:
    """未完了の最新 pipeline job_id を返す。"""
    path = log_path or BATCH_LOG_PATH
    latest_started: tuple[datetime, str] | None = None
    finished_after: dict[str, datetime] = {}

    for row in _iter_log_rows(path):
        event = row.get("event")
        job_id = row.get("job_id")
        if not isinstance(job_id, str) or not job_id.startswith("pipeline_"):
            continue
        ts = _parse_ts(row.get("timestamp"))
        if ts is None:
            continue
        if event == "batch.pipeline.started":
            if latest_started is None or ts >= latest_started[0]:
                latest_started = (ts, job_id)
        elif event == "batch.pipeline.finished":
            prev = finished_after.get(job_id)
            if prev is None or ts >= prev:
                finished_after[job_id] = ts

    if latest_started is None:
        return None
    started_at, job_id = latest_started
    finished_at = finished_after.get(job_id)
    if finished_at is not None and finished_at >= started_at:
        return None
    return job_id


def _normalize_weights(step_ids: list[str]) -> dict[str, float]:
    raw = {step_id: float(_STEP_META.get(step_id, {}).get("weight", 0.1)) for step_id in step_ids}
    total = sum(raw.values()) or 1.0
    return {step_id: weight / total for step_id, weight in raw.items()}


def _ingest_step_progress(state: _StepRuntime) -> tuple[int, str | None]:
    if state.status == "completed":
        return 100, state.detail
    if state.status == "pending":
        return 0, None

    if state.skill_total > 0:
        ratio = min(1.0, state.skill_done / max(1, state.skill_total))
        detail = f"スキルシート {state.skill_done}/{state.skill_total} 件"
        pct = max(1, min(99, int(round(ratio * 100))))
        return pct, detail

    total = state.targets or state.persist_total or state.fetch_total or state.listed
    if total <= 0 and state.status == "running":
        return 5, state.detail or "準備中"

    fetch_total = state.fetch_total or total
    ai_total = state.ai_total or state.fetch_done or fetch_total
    persist_total = state.persist_total or state.targets or total

    fetch_ratio = min(1.0, state.fetch_done / max(1, fetch_total))
    ai_ratio = min(1.0, state.ai_done / max(1, ai_total))
    persist_ratio = min(1.0, state.persist_done / max(1, persist_total))

    pct_float = (
        _INGEST_SUB_WEIGHTS["list"] * (1.0 if state.listed or state.targets else 0.0)
        + _INGEST_SUB_WEIGHTS["fetch"] * fetch_ratio
        + _INGEST_SUB_WEIGHTS["ai"] * ai_ratio
        + _INGEST_SUB_WEIGHTS["persist"] * persist_ratio
    )
    pct_int = max(1, min(99, int(round(pct_float * 100))))

    if state.persist_done < persist_total:
        if state.ai_done < ai_total:
            detail = f"AI要約 {state.ai_done}/{ai_total} 件"
        elif state.fetch_done < fetch_total:
            detail = f"本文取得 {state.fetch_done}/{fetch_total} 件"
        else:
            detail = f"登録 {state.persist_done}/{persist_total} 件"
    else:
        detail = state.detail or f"対象 {total} 件"
    return pct_int, detail


def _generic_running_progress(
    state: _StepRuntime, *, default_seconds: int, now: datetime
) -> tuple[int, str | None]:
    if state.started_at is None:
        return 5, state.detail or "実行中"
    elapsed = max(0, int((now - state.started_at).total_seconds()))
    if elapsed <= 0:
        return 5, state.detail or "実行中"
    ratio = min(0.95, elapsed / max(1, default_seconds))
    pct = max(5, min(95, int(round(ratio * 100))))
    return pct, state.detail or "実行中"


def _estimate_step_eta(
    *,
    step_id: str,
    state: _StepRuntime,
    progress_percent: int,
    now: datetime,
) -> int | None:
    default_seconds = int(_STEP_META.get(step_id, {}).get("default_seconds", 120))
    if state.status == "completed":
        return 0
    if state.status == "pending":
        return default_seconds
    if state.started_at is None:
        return default_seconds
    elapsed = max(0, int((now - state.started_at).total_seconds()))
    if progress_percent >= 100:
        return 0
    if progress_percent > 0:
        estimated_total = int(elapsed * 100 / progress_percent)
        return max(0, estimated_total - elapsed)
    return max(0, default_seconds - elapsed)


def parse_pipeline_progress(job_id: str, *, log_path: Path | None = None) -> PipelineProgress:
    """指定 job_id のパイプライン進捗を batch.log から組み立てる。"""
    path = log_path or BATCH_LOG_PATH
    progress = PipelineProgress(job_id=job_id, status="not_found")

    rows = [row for row in _iter_log_rows(path) if row.get("job_id") == job_id]
    if not rows:
        return progress

    progress.status = "running"
    enabled_steps: list[str] = []
    step_states: dict[str, _StepRuntime] = {}
    started_at: datetime | None = None
    updated_at: datetime | None = None
    current_step_id: str | None = None
    pipeline_status = "running"
    ingested_total = 0
    skipped_total = 0
    failed_total = 0
    total_messages = 0

    for row in rows:
        ts = _parse_ts(row.get("timestamp"))
        if ts is not None:
            if started_at is None:
                started_at = ts
            updated_at = ts

        event = row.get("event")
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}

        if event == "batch.pipeline.started":
            steps = extra.get("steps")
            if isinstance(steps, list):
                enabled_steps = [str(step) for step in steps]
            progress.status = "running"
            pipeline_status = "running"
        elif event == "batch.pipeline.step_started":
            step_id = extra.get("step")
            if isinstance(step_id, str):
                current_step_id = step_id
                state = step_states.setdefault(step_id, _StepRuntime())
                state.status = "running"
                state.started_at = ts
        elif event == "batch.pipeline.step_finished":
            step_id = extra.get("step")
            if isinstance(step_id, str):
                state = step_states.setdefault(step_id, _StepRuntime())
                state.status = "failed" if extra.get("exit_code") not in (0, None) else "completed"
                state.finished_at = ts
                duration_ms = row.get("duration_ms")
                if isinstance(duration_ms, int):
                    state.duration_ms = duration_ms
                if extra.get("exit_code") not in (0, None):
                    progress.status = "failed"
                    pipeline_status = "failed"
                    progress.error_code = (
                        row.get("error_code") if isinstance(row.get("error_code"), str) else "ERR-0030"
                    )
                    progress.error_message = (
                        row.get("error_message")
                        if isinstance(row.get("error_message"), str)
                        else f"{_STEP_META.get(step_id, {}).get('label', step_id)}で失敗しました"
                    )
        elif event == "gmail_ingest.label_targets":
            label_type = extra.get("label_type")
            step_id = _LABEL_TYPE_TO_STEP.get(str(label_type), current_step_id or "ingest")
            state = step_states.setdefault(step_id, _StepRuntime())
            if isinstance(extra.get("listed"), int):
                state.listed = max(state.listed, int(extra["listed"]))
            if isinstance(extra.get("targets"), int):
                targets = max(0, int(extra["targets"]))
                state.targets = max(state.targets, targets)
                state.persist_total = max(state.persist_total, targets)
                total_messages += targets
            source = extra.get("source_label")
            if source:
                state.detail = f"{source} を処理中"
        elif event == "gmail_ingest.fetch_progress":
            label_type = extra.get("label_type")
            step_id = _LABEL_TYPE_TO_STEP.get(str(label_type), current_step_id or "ingest")
            state = step_states.setdefault(step_id, _StepRuntime())
            if isinstance(extra.get("done"), int):
                state.fetch_done = max(state.fetch_done, int(extra["done"]))
            if isinstance(extra.get("total"), int):
                state.fetch_total = max(state.fetch_total, int(extra["total"]))
        elif event == "gmail_ingest.ai_progress":
            label_type = extra.get("label_type")
            step_id = _LABEL_TYPE_TO_STEP.get(str(label_type), current_step_id or "ingest")
            state = step_states.setdefault(step_id, _StepRuntime())
            if isinstance(extra.get("done"), int):
                state.ai_done = max(state.ai_done, int(extra["done"]))
            if isinstance(extra.get("total"), int):
                state.ai_total = max(state.ai_total, int(extra["total"]))
        elif event == "gmail_ingest.message_fetched":
            label_type = extra.get("label_type")
            step_id = _LABEL_TYPE_TO_STEP.get(str(label_type), current_step_id or "ingest")
            state = step_states.setdefault(step_id, _StepRuntime())
            state.persist_done += 1
            ingested_total += 1
        elif event == "gmail_ingest.finished":
            ingested_total = max(ingested_total, int(extra.get("ingested", 0) or 0))
            skipped_total += int(extra.get("skipped", 0) or 0)
            failed_total += int(extra.get("failed", 0) or 0)
        elif event == "gmail_ingest.skill_sheets_started":
            state = step_states.setdefault("ingest_skill_sheets", _StepRuntime())
            if isinstance(extra.get("total"), int):
                state.skill_total = max(state.skill_total, int(extra["total"]))
        elif event == "gmail_ingest.skill_sheet_progress":
            state = step_states.setdefault("ingest_skill_sheets", _StepRuntime())
            if isinstance(extra.get("done"), int):
                state.skill_done = max(state.skill_done, int(extra["done"]))
            if isinstance(extra.get("total"), int):
                state.skill_total = max(state.skill_total, int(extra["total"]))
        elif event == "gmail_ingest.skill_sheets_finished":
            state = step_states.setdefault("ingest_skill_sheets", _StepRuntime())
            if isinstance(extra.get("total"), int):
                state.skill_total = max(state.skill_total, int(extra["total"]))
            if isinstance(extra.get("done"), int):
                state.skill_done = max(state.skill_done, int(extra["done"]))
            state.detail = f"スキルシート {state.skill_done}/{state.skill_total or state.skill_done} 件"
        elif event == "ingest_cleanup.started":
            state = step_states.setdefault("cleanup", _StepRuntime())
            state.status = "running"
            state.detail = "古い取込データを確認しています"
        elif event == "ingest_cleanup.skipped":
            state = step_states.setdefault("cleanup", _StepRuntime())
            state.status = "completed"
            state.detail = "削除対象なし（保持日数 0）"
        elif event == "ingest_cleanup.finished":
            state = step_states.setdefault("cleanup", _StepRuntime())
            state.status = "completed"
            deleted = extra.get("deleted")
            state.detail = f"削除 {deleted} 件" if deleted is not None else "削除完了"
        elif event == "matching.rule_score.started":
            state = step_states.setdefault("match", _StepRuntime())
            state.status = "running"
            state.detail = "人材×案件のルール採点を実行中"
        elif event == "matching.rule_score.finished":
            state = step_states.setdefault("match", _StepRuntime())
            state.status = "completed"
            match_count = extra.get("match_count")
            scored = extra.get("scored_count")
            if match_count is not None:
                state.detail = f"採点 {match_count} 組合せ"
                if scored is not None:
                    state.detail += f"（新規 {scored}）"
        elif event == "matching.ai_judge.started":
            state = step_states.setdefault("ai_judge", _StepRuntime())
            state.status = "running"
            state.detail = "AI 判定を実行中"
        elif event == "matching.ai_judge.finished":
            state = step_states.setdefault("ai_judge", _StepRuntime())
            state.status = "completed"
            judged = extra.get("ai_judged")
            if judged is not None:
                state.detail = f"AI 判定 {judged} 件"
        elif event == "outreach.reply_sync.started":
            state = step_states.setdefault("reply_sync", _StepRuntime())
            state.status = "running"
            state.detail = "Gmail 返信を同期中"
        elif event == "outreach.reply_sync.finished":
            state = step_states.setdefault("reply_sync", _StepRuntime())
            state.status = "completed"
            replies = extra.get("new_replies")
            if replies is not None:
                state.detail = f"新規返信 {replies} 件"
        elif event == "batch.job.failed" and row.get("level") == "ERROR":
            code = row.get("error_code")
            if isinstance(code, str):
                progress.error_code = code
            msg = row.get("error_message") or row.get("message")
            if isinstance(msg, str):
                progress.error_message = msg
            progress.status = "failed"
            pipeline_status = "failed"
        elif event == "batch.job.cancelled":
            progress.status = "failed"
            progress.error_message = "処理が停止されました"
            progress.detail = "ユーザーにより停止されました"
            pipeline_status = "failed"
        elif event == "batch.pipeline.finished":
            status = extra.get("status")
            failed_step = extra.get("failed_step")
            if status == "ok":
                progress.status = "completed"
                pipeline_status = "completed"
                progress.detail = "すべての工程が完了しました"
            elif status == "cancelled":
                progress.status = "failed"
                progress.error_message = "処理が停止されました"
                progress.detail = "ユーザーにより停止されました"
                pipeline_status = "failed"
            else:
                progress.status = "failed"
                pipeline_status = "failed"
                if isinstance(failed_step, str):
                    progress.error_message = progress.error_message or (
                        f"{_STEP_META.get(failed_step, {}).get('label', failed_step)}で失敗しました"
                    )

    if not enabled_steps:
        enabled_steps = ["ingest_talent", "ingest_project", "cleanup", "match", "reply_sync"]

    weights = _normalize_weights(enabled_steps)
    now = datetime.now(UTC)
    if started_at is not None:
        progress.started_at = started_at.isoformat()
        progress.elapsed_seconds = max(0, int((now - started_at).total_seconds()))
    if updated_at is not None:
        progress.updated_at = updated_at.isoformat()

    step_progress_list: list[PipelineStepProgress] = []
    overall_ratio = 0.0
    total_eta = 0
    active_step_id: str | None = None

    for step_id in enabled_steps:
        meta = _STEP_META.get(step_id, {"label": step_id, "default_seconds": 120})
        state = step_states.setdefault(step_id, _StepRuntime())

        if state.status == "pending":
            for prev_id in enabled_steps:
                if prev_id == step_id:
                    break
                prev_state = step_states.get(prev_id)
                if prev_state and prev_state.status not in {"completed", "failed"}:
                    break
            else:
                if current_step_id == step_id:
                    state.status = "running"

        if state.status == "running" and active_step_id is None:
            active_step_id = step_id

        if step_id.startswith("ingest_") or step_id == "ingest":
            pct, detail = _ingest_step_progress(state)
        elif state.status == "completed":
            pct, detail = 100, state.detail
        elif state.status == "running":
            default_seconds = int(meta.get("default_seconds", 120))
            pct, detail = _generic_running_progress(state, default_seconds=default_seconds, now=now)
        else:
            pct, detail = 0, None

        if state.status == "completed":
            pct = 100
        elif state.status == "failed":
            pct = min(pct, 99)

        elapsed = 0
        if state.started_at is not None:
            end = state.finished_at or now
            elapsed = max(0, int((end - state.started_at).total_seconds()))
        elif state.duration_ms is not None:
            elapsed = max(0, int(state.duration_ms / 1000))

        eta_seconds = _estimate_step_eta(step_id=step_id, state=state, progress_percent=pct, now=now)
        if eta_seconds is not None and state.status in {"pending", "running"}:
            total_eta += eta_seconds

        step_progress_list.append(
            PipelineStepProgress(
                id=step_id,
                label=str(meta.get("label", step_id)),
                status=state.status,
                progress_percent=pct,
                elapsed_seconds=elapsed,
                eta_seconds=eta_seconds,
                eta_label=_format_eta(eta_seconds),
                detail=detail or state.detail,
                weight=weights.get(step_id, 0.0),
            )
        )
        overall_ratio += weights.get(step_id, 0.0) * (pct / 100.0)

    progress.steps = step_progress_list
    progress.total_steps = len(enabled_steps)
    progress.current_step = next(
        (index + 1 for index, step in enumerate(step_progress_list) if step.status == "running"),
        len(enabled_steps) if pipeline_status == "completed" else min(len(enabled_steps), 1),
    )

    if active_step_id:
        progress.phase = active_step_id
        progress.phase_label = str(_STEP_META.get(active_step_id, {}).get("label", active_step_id))
    elif pipeline_status == "completed":
        progress.phase = "done"
        progress.phase_label = "完了"

    progress.progress_percent = (
        100 if pipeline_status == "completed" else min(100, max(0, int(round(overall_ratio * 100))))
    )
    progress.processed_messages = ingested_total
    progress.total_messages = total_messages or None
    progress.ingested = ingested_total
    progress.skipped = skipped_total
    progress.failed = failed_total
    progress.eta_seconds = total_eta if pipeline_status == "running" else (0 if pipeline_status == "completed" else None)
    progress.eta_label = (
        _format_eta(progress.eta_seconds)
        if pipeline_status == "running"
        else ("完了" if pipeline_status == "completed" else None)
    )
    progress.total_estimated_seconds = (
        progress.elapsed_seconds + total_eta if pipeline_status == "running" else progress.elapsed_seconds
    )

    running_step = next((step for step in step_progress_list if step.status == "running"), None)
    if running_step and running_step.detail:
        progress.detail = running_step.detail
    elif not progress.detail and running_step:
        progress.detail = running_step.label

    if progress.status == "running" and not is_batch_job_running("pipeline"):
        progress.status = "failed"
        progress.error_message = "処理が中断されました"
        progress.detail = "バッチプロセスが見つかりません（異常終了または既に停止済み）"
        progress.eta_label = None

    return progress
