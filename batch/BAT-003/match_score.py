"""BAT-003: ルールスコア採点バッチ。

増分: 未採点の人材×案件だけ採点（最新 completed run に追記）。
スコープ: MATCH_PROJECT_IDS / MATCH_TALENT_IDS で候補を絞る。
強制再採点: MATCH_FORCE_RESCORE=1 のときのみ全件を新規 run で再計算。
"""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from db import (
    abandon_stuck_match_runs,
    create_match_run,
    finish_match_run,
    insert_matches,
    list_active_talents,
    list_latest_completed_match_run,
    list_latest_match_by_pair_keys,
    list_missing_pair_keys,
    list_open_projects,
    load_setting,
    match_row_from_existing,
    update_match_score,
)
from scorer import prepare_project_skills, prepare_talent_skills, score_pair_job

from app.batch_job_id import resolve_batch_job_id
from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.logging_util import get_batch_logger, log_error_event, log_event

Trigger = Literal["batch_auto", "manual"]

_SCORE_WORKERS_DEFAULT = 4
_PARALLEL_MIN_PAIRS = 2000
# 増分採点の 1 チャンクサイズ（途中 commit してタイムアウト時も進捗を残す）
_INCREMENTAL_CHUNK = 5000

def _parse_uuid_list(raw: str | None) -> list[UUID]:
    if not raw or not raw.strip():
        return []
    out: list[UUID] = []
    for part in raw.split(","):
        text = part.strip()
        if not text:
            continue
        out.append(UUID(text))
    return out

def _env_force_rescore() -> bool:
    raw = (os.environ.get("MATCH_FORCE_RESCORE") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}

def _talent_company_name(session, talent) -> str | None:
    company_id = getattr(talent, "introducer_company_id", None)
    if company_id:
        from app.models import Company

        company = session.get(Company, company_id)
        if company and (company.name or "").strip():
            return company.name.strip()
    name = (getattr(talent, "source_company_name", None) or "").strip()
    return name or None

def _talent_score_features(
    talent,
    *,
    own_company_name: str | None,
    talent_company_name: str | None,
) -> dict[str, Any]:
    from app.constraint_rules import resolve_proposal_commerce_flow

    adjusted_commerce = resolve_proposal_commerce_flow(
        own_company_name=own_company_name,
        talent_company_name=talent_company_name,
        affiliation=getattr(talent, "affiliation", None),
        commerce_flow=getattr(talent, "commerce_flow", None),
    )
    return {
        "talent_skills_prepared": prepare_talent_skills(
            talent.skills if isinstance(talent.skills, list) else [],
            getattr(talent, "summary", None),
        ),
        "desired_rate": talent.desired_rate,
        "available_from": talent.available_from,
        "talent_work_style": talent.work_style,
        "talent_is_foreign_national": getattr(talent, "is_foreign_national", None),
        "talent_commerce_flow": adjusted_commerce or None,
        "talent_affiliation": getattr(talent, "affiliation", None),
    }

def _project_score_features(project) -> dict[str, Any]:
    return {
        "required_skills_prepared": prepare_project_skills(
            project.required_skills if isinstance(project.required_skills, list) else []
        ),
        "preferred_skills_prepared": prepare_project_skills(
            project.preferred_skills if isinstance(getattr(project, "preferred_skills", None), list) else []
        ),
        "rate_min": project.rate_min,
        "rate_max": project.rate_max,
        "start_date": project.start_date,
        "project_work_style": project.work_style,
        "project_foreign_nationality_ng": bool(getattr(project, "foreign_nationality_ng", False)),
        "project_commerce_flow_limit": getattr(project, "commerce_flow_limit", None),
    }

def _resolve_score_workers(pair_count: int) -> int:
    if pair_count < _PARALLEL_MIN_PAIRS:
        return 1
    cpu = os.cpu_count() or 1
    raw = (os.environ.get("MATCH_SCORE_WORKERS") or "").strip()
    if raw:
        try:
            requested = int(raw)
        except ValueError:
            requested = _SCORE_WORKERS_DEFAULT
    else:
        requested = _SCORE_WORKERS_DEFAULT
    return max(1, min(_SCORE_WORKERS_DEFAULT, cpu, requested, pair_count))

def _score_payloads(
    pair_keys: list[tuple[UUID, UUID]],
    talent_features: dict[UUID, dict[str, Any]],
    project_features: dict[UUID, dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "talent_id": talent_id,
            "project_id": project_id,
            **talent_features[talent_id],
            **project_features[project_id],
        }
        for talent_id, project_id in pair_keys
    ]

