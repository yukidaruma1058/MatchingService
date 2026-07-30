"""BAT-003: DB 操作（match_runs / matches）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Match, MatchRun, Project, Talent, SystemSetting


def load_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(SystemSetting, key)
    if row is None:
        return default
    return row.value if row.value is not None else default


def list_active_talents(session: Session) -> list[Talent]:
    return list(session.scalars(select(Talent).where(Talent.status == "active")).all())


def list_open_projects(session: Session) -> list[Project]:
    return list(session.scalars(select(Project).where(Project.status == "open")).all())


def create_match_run(
    session: Session,
    *,
    trigger: str,
    top_n: int,
    ai_assist_enabled: bool,
) -> MatchRun:
    now = datetime.now().astimezone()
    run = MatchRun(
        id=uuid4(),
        trigger=trigger,
        ai_judgement_top_n=top_n,
        ai_assist_enabled=ai_assist_enabled,
        status="running",
        stats=None,
        started_at=now,
        created_at=now,
    )
    session.add(run)
    session.flush()
    return run


def finish_match_run(
    session: Session,
    run: MatchRun,
    *,
    status: str,
    stats: dict[str, Any],
) -> None:
    run.status = status
    run.stats = stats
    run.finished_at = datetime.now().astimezone()


def insert_matches(
    session: Session,
    *,
    match_run_id: UUID,
    rows: list[dict[str, Any]],
) -> int:
    now = datetime.now().astimezone()
    objects = [
        Match(
            id=uuid4(),
            match_run_id=match_run_id,
            talent_id=row["talent_id"],
            project_id=row["project_id"],
            score=row["score"],
            score_band=row["score_band"],
            score_breakdown=row["score_breakdown"],
            is_candidate=False,
            created_at=now,
        )
        for row in rows
    ]
    session.add_all(objects)
    session.flush()
    return len(objects)


def update_match_score(
    session: Session,
    *,
    match_id: UUID,
    score: int,
    score_band: str,
    breakdown: dict[str, Any],
) -> None:
    row = session.get(Match, match_id)
    if row is None:
        return
    row.score = score
    row.score_band = score_band
    row.score_breakdown = breakdown
