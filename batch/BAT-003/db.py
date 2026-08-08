"""BAT-003: DB 操作（match_runs / matches）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import Match, MatchRun, Project, Talent, SystemSetting


def load_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(SystemSetting, key)
    if row is None:
        return default
    return row.value if row.value is not None else default


def list_active_talents(session: Session, *, talent_ids: list[UUID] | None = None) -> list[Talent]:
    stmt = select(Talent).where(Talent.status == "active")
    if talent_ids is not None:
        if not talent_ids:
            return []
        stmt = stmt.where(Talent.id.in_(talent_ids))
    return list(session.scalars(stmt).all())


def list_open_projects(session: Session, *, project_ids: list[UUID] | None = None) -> list[Project]:
    stmt = select(Project).where(Project.status == "open")
    if project_ids is not None:
        if not project_ids:
            return []
        stmt = stmt.where(Project.id.in_(project_ids))
    return list(session.scalars(stmt).all())


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


def abandon_stuck_match_runs(session: Session, *, reason: str = "superseded") -> int:
    """status=running の中断 run を failed にする。戻り値は件数。"""
    stuck_runs = list(session.scalars(select(MatchRun).where(MatchRun.status == "running")).all())
    if not stuck_runs:
        return 0
    now = datetime.now().astimezone()
    for stuck in stuck_runs:
        stuck.status = "failed"
        stuck.finished_at = now
        stuck.stats = {
            **(stuck.stats if isinstance(stuck.stats, dict) else {}),
            "abandoned": True,
            "reason": reason,
        }
    session.flush()
    return len(stuck_runs)


def list_latest_completed_match_run(session: Session) -> MatchRun | None:
    return session.scalar(
        select(MatchRun)
        .where(MatchRun.status == "completed")
        .order_by(MatchRun.started_at.desc())
        .limit(1)
    )


def list_missing_pair_keys(
    session: Session,
    *,
    talent_ids: list[UUID],
    project_ids: list[UUID],
    latest_run_id: UUID | None,
) -> list[tuple[UUID, UUID]]:
    """最新 completed run に無い人材×案件キーだけを返す（SQL anti-join）。"""
    if not talent_ids or not project_ids:
        return []

    if latest_run_id is None:
        sql = text(
            """
            SELECT t.id AS talent_id, p.id AS project_id
            FROM unnest(CAST(:talent_ids AS uuid[])) AS t(id)
            CROSS JOIN unnest(CAST(:project_ids AS uuid[])) AS p(id)
            """
        )
        rows = session.execute(
            sql,
            {"talent_ids": talent_ids, "project_ids": project_ids},
        ).all()
    else:
        sql = text(
            """
            SELECT t.id AS talent_id, p.id AS project_id
            FROM unnest(CAST(:talent_ids AS uuid[])) AS t(id)
            CROSS JOIN unnest(CAST(:project_ids AS uuid[])) AS p(id)
            WHERE NOT EXISTS (
              SELECT 1 FROM matches m
              WHERE m.match_run_id = :run_id
                AND m.talent_id = t.id
                AND m.project_id = p.id
            )
            """
        )
        rows = session.execute(
            sql,
            {
                "talent_ids": talent_ids,
                "project_ids": project_ids,
                "run_id": latest_run_id,
            },
        ).all()
    return [(row.talent_id, row.project_id) for row in rows]


def list_latest_match_by_pair_keys(
    session: Session,
    *,
    pair_keys: list[tuple[UUID, UUID]],
) -> dict[tuple[UUID, UUID], Match]:
    """指定キーについて過去 run 横断の最新 Match だけ取得。"""
    if not pair_keys:
        return {}
    talent_ids = list({t for t, _ in pair_keys})
    project_ids = list({p for _, p in pair_keys})
    key_set = set(pair_keys)
    # DISTINCT ON でキーごとの最新行を 1 クエリで取得（id の IN が 65535 超えないようにする）
    stmt = (
        select(Match)
        .distinct(Match.talent_id, Match.project_id)
        .where(Match.talent_id.in_(talent_ids))
        .where(Match.project_id.in_(project_ids))
        .order_by(Match.talent_id, Match.project_id, Match.created_at.desc())
    )
    matches = list(session.scalars(stmt).all())
    out: dict[tuple[UUID, UUID], Match] = {}
    for match in matches:
        key = (match.talent_id, match.project_id)
        if key in key_set:
            out[key] = match
    return out


def match_row_from_existing(match: Match) -> dict[str, Any]:
    """過去の Match を新しい match_run へ引き継ぐための行データ。"""
    return {
        "talent_id": match.talent_id,
        "project_id": match.project_id,
        "score": match.score,
        "score_band": match.score_band,
        "score_breakdown": match.score_breakdown if isinstance(match.score_breakdown, dict) else {},
        "ai_score": match.ai_score,
        "reason": match.reason,
        "recommendation_points": match.recommendation_points,
        "ai_judged_at": match.ai_judged_at,
        "is_candidate": bool(match.is_candidate),
        "reused": True,
    }


def insert_matches(
    session: Session,
    *,
    match_run_id: UUID,
    rows: list[dict[str, Any]],
) -> list[Match]:
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
            ai_score=row.get("ai_score"),
            reason=row.get("reason"),
            recommendation_points=row.get("recommendation_points"),
            ai_judged_at=row.get("ai_judged_at"),
            is_candidate=bool(row.get("is_candidate", False)),
            created_at=now,
        )
        for row in rows
    ]
    session.add_all(objects)
    session.flush()
    return objects


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


def ensure_match_indexes(session: Session) -> None:
    session.execute(
        text("CREATE INDEX IF NOT EXISTS idx_matches_run ON matches (match_run_id)")
    )
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_matches_talent_project ON matches (talent_id, project_id)"
        )
    )
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_matches_project_talent ON matches (project_id, talent_id)"
        )
    )
    session.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_matches_pair_created ON matches (talent_id, project_id, created_at DESC)"
        )
    )
    session.flush()
