"""マッチング実行（BAT-003 / BAT-004）API。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.batch_runner import BatchRunTimeoutError, read_last_batch_error, run_batch_job
from app.deps import get_db
from app.match_run_query import latest_completed_match_run
from app.models import (
    Match,
    MatchRun,
    OutreachMessage,
    OutreachMessageTalent,
    OutreachReply,
    Project,
    Talent,
)

router = APIRouter(prefix="/api/match-runs", tags=["match-runs"])


class MatchRunCreateRequest(BaseModel):
    trigger: str = "manual"
    ai_judgement_top_n: int | None = Field(default=None, ge=1, le=20)
    force: bool = False


class MatchRunResponse(BaseModel):
    id: str
    trigger: str
    status: str
    ai_judgement_top_n: int | None = None
    stats: dict | None = None
    started_at: str | None = None
    finished_at: str | None = None


class MatchListItem(BaseModel):
    id: str
    talent_id: str
    project_id: str
    score: int
    score_band: str | None = None
    score_breakdown: dict | None = None
    display_name: str | None = None
    project_title: str | None = None
    desired_rate: int | None = None
    skills: list[str] = []
    ai_score: int | None = None
    reason: str | None = None
    reply_judgment: str | None = None
    reply_id: str | None = None
    talent_sent_at: str | None = None
    project_sent_at: str | None = None
    outreach_status: str = "none"


class AiJudgeRequest(BaseModel):
    project_id: str | None = None
    match_ids: list[str] | None = None


def _raise_batch_error(*, fallback_message: str, after_byte_offset: int | None = None) -> None:
    error = read_last_batch_error(after_byte_offset=after_byte_offset)
    if error:
        raise HTTPException(status_code=500, detail=error)
    raise HTTPException(
        status_code=500,
        detail={"error_code": "ERR-0030", "error_message": fallback_message},
    )


def _to_run_response(row: MatchRun) -> MatchRunResponse:
    return MatchRunResponse(
        id=str(row.id),
        trigger=row.trigger,
        status=row.status,
        ai_judgement_top_n=row.ai_judgement_top_n,
        stats=row.stats if isinstance(row.stats, dict) else None,
        started_at=row.started_at.isoformat() if row.started_at else None,
        finished_at=row.finished_at.isoformat() if row.finished_at else None,
    )


@router.post("", response_model=MatchRunResponse)
def create_match_run(body: MatchRunCreateRequest | None = None) -> MatchRunResponse:
    """ルールスコア採点（BAT-003）を実行する。

    force=true のときのみ全件強制再採点。それ以外は増分。
    """
    force = bool(body and body.force)
    extra_env = {"MATCH_FORCE_RESCORE": "1"} if force else None
    try:
        result = run_batch_job("match", timeout_seconds=1800 if force else 600, extra_env=extra_env)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "ERR-0030", "error_message": str(exc)},
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
            fallback_message="ルールスコア採点に失敗しました。",
            after_byte_offset=result.log_offset_before,
        )

    from app.db import create_session_factory

    session_factory, _ = create_session_factory()
    with session_factory() as session:
        row = latest_completed_match_run(session)
        if row is None:
            raise HTTPException(
                status_code=500,
                detail={"error_code": "ERR-0030", "error_message": "match_run が作成されませんでした。"},
            )
        return _to_run_response(row)


@router.get("", response_model=list[MatchRunResponse])
def list_match_runs(session: Session = Depends(get_db)) -> list[MatchRunResponse]:
    rows = session.scalars(select(MatchRun).order_by(MatchRun.started_at.desc()).limit(20)).all()
    return [_to_run_response(row) for row in rows]


@router.post("/{match_run_id}/ai-judge", response_model=MatchRunResponse)
def run_ai_judge(
    match_run_id: str,
    body: AiJudgeRequest | None = None,
    session: Session = Depends(get_db),
) -> MatchRunResponse:
    try:
        uid = UUID(match_run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "不正な ID です。"},
        ) from exc
    row = session.get(MatchRun, uid)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"},
        )

    extra_env = {"AI_JUDGE_MATCH_RUN_ID": str(uid)}
    if body and body.project_id:
        try:
            UUID(body.project_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "不正な project_id です。"},
            ) from exc
        extra_env["AI_JUDGE_PROJECT_ID"] = body.project_id
    if body and body.match_ids:
        parsed_ids: list[str] = []
        for raw in body.match_ids:
            try:
                parsed_ids.append(str(UUID(raw)))
            except ValueError as exc:
                raise HTTPException(
                    status_code=400,
                    detail={"error_code": "ERR-0001", "error_message": "不正な match_id です。"},
                ) from exc
        if parsed_ids:
            extra_env["AI_JUDGE_MATCH_IDS"] = ",".join(parsed_ids)

    try:
        result = run_batch_job("ai_judge", timeout_seconds=900, extra_env=extra_env)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "ERR-0030", "error_message": str(exc)},
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
            fallback_message="AI判定に失敗しました。",
            after_byte_offset=result.log_offset_before,
        )
    session.refresh(row)
    return _to_run_response(row)


@router.get("/{match_run_id}/matches", response_model=list[MatchListItem])
def list_matches_for_run(match_run_id: str, session: Session = Depends(get_db)) -> list[MatchListItem]:
    try:
        uid = UUID(match_run_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "不正な ID です。"},
        ) from exc
    rows = session.scalars(
        select(Match).where(Match.match_run_id == uid).order_by(Match.score.desc()).limit(2000)
    ).all()
    talent_ids = {row.talent_id for row in rows}
    project_ids = {row.project_id for row in rows}
    match_ids = [row.id for row in rows]
    talents = {
        t.id: t
        for t in session.scalars(select(Talent).where(Talent.id.in_(talent_ids))).all()
    } if talent_ids else {}
    projects = {
        p.id: p
        for p in session.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    } if project_ids else {}

    talent_proposals = list(
        session.scalars(
            select(OutreachMessage).where(
                OutreachMessage.kind == "talent_proposal",
                OutreachMessage.status == "sent",
                OutreachMessage.match_id.in_(match_ids) if match_ids else False,
            )
        ).all()
    ) if match_ids else []
    proposal_by_match: dict[UUID, OutreachMessage] = {}
    for proposal in talent_proposals:
        if proposal.match_id is None:
            continue
        current = proposal_by_match.get(proposal.match_id)
        if current is None or (proposal.sent_at and (current.sent_at is None or proposal.sent_at > current.sent_at)):
            proposal_by_match[proposal.match_id] = proposal

    project_sent: dict[tuple[UUID, UUID], OutreachMessage] = {}
    if project_ids and talent_ids:
        project_rows = session.execute(
            select(OutreachMessage, OutreachMessageTalent)
            .join(
                OutreachMessageTalent,
                OutreachMessageTalent.outreach_message_id == OutreachMessage.id,
            )
            .where(
                OutreachMessage.kind == "project_proposal",
                OutreachMessage.status == "sent",
                OutreachMessage.project_id.in_(project_ids),
            )
        ).all()
        for outreach, link in project_rows:
            if outreach.project_id is None:
                continue
            key = (outreach.project_id, link.talent_id)
            current = project_sent.get(key)
            if current is None or (outreach.sent_at and (current.sent_at is None or outreach.sent_at > current.sent_at)):
                project_sent[key] = outreach

    reply_by_proposal: dict[UUID, OutreachReply] = {}
    proposal_ids = [p.id for p in proposal_by_match.values()]
    proposal_ids.extend(p.id for p in project_sent.values())
    if proposal_ids:
        replies = session.scalars(
            select(OutreachReply).where(OutreachReply.outreach_message_id.in_(proposal_ids))
        ).all()
        for reply in replies:
            current = reply_by_proposal.get(reply.outreach_message_id)
            if current is None or reply.received_at > current.received_at:
                reply_by_proposal[reply.outreach_message_id] = reply

    items: list[MatchListItem] = []
    for row in rows:
        talent = talents.get(row.talent_id)
        project = projects.get(row.project_id)
        skills = talent.skills if talent and isinstance(talent.skills, list) else []
        proposal = proposal_by_match.get(row.id)
        project_msg = project_sent.get((row.project_id, row.talent_id))
        reply = None
        if project_msg is not None:
            reply = reply_by_proposal.get(project_msg.id)
            outreach_status = f"reply_{reply.judgment}" if reply is not None else "project_sent"
        elif proposal is not None:
            reply = reply_by_proposal.get(proposal.id)
            outreach_status = f"reply_{reply.judgment}" if reply is not None else "talent_sent"
        else:
            outreach_status = "none"

        items.append(
            MatchListItem(
                id=str(row.id),
                talent_id=str(row.talent_id),
                project_id=str(row.project_id),
                score=row.score,
                score_band=row.score_band,
                score_breakdown=row.score_breakdown if isinstance(row.score_breakdown, dict) else None,
                display_name=talent.display_name if talent else None,
                project_title=project.title if project else None,
                desired_rate=talent.desired_rate if talent else None,
                skills=[str(s) for s in skills],
                ai_score=row.ai_score,
                reason=row.reason,
                reply_judgment=reply.judgment if reply else None,
                reply_id=str(reply.id) if reply else None,
                talent_sent_at=proposal.sent_at.isoformat() if proposal and proposal.sent_at else None,
                project_sent_at=project_msg.sent_at.isoformat() if project_msg and project_msg.sent_at else None,
                outreach_status=outreach_status,
            )
        )
    return items
