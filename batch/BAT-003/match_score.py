"""BAT-003: ルールスコア採点バッチ。

Pass1: 全 active 人材 × open 案件（通勤は中立 5）
Pass2: 案件ごと上位 N 人のみ Google Routes で通勤点を確定
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from commute import get_monthly_usage, resolve_commute_minutes
from db import (
    create_match_run,
    finish_match_run,
    insert_matches,
    list_active_talents,
    list_open_projects,
    load_setting,
    update_match_score,
)
from scorer import is_full_remote, score_pair


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
        # 自社名設定がある場合は提案メールと同じ視点で商流を調整して足切り判定する
        "talent_commerce_flow": adjusted_commerce or None,
        "talent_affiliation": getattr(talent, "affiliation", None),
    }

from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.logging_util import get_batch_logger, log_error_event, log_event

Trigger = Literal["batch_auto", "manual"]


@dataclass
class MatchBatchStats:
    talent_count: int = 0
    project_count: int = 0
    match_count: int = 0
    commute_api_calls: int = 0
    commute_cache_hits: int = 0
    commute_skipped_limit: int = 0
    commute_skipped_remote: int = 0
    warnings: list[str] = field(default_factory=list)


class MatchScoreBatch:
    function_id = "BAT-003"

    def __init__(self, cfg: Settings | None = None, *, trigger: Trigger = "manual") -> None:
        self.cfg = cfg or settings
        self.trigger: Trigger = trigger
        self.job_id = f"job_{uuid.uuid4().hex[:12]}"
        self.logger = get_batch_logger()

    def run(self) -> tuple[UUID | None, MatchBatchStats]:
        started = time.perf_counter()
        stats = MatchBatchStats()
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
            extra={"trigger": self.trigger},
        )

        session_factory, engine = create_session_factory(self.cfg.database_url)
        ensure_schema(engine)

        match_run_id: UUID | None = None
        try:
            with session_factory() as session:
                top_n_raw = load_setting(session, "ai_judgement_top_n", 5)
                try:
                    top_n = max(1, min(20, int(top_n_raw)))
                except (TypeError, ValueError):
                    top_n = 5
                ai_assist = bool(load_setting(session, "ai_assist_enabled", False))
                own_company_raw = load_setting(session, "own_company_name", "")
                own_company_name = str(own_company_raw or "").strip() or None

                talents = list_active_talents(session)
                projects = list_open_projects(session)
                stats.talent_count = len(talents)
                stats.project_count = len(projects)
                talent_company_names = {t.id: _talent_company_name(session, t) for t in talents}

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
                    return None, stats

                run = create_match_run(
                    session,
                    trigger=self.trigger,
                    top_n=top_n,
                    ai_assist_enabled=ai_assist,
                )
                match_run_id = run.id

                # --- Pass 1 ---
                pass1_rows: list[dict[str, Any]] = []
                for project in projects:
                    for talent in talents:
                        result = score_pair(
                            **_score_kwargs(
                                talent,
                                project,
                                commute_resolved=False,
                                own_company_name=own_company_name,
                                talent_company_name=talent_company_names.get(talent.id),
                            )
                        )
                        pass1_rows.append(
                            {
                                "talent_id": talent.id,
                                "project_id": project.id,
                                "score": result.score,
                                "score_band": result.score_band,
                                "score_breakdown": result.breakdown,
                            }
                        )
                insert_matches(session, match_run_id=run.id, rows=pass1_rows)
                stats.match_count = len(pass1_rows)
                session.flush()

                # Load matches for Pass 2 updates
                from sqlalchemy import select

                from app.models import Match

                match_rows = list(
                    session.scalars(select(Match).where(Match.match_run_id == run.id)).all()
                )
                by_project: dict[UUID, list[Match]] = defaultdict(list)
                for row in match_rows:
                    by_project[row.project_id].append(row)

                talent_map = {t.id: t for t in talents}
                project_map = {p.id: p for p in projects}
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

                # --- Pass 2 ---
                for project_id, rows in by_project.items():
                    project = project_map[project_id]
                    rows_sorted = sorted(rows, key=lambda m: m.score, reverse=True)
                    top_rows = rows_sorted[:top_n]
                    remote = is_full_remote(project.work_style)

                    for match in top_rows:
                        talent = talent_map[match.talent_id]
                        if remote:
                            score_kwargs = _score_kwargs(
                                talent,
                                project,
                                commute_resolved=True,
                                own_company_name=own_company_name,
                                talent_company_name=talent_company_names.get(talent.id),
                            )
                            # リモート判定済みでも work_style が空のときはフルリモート扱いを明示
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

                        usage_now = get_monthly_usage(session)
                        if usage_now >= self.cfg.google_routes_monthly_limit:
                            stats.commute_skipped_limit += 1
                            continue

                        minutes, status, called = resolve_commute_minutes(
                            session,
                            api_key=self.cfg.google_maps_api_key,
                            origin=talent.nearest_station,
                            destination=project.location,
                            monthly_warn=self.cfg.google_routes_monthly_warn,
                            monthly_limit=self.cfg.google_routes_monthly_limit,
                            logger=self.logger,
                        )
                        if called:
                            stats.commute_api_calls += 1
                        elif status not in ("no_api_key", "missing_place", "monthly_limit"):
                            stats.commute_cache_hits += 1

                        if status == "monthly_limit":
                            stats.commute_skipped_limit += 1

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

                run_stats = {
                    "talent_count": stats.talent_count,
                    "project_count": stats.project_count,
                    "match_count": stats.match_count,
                    "top_n": top_n,
                    "commute_api_calls": stats.commute_api_calls,
                    "commute_cache_hits": stats.commute_cache_hits,
                    "commute_skipped_limit": stats.commute_skipped_limit,
                    "commute_skipped_remote": stats.commute_skipped_remote,
                    "google_routes_usage": get_monthly_usage(session),
                }
                finish_match_run(session, run, status="completed", stats=run_stats)
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
                "commute_api_calls": stats.commute_api_calls,
            },
        )
        return match_run_id, stats


def run_match_score_batch(*, trigger: Trigger = "manual") -> MatchBatchStats:
    _, stats = MatchScoreBatch(trigger=trigger).run()
    return stats
