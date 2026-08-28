"""BAT-003: ルールスコア採点バッチ。

増分: 未採点の人材×案件だけ採点（最新 completed run に追記）。
スコープ: MATCH_PROJECT_IDS / MATCH_TALENT_IDS で候補を絞る。
強制再採点: MATCH_FORCE_RESCORE=1 のときのみ全件を新規 run で再計算。
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from commute import get_monthly_usage, resolve_commute_minutes
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
from scorer import is_full_remote, score_pair

from app.batch_job_id import resolve_batch_job_id
from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.logging_util import get_batch_logger, log_error_event, log_event

Trigger = Literal["batch_auto", "manual"]

_COMMUTE_PARALLEL = 4


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


def _score_kwargs(
    talent,
    project,
    *,
    commute_resolved: bool,
    commute_minutes: int | None = None,
    own_company_name: str | None = None,
    talent_company_name: str | None = None,
) -> dict:
    from app.constraint_rules import resolve_proposal_commerce_flow

    adjusted_commerce = resolve_proposal_commerce_flow(
        own_company_name=own_company_name,
        talent_company_name=talent_company_name,
        affiliation=getattr(talent, "affiliation", None),
        commerce_flow=getattr(talent, "commerce_flow", None),
    )
    return {
        "talent_skills": talent.skills if isinstance(talent.skills, list) else [],
        "required_skills": project.required_skills if isinstance(project.required_skills, list) else [],
        "desired_rate": talent.desired_rate,
        "rate_min": project.rate_min,
        "rate_max": project.rate_max,
        "available_from": talent.available_from,
        "start_date": project.start_date,
        "talent_work_style": talent.work_style,
        "project_work_style": project.work_style,
        "commute_minutes": commute_minutes,
        "commute_resolved": commute_resolved,
        "project_foreign_nationality_ng": bool(getattr(project, "foreign_nationality_ng", False)),
        "talent_is_foreign_national": getattr(talent, "is_foreign_national", None),
        "project_commerce_flow_limit": getattr(project, "commerce_flow_limit", None),
        "talent_commerce_flow": adjusted_commerce or None,
        "talent_affiliation": getattr(talent, "affiliation", None),
    }


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
                talent_map = {t.id: t for t in talents}
                project_map = {p.id: p for p in projects}
                talent_ids = [t.id for t in talents]
                project_ids = [p.id for p in projects]

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
                        talent_map=talent_map,
                        project_map=project_map,
                        talent_company_names=talent_company_names,
                        own_company_name=own_company_name,
                        top_n=top_n,
                        ai_assist=ai_assist,
                    )
                    session.commit()
                else:
                    match_run_id, stats = self._run_incremental(
                        session,
                        stats=stats,
                        talents=talents,
                        projects=projects,
                        talent_ids=talent_ids,
                        project_ids=project_ids,
                        talent_map=talent_map,
                        project_map=project_map,
                        talent_company_names=talent_company_names,
                        own_company_name=own_company_name,
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
        talents,
        projects,
        talent_ids: list[UUID],
        project_ids: list[UUID],
        talent_map,
        project_map,
        talent_company_names,
        own_company_name: str | None,
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

        historical = list_latest_match_by_pair_keys(session, pair_keys=missing_keys)
        rows_to_insert: list[dict[str, Any]] = []
        for talent_id, project_id in missing_keys:
            prior = historical.get((talent_id, project_id))
            if prior is not None:
                rows_to_insert.append(match_row_from_existing(prior))
                stats.reused_count += 1
                continue
            talent = talent_map[talent_id]
            project = project_map[project_id]
            result = score_pair(
                **_score_kwargs(
                    talent,
                    project,
                    commute_resolved=False,
                    own_company_name=own_company_name,
                    talent_company_name=talent_company_names.get(talent.id),
                )
            )
            rows_to_insert.append(
                {
                    "talent_id": talent.id,
                    "project_id": project.id,
                    "score": result.score,
                    "score_band": result.score_band,
                    "score_breakdown": result.breakdown,
                    "reused": False,
                }
            )
            stats.scored_count += 1

        if latest is None:
            latest = create_match_run(
                session,
                trigger=self.trigger,
                top_n=top_n,
                ai_assist_enabled=ai_assist,
            )
        match_run_id = latest.id

        inserted = insert_matches(session, match_run_id=latest.id, rows=rows_to_insert)
        newly_scored = [
            match
            for match, row in zip(inserted, rows_to_insert, strict=True)
            if not row.get("reused")
        ]
        self._pass2_commute(
            session,
            stats=stats,
            latest_run_id=latest.id,
            newly_scored=newly_scored,
            talent_map=talent_map,
            project_map=project_map,
            talent_company_names=talent_company_names,
            own_company_name=own_company_name,
            top_n=top_n,
        )

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
                "google_routes_usage": get_monthly_usage(session),
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
        talent_map,
        project_map,
        talent_company_names,
        own_company_name: str | None,
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

        insert_rows: list[dict[str, Any]] = []
        updated: list = []
        for talent in talents:
            for project in projects:
                result = score_pair(
                    **_score_kwargs(
                        talent,
                        project,
                        commute_resolved=False,
                        own_company_name=own_company_name,
                        talent_company_name=talent_company_names.get(talent.id),
                    )
                )
                current = existing.get((talent.id, project.id))
                if current is not None:
                    update_match_score(
                        session,
                        match_id=current.id,
                        score=result.score,
                        score_band=result.score_band,
                        breakdown=result.breakdown,
                    )
                    updated.append(current)
                    stats.scored_count += 1
                    continue
                prior = historical.get((talent.id, project.id))
                row: dict[str, Any] = {
                    "talent_id": talent.id,
                    "project_id": project.id,
                    "score": result.score,
                    "score_band": result.score_band,
                    "score_breakdown": result.breakdown,
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

        inserted = insert_matches(session, match_run_id=latest.id, rows=insert_rows) if insert_rows else []
        newly_scored = [*updated, *inserted]
        session.flush()
        self._pass2_commute(
            session,
            stats=stats,
            latest_run_id=latest.id,
            newly_scored=newly_scored,
            talent_map=talent_map,
            project_map=project_map,
            talent_company_names=talent_company_names,
            own_company_name=own_company_name,
            top_n=top_n,
        )
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
                "commute_api_calls": stats.commute_api_calls,
                "commute_cache_hits": stats.commute_cache_hits,
                "commute_skipped_limit": stats.commute_skipped_limit,
                "commute_skipped_remote": stats.commute_skipped_remote,
                "google_routes_usage": get_monthly_usage(session),
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
        talent_map,
        project_map,
        talent_company_names,
        own_company_name: str | None,
        top_n: int,
        ai_assist: bool,
    ) -> tuple[UUID | None, MatchBatchStats]:
        from sqlalchemy import func, select

        from app.models import Match

        pair_keys = [(t.id, p.id) for p in projects for t in talents]
        historical = list_latest_match_by_pair_keys(session, pair_keys=pair_keys)

        run = create_match_run(
            session,
            trigger=self.trigger,
            top_n=top_n,
            ai_assist_enabled=ai_assist,
        )
        rows: list[dict[str, Any]] = []
        for talent in talents:
            for project in projects:
                result = score_pair(
                    **_score_kwargs(
                        talent,
                        project,
                        commute_resolved=False,
                        own_company_name=own_company_name,
                        talent_company_name=talent_company_names.get(talent.id),
                    )
                )
                prior = historical.get((talent.id, project.id))
                row: dict[str, Any] = {
                    "talent_id": talent.id,
                    "project_id": project.id,
                    "score": result.score,
                    "score_band": result.score_band,
                    "score_breakdown": result.breakdown,
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

        inserted = insert_matches(session, match_run_id=run.id, rows=rows)
        self._pass2_commute(
            session,
            stats=stats,
            latest_run_id=run.id,
            newly_scored=inserted,
            talent_map=talent_map,
            project_map=project_map,
            talent_company_names=talent_company_names,
            own_company_name=own_company_name,
            top_n=top_n,
        )
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
                "commute_api_calls": stats.commute_api_calls,
                "commute_cache_hits": stats.commute_cache_hits,
                "commute_skipped_limit": stats.commute_skipped_limit,
                "commute_skipped_remote": stats.commute_skipped_remote,
                "google_routes_usage": get_monthly_usage(session),
                "incremental": False,
                "force_rescore": True,
            },
        )
        return run.id, stats

    def _pass2_commute(
        self,
        session,
        *,
        stats: MatchBatchStats,
        latest_run_id: UUID,
        newly_scored: list,
        talent_map,
        project_map,
        talent_company_names,
        own_company_name: str | None,
        top_n: int,
    ) -> None:
        from sqlalchemy import select

        from app.models import Match

        if not newly_scored:
            return

        monthly_before = get_monthly_usage(session)
        if monthly_before >= self.cfg.google_routes_monthly_warn:
            msg = f"Google Routes usage {monthly_before} >= warn {self.cfg.google_routes_monthly_warn}"
            stats.warnings.append(msg)
            log_event(
                self.logger,
                logging.WARNING,
                event="matching.commute.usage_warning",
                message=msg,
                operation="通勤API利用量",
                method_name="run",
                job_id=self.job_id,
                function_id=self.function_id,
                module_name="BAT-003.match_score",
                extra={"usage": monthly_before, "limit": self.cfg.google_routes_monthly_limit},
            )

        newly_ids = {m.id for m in newly_scored}
        affected_project_ids = {m.project_id for m in newly_scored}
        commute_jobs: list[tuple[Any, Any, Any]] = []

        for project_id in affected_project_ids:
            project = project_map[project_id]
            project_matches = list(
                session.scalars(
                    select(Match).where(
                        Match.match_run_id == latest_run_id,
                        Match.project_id == project_id,
                    )
                ).all()
            )
            rows_sorted = sorted(project_matches, key=lambda m: m.score, reverse=True)
            top_rows = rows_sorted[:top_n]
            remote = is_full_remote(project.work_style)

            for match in top_rows:
                if match.id not in newly_ids:
                    continue
                talent = talent_map[match.talent_id]
                if remote:
                    score_kwargs = _score_kwargs(
                        talent,
                        project,
                        commute_resolved=True,
                        own_company_name=own_company_name,
                        talent_company_name=talent_company_names.get(talent.id),
                    )
                    score_kwargs["project_work_style"] = project.work_style or "フルリモート"
                    result = score_pair(**score_kwargs)
                    update_match_score(
                        session,
                        match_id=match.id,
                        score=result.score,
                        score_band=result.score_band,
                        breakdown=result.breakdown,
                    )
                    stats.commute_skipped_remote += 1
                    continue
                commute_jobs.append((match, talent, project))

        if not commute_jobs:
            return

        def _resolve_one(job: tuple[Any, Any, Any]) -> tuple[UUID, int | None, str, bool]:
            match, talent, project = job
            # キャッシュ読みは別セッション相当が理想だが、ここでは共有 session を避け
            # API 呼び出しだけ並列化し、結果適用は呼び出し側で直列にする。
            from app.db_bootstrap import create_session_factory as _csf

            factory, _ = _csf(self.cfg.database_url)
            with factory() as local_session:
                minutes, status, called = resolve_commute_minutes(
                    local_session,
                    api_key=self.cfg.google_maps_api_key,
                    origin=talent.nearest_station,
                    destination=project.location,
                    monthly_warn=self.cfg.google_routes_monthly_warn,
                    monthly_limit=self.cfg.google_routes_monthly_limit,
                    logger=self.logger,
                )
                local_session.commit()
            return match.id, minutes, status, called

        workers = min(_COMMUTE_PARALLEL, len(commute_jobs))
        results: list[tuple[UUID, int | None, str, bool]] = []
        if workers <= 1:
            results = [_resolve_one(job) for job in commute_jobs]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(_resolve_one, job): job for job in commute_jobs}
                for future in as_completed(futures):
                    results.append(future.result())

        result_by_id = {match_id: (minutes, status, called) for match_id, minutes, status, called in results}
        for match, talent, project in commute_jobs:
            minutes, status, called = result_by_id[match.id]
            if called:
                stats.commute_api_calls += 1
            elif status not in ("no_api_key", "missing_place", "monthly_limit"):
                stats.commute_cache_hits += 1
            if status == "monthly_limit":
                stats.commute_skipped_limit += 1
                continue
            result = score_pair(
                **_score_kwargs(
                    talent,
                    project,
                    commute_resolved=True,
                    commute_minutes=minutes,
                    own_company_name=own_company_name,
                    talent_company_name=talent_company_names.get(talent.id),
                )
            )
            result.breakdown["commute_status"] = status
            update_match_score(
                session,
                match_id=match.id,
                score=result.score,
                score_band=result.score_band,
                breakdown=result.breakdown,
            )


def run_match_score_batch(*, trigger: Trigger = "manual") -> MatchBatchStats:
    _, stats = MatchScoreBatch(trigger=trigger).run()
    return stats