def _map_score_jobs(
    payloads: list[dict[str, Any]],
    *,
    executor: ProcessPoolExecutor | None,
    workers: int,
) -> list[dict[str, Any]]:
    if not payloads:
        return []
    if executor is None or workers <= 1 or len(payloads) < 32:
        return [score_pair_job(payload) for payload in payloads]
    chunksize = max(32, len(payloads) // (workers * 8))
    return list(executor.map(score_pair_job, payloads, chunksize=chunksize))

@dataclass
class MatchBatchStats:
    talent_count: int = 0
    project_count: int = 0
    match_count: int = 0
    scored_count: int = 0
    reused_count: int = 0
    commute_api_calls: int = 0
    commute_cache_hits: int = 0
    commute_skipped_limit: int = 0
    commute_skipped_remote: int = 0
    force_rescore: bool = False
    warnings: list[str] = field(default_factory=list)

class MatchScoreBatch:
    function_id = "BAT-003"

    def __init__(
        self,
        cfg: Settings | None = None,
        *,
        trigger: Trigger = "manual",
        force_rescore: bool | None = None,
        scope_project_ids: list[UUID] | None = None,
        scope_talent_ids: list[UUID] | None = None,
    ) -> None:
        self.cfg = cfg or settings
        self.trigger: Trigger = trigger
        self.force_rescore = _env_force_rescore() if force_rescore is None else force_rescore
        self.scope_project_ids = scope_project_ids
        self.scope_talent_ids = scope_talent_ids
        if self.scope_project_ids is None:
            self.scope_project_ids = _parse_uuid_list(os.environ.get("MATCH_PROJECT_IDS"))
        if self.scope_talent_ids is None:
            self.scope_talent_ids = _parse_uuid_list(os.environ.get("MATCH_TALENT_IDS"))
        self.job_id = resolve_batch_job_id(default_prefix="job")
        self.logger = get_batch_logger()

    def run(self) -> tuple[UUID | None, MatchBatchStats]:
        started = time.perf_counter()
        stats = MatchBatchStats(force_rescore=self.force_rescore)
        log_event(
            self.logger,
            logging.INFO,
            event="matching.rule_score.started",
            message="Rule score batch started",
            operation="ルールスコア採点開始",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            module_name="BAT-003.match_score",
            extra={
                "trigger": self.trigger,
                "force_rescore": self.force_rescore,
                "scope_project_ids": [str(i) for i in (self.scope_project_ids or [])],
                "scope_talent_ids": [str(i) for i in (self.scope_talent_ids or [])],
            },
        )

        session_factory, engine = create_session_factory(self.cfg.database_url)
        ensure_schema(engine)

        match_run_id: UUID | None = None
        try:
            try:
                with session_factory() as session:
                    from sqlalchemy import func, select

                    from app.models import Match

                    top_n_raw = load_setting(session, "ai_judgement_top_n", 5)
                    try:
                        top_n = max(1, min(20, int(top_n_raw)))
                    except (TypeError, ValueError):
                        top_n = 5
                    ai_assist = bool(load_setting(session, "ai_assist_enabled", False))
                    own_company_raw = load_setting(session, "own_company_name", "")
                    own_company_name = str(own_company_raw or "").strip() or None

                    abandon_stuck_match_runs(session, reason="superseded_by_match_batch")
                    session.flush()

                    scoped_projects = self.scope_project_ids or None
                    scoped_talents = self.scope_talent_ids or None
                    # 片方だけ指定: 相手側は全件
                    if scoped_projects is not None and not scoped_projects:
                        scoped_projects = None
                    if scoped_talents is not None and not scoped_talents:
                        scoped_talents = None

                    if scoped_projects is not None and scoped_talents is None:
                        projects = list_open_projects(session, project_ids=scoped_projects)
                        talents = list_active_talents(session)
                    elif scoped_talents is not None and scoped_projects is None:
                        talents = list_active_talents(session, talent_ids=scoped_talents)
                        projects = list_open_projects(session)
                    elif scoped_projects is not None and scoped_talents is not None:
                        projects = list_open_projects(session, project_ids=scoped_projects)
                        talents = list_active_talents(session, talent_ids=scoped_talents)
                    else:
                        talents = list_active_talents(session)
                        projects = list_open_projects(session)

                    stats.talent_count = len(talents)
                    stats.project_count = len(projects)
                    talent_company_names = {t.id: _talent_company_name(session, t) for t in talents}
                    talent_ids = [t.id for t in talents]
                    project_ids = [p.id for p in projects]
                    talent_features = {
                        t.id: _talent_score_features(
                            t,
                            own_company_name=own_company_name,
                            talent_company_name=talent_company_names.get(t.id),
                        )
                        for t in talents
                    }
                    project_features = {p.id: _project_score_features(p) for p in projects}

                    if not talents or not projects:
                        log_error_event(
                            self.logger,
                            event="matching.rule_score.failed",
                            error_code="ERR-0026",
                            detail="マッチング対象がありません。",
                            operation="ルールスコア採点",
                            method_name="run",
                            job_id=self.job_id,
                            function_id=self.function_id,
                            module_name="BAT-003.match_score",
                        )
                        session.commit()
                        return None, stats

                    if self.force_rescore:
                        scoped = scoped_projects is not None or scoped_talents is not None
                        runner = self._run_scoped_rescore if scoped else self._run_force_rescore
                        match_run_id, stats = runner(
                            session,
                            stats=stats,
                            talents=talents,
                            projects=projects,
                            talent_features=talent_features,
                            project_features=project_features,
                            top_n=top_n,
                            ai_assist=ai_assist,
                        )
                        session.commit()
                    else:
                        match_run_id, stats = self._run_incremental(
                            session,
                            stats=stats,
                            talent_ids=talent_ids,
                            project_ids=project_ids,
                            talent_features=talent_features,
                            project_features=project_features,
                            top_n=top_n,
                            ai_assist=ai_assist,
                        )
                        session.commit()
            except Exception as exc:
                log_error_event(
                    self.logger,
                    event="matching.rule_score.failed",
                    error_code="ERR-0030",
                    detail=str(exc),
                    operation="ルールスコア採点",
                    method_name="run",
                    job_id=self.job_id,
                    function_id=self.function_id,
                    module_name="BAT-003.match_score",
                )
                raise
        finally:
            engine.dispose()

        duration_ms = int((time.perf_counter() - started) * 1000)
        log_event(
            self.logger,
            logging.INFO,
            event="matching.rule_score.finished",
            message="Rule score batch finished",
            operation="ルールスコア採点終了",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            module_name="BAT-003.match_score",
            duration_ms=duration_ms,
            extra={
                "match_run_id": str(match_run_id) if match_run_id else None,
                "created_count": stats.match_count,
                "scored_count": stats.scored_count,
                "reused_count": stats.reused_count,
                "commute_api_calls": stats.commute_api_calls,
                "force_rescore": stats.force_rescore,
            },
        )
        return match_run_id, stats

    def _run_incremental(
        self,
        session,
        *,
        stats: MatchBatchStats,
        talent_ids: list[UUID],
        project_ids: list[UUID],
        talent_features: dict[UUID, dict[str, Any]],
        project_features: dict[UUID, dict[str, Any]],
        top_n: int,
        ai_assist: bool,
    ) -> tuple[UUID | None, MatchBatchStats]:
        from sqlalchemy import func, select

        from app.models import Match

        latest = list_latest_completed_match_run(session)
        missing_keys = list_missing_pair_keys(
            session,
            talent_ids=talent_ids,
            project_ids=project_ids,
            latest_run_id=latest.id if latest else None,
        )

        if not missing_keys:
            stats.match_count = (
                int(
                    session.scalar(
                        select(func.count()).select_from(Match).where(Match.match_run_id == latest.id)
                    )
                    or 0
                )
                if latest
                else 0
            )
            return (latest.id if latest else None), stats

        if latest is None:
            latest = create_match_run(
                session,
                trigger=self.trigger,
                top_n=top_n,
                ai_assist_enabled=ai_assist,
            )
            session.flush()
        match_run_id = latest.id

        workers = _resolve_score_workers(len(missing_keys))
        total_missing = len(missing_keys)
        executor: ProcessPoolExecutor | None = None
        if workers > 1:
            executor = ProcessPoolExecutor(max_workers=workers)
        try:
            for chunk_start in range(0, total_missing, _INCREMENTAL_CHUNK):
                chunk_keys = missing_keys[chunk_start : chunk_start + _INCREMENTAL_CHUNK]
                historical = list_latest_match_by_pair_keys(session, pair_keys=chunk_keys)
                rows_to_insert: list[dict[str, Any]] = []
                to_score: list[tuple[UUID, UUID]] = []
                for talent_id, project_id in chunk_keys:
                    prior = historical.get((talent_id, project_id))
                    if prior is not None:
                        rows_to_insert.append(match_row_from_existing(prior))
                        stats.reused_count += 1
                        continue
                    to_score.append((talent_id, project_id))
                scored_rows = _map_score_jobs(
                    _score_payloads(to_score, talent_features, project_features),
                    executor=executor,
                    workers=workers,
                )
                scored_by_key = {
                    (row["talent_id"], row["project_id"]): row for row in scored_rows
                }
                for talent_id, project_id in to_score:
                    scored = scored_by_key[(talent_id, project_id)]
                    rows_to_insert.append(
                        {
                            "talent_id": talent_id,
                            "project_id": project_id,
                            "score": scored["score"],
                            "score_band": scored["score_band"],
                            "score_breakdown": scored["score_breakdown"],
                            "reused": False,
                        }
                    )
                    stats.scored_count += 1

                insert_matches(session, match_run_id=latest.id, rows=rows_to_insert)
                session.commit()
        finally:
            if executor is not None:
                executor.shutdown(wait=True)

        total_matches = (
            session.scalar(
                select(func.count()).select_from(Match).where(Match.match_run_id == latest.id)
            )
            or 0
        )
        stats.match_count = int(total_matches)
        latest.trigger = self.trigger
        latest.ai_judgement_top_n = top_n
        latest.ai_assist_enabled = ai_assist
        finish_match_run(
            session,
            latest,
            status="completed",
            stats={
                "talent_count": stats.talent_count,
                "project_count": stats.project_count,
                "match_count": stats.match_count,
                "scored_count": stats.scored_count,
                "reused_count": stats.reused_count,
                "top_n": top_n,
                "commute_api_calls": stats.commute_api_calls,
                "commute_cache_hits": stats.commute_cache_hits,
                "commute_skipped_limit": stats.commute_skipped_limit,
                "commute_skipped_remote": stats.commute_skipped_remote,
                "incremental": True,
                "force_rescore": False,
            },
        )
        return match_run_id, stats

    def _run_scoped_rescore(
        self,
        session,
        *,
        stats: MatchBatchStats,
        talents,
        projects,
        talent_features: dict[UUID, dict[str, Any]],
        project_features: dict[UUID, dict[str, Any]],
        top_n: int,
        ai_assist: bool,
    ) -> tuple[UUID | None, MatchBatchStats]:
        """指定人材または案件だけを、直近 completed run 上で再採点する（他ペアは残す）。"""
        from sqlalchemy import func, select

        from app.models import Match

        latest = list_latest_completed_match_run(session)
        if latest is None:
            latest = create_match_run(
                session,
                trigger=self.trigger,
                top_n=top_n,
                ai_assist_enabled=ai_assist,
            )

        pair_keys = [(t.id, p.id) for p in projects for t in talents]
        key_set = set(pair_keys)
        talent_ids = [t.id for t in talents]
        project_ids = [p.id for p in projects]
        existing_rows = list(
            session.scalars(
                select(Match).where(
                    Match.match_run_id == latest.id,
                    Match.talent_id.in_(talent_ids),
                    Match.project_id.in_(project_ids),
                )
            ).all()
        )
        existing = {
            (row.talent_id, row.project_id): row
            for row in existing_rows
            if (row.talent_id, row.project_id) in key_set
        }
        historical = list_latest_match_by_pair_keys(session, pair_keys=pair_keys)

        workers = _resolve_score_workers(len(pair_keys))
        executor: ProcessPoolExecutor | None = (
            ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
        )
        try:
            scored_rows = _map_score_jobs(
                _score_payloads(pair_keys, talent_features, project_features),
                executor=executor,
                workers=workers,
            )
        finally:
            if executor is not None:
                executor.shutdown(wait=True)
        scored_by_key = {(row["talent_id"], row["project_id"]): row for row in scored_rows}

        insert_rows: list[dict[str, Any]] = []
        for talent_id, project_id in pair_keys:
            scored = scored_by_key[(talent_id, project_id)]
            current = existing.get((talent_id, project_id))
            if current is not None:
                update_match_score(
                    session,
                    match_id=current.id,
                    score=scored["score"],
                    score_band=scored["score_band"],
                    breakdown=scored["score_breakdown"],
                )
                stats.scored_count += 1
                continue
            prior = historical.get((talent_id, project_id))
            row: dict[str, Any] = {
                "talent_id": talent_id,
                "project_id": project_id,
                "score": scored["score"],
                "score_band": scored["score_band"],
                "score_breakdown": scored["score_breakdown"],
                "reused": False,
            }
            if prior is not None:
                row["ai_score"] = prior.ai_score
                row["reason"] = prior.reason
                row["recommendation_points"] = prior.recommendation_points
                row["ai_judged_at"] = prior.ai_judged_at
                row["is_candidate"] = bool(prior.is_candidate)
            insert_rows.append(row)
            stats.scored_count += 1

        if insert_rows:
            insert_matches(session, match_run_id=latest.id, rows=insert_rows)
        session.flush()
        stats.match_count = int(
            session.scalar(select(func.count()).select_from(Match).where(Match.match_run_id == latest.id))
            or 0
        )
        finish_match_run(
            session,
            latest,
            status="completed",
            stats={
                "talent_count": stats.talent_count,
                "project_count": stats.project_count,
                "match_count": stats.match_count,
                "scored_count": stats.scored_count,
                "reused_count": 0,
                "top_n": top_n,
                "commute_api_calls": 0,
                "incremental": False,
                "force_rescore": True,
                "scoped": True,
            },
        )
        return latest.id, stats

    def _run_force_rescore(
        self,
        session,
        *,
        stats: MatchBatchStats,
        talents,
        projects,
        talent_features: dict[UUID, dict[str, Any]],
        project_features: dict[UUID, dict[str, Any]],
        top_n: int,
        ai_assist: bool,
    ) -> tuple[UUID | None, MatchBatchStats]:
        from sqlalchemy import func, select

        from app.models import Match

        pair_keys = [(t.id, p.id) for p in projects for t in talents]
        run = create_match_run(
            session,
            trigger=self.trigger,
            top_n=top_n,
            ai_assist_enabled=ai_assist,
        )
        workers = _resolve_score_workers(len(pair_keys))
        executor: ProcessPoolExecutor | None = (
            ProcessPoolExecutor(max_workers=workers) if workers > 1 else None
        )
        try:
            for chunk_start in range(0, len(pair_keys), _INCREMENTAL_CHUNK):
                chunk = pair_keys[chunk_start : chunk_start + _INCREMENTAL_CHUNK]
                historical = list_latest_match_by_pair_keys(session, pair_keys=chunk)
                scored_rows = _map_score_jobs(
                    _score_payloads(chunk, talent_features, project_features),
                    executor=executor,
                    workers=workers,
                )
                scored_by_key = {(row["talent_id"], row["project_id"]): row for row in scored_rows}
                rows: list[dict[str, Any]] = []
                for talent_id, project_id in chunk:
                    scored = scored_by_key[(talent_id, project_id)]
                    prior = historical.get((talent_id, project_id))
                    row = {
                        "talent_id": talent_id,
                        "project_id": project_id,
                        "score": scored["score"],
                        "score_band": scored["score_band"],
                        "score_breakdown": scored["score_breakdown"],
                        "reused": False,
                    }
                    if prior is not None:
                        row["ai_score"] = prior.ai_score
                        row["reason"] = prior.reason
                        row["recommendation_points"] = prior.recommendation_points
                        row["ai_judged_at"] = prior.ai_judged_at
                        row["is_candidate"] = bool(prior.is_candidate)
                    rows.append(row)
                    stats.scored_count += 1
                insert_matches(session, match_run_id=run.id, rows=rows)
                session.flush()
        finally:
            if executor is not None:
                executor.shutdown(wait=True)
        stats.match_count = int(
            session.scalar(select(func.count()).select_from(Match).where(Match.match_run_id == run.id))
            or 0
        )
        finish_match_run(
            session,
            run,
            status="completed",
            stats={
                "talent_count": stats.talent_count,
                "project_count": stats.project_count,
                "match_count": stats.match_count,
                "scored_count": stats.scored_count,
                "reused_count": 0,
                "top_n": top_n,
                "commute_api_calls": 0,
                "incremental": False,
                "force_rescore": True,
            },
        )
        return run.id, stats

def run_match_score_batch(*, trigger: Trigger = "manual") -> MatchBatchStats:
    _, stats = MatchScoreBatch(trigger=trigger).run()
    return stats
