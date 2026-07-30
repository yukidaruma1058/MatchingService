"""案件 API。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import get_db
from app.entity_delete import delete_project_cascade
from app.models import (
    Company,
    Email,
    Match,
    MatchRun,
    OutreachMessage,
    OutreachMessageTalent,
    OutreachReply,
    Project,
    Talent,
    TalentSkillSheet,
)
from app.outreach_status import (
    ProposalSideStatus,
    compute_outreach_status,
    is_valid_outreach_reply,
    latest_reply_for_match,
    project_proposal_side_status,
    talent_proposal_side_status,
)
from app.schemas import ProjectDetail, ProjectListItem

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectMatchItem(BaseModel):
    match_id: str
    match_run_id: str
    talent_id: str
    display_name: str | None = None
    source_company_name: str | None = None
    introducer_company_id: str | None = None
    skills: list[str] = []
    desired_rate: int | None = None
    has_skill_sheet: bool = False
    score: int
    score_band: str | None = None
    score_breakdown: dict | None = None
    ai_score: int | None = None
    reason: str | None = None
    reply_judgment: str | None = None
    reply_id: str | None = None
    reply_body: str | None = None
    reply_received_at: str | None = None
    outreach_status: str = "none"
    talent_proposal_status: str = "none"
    talent_proposal_reply_judgment: str | None = None
    talent_proposal_reply_id: str | None = None
    talent_proposal_reply_body: str | None = None
    talent_proposal_reply_received_at: str | None = None
    project_proposal_status: str = "none"
    project_proposal_reply_judgment: str | None = None
    project_proposal_reply_id: str | None = None
    project_proposal_reply_body: str | None = None
    project_proposal_reply_received_at: str | None = None


class ProjectUpdateRequest(BaseModel):
    """案件情報の部分更新。送信したフィールドだけ反映する。"""

    title: str | None = Field(None, min_length=1, max_length=255)
    project_code: str | None = Field(None, max_length=32)
    required_skills: list[str] | None = None
    rate_min: int | None = Field(None, ge=0, le=1000)
    rate_max: int | None = Field(None, ge=0, le=1000)
    location: str | None = Field(None, max_length=128)
    work_style: str | None = Field(None, max_length=255)
    working_hours: str | None = Field(None, max_length=128)
    start_date: str | None = Field(None, max_length=64)
    foreign_nationality_ng: bool | None = None
    commerce_flow_limit: str | None = Field(None, max_length=64)
    settlement_range: str | None = Field(None, max_length=64)
    interview_count: int | None = Field(None, ge=0, le=20)
    headcount: int | None = Field(None, ge=0, le=100)
    summary: str | None = None
    proposal_cc_emails: list[str] | None = None
    status: str | None = Field(None, pattern="^(open|closed)$")


@dataclass(frozen=True)
class ProposedTalentStats:
    total: int = 0
    no_reply: int = 0
    ok: int = 0
    ng: int = 0


def _proposed_talent_stats(session: Session, project_ids: list[UUID]) -> dict[UUID, ProposedTalentStats]:
    """案件配信元へ送った人材提案を、人材単位で件数内訳する。

    - total: 提案済み人材数
    - no_reply: 未返信（返信なし / 判定不明）
    - ok / ng: 最新返信の判定
    """
    if not project_ids:
        return {}

    proposal_rows = session.execute(
        select(
            OutreachMessage.project_id,
            OutreachMessageTalent.talent_id,
            OutreachMessage.id.label("message_id"),
            OutreachMessage.sent_at,
        )
        .select_from(OutreachMessage)
        .join(
            OutreachMessageTalent,
            OutreachMessageTalent.outreach_message_id == OutreachMessage.id,
        )
        .where(
            OutreachMessage.kind == "project_proposal",
            OutreachMessage.status == "sent",
            OutreachMessage.project_id.in_(project_ids),
        )
        .order_by(OutreachMessage.project_id, OutreachMessageTalent.talent_id, OutreachMessage.sent_at.desc())
    ).all()

    latest_message_by_key: dict[tuple[UUID, UUID], UUID] = {}
    for row in proposal_rows:
        if row.project_id is None or row.talent_id is None:
            continue
        key = (row.project_id, row.talent_id)
        if key not in latest_message_by_key:
            latest_message_by_key[key] = row.message_id

    if not latest_message_by_key:
        return {}

    message_ids = list({mid for mid in latest_message_by_key.values()})
    proposals = {
        row.id: row
        for row in session.scalars(select(OutreachMessage).where(OutreachMessage.id.in_(message_ids))).all()
    }
    reply_rows = session.execute(
        select(OutreachReply)
        .where(OutreachReply.outreach_message_id.in_(message_ids))
        .order_by(OutreachReply.outreach_message_id, OutreachReply.received_at.desc())
    ).scalars().all()
    latest_judgment: dict[UUID, str] = {}
    for reply in reply_rows:
        if reply.outreach_message_id in latest_judgment:
            continue
        proposal = proposals.get(reply.outreach_message_id)
        if proposal is not None and not is_valid_outreach_reply(session, proposal, reply):
            continue
        latest_judgment[reply.outreach_message_id] = reply.judgment

    buckets: dict[UUID, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "no_reply": 0, "ok": 0, "ng": 0}
    )
    for (project_id, _talent_id), message_id in latest_message_by_key.items():
        buckets[project_id]["total"] += 1
        judgment = latest_judgment.get(message_id)
        if judgment == "ok":
            buckets[project_id]["ok"] += 1
        elif judgment == "ng":
            buckets[project_id]["ng"] += 1
        else:
            buckets[project_id]["no_reply"] += 1

    return {
        project_id: ProposedTalentStats(
            total=vals["total"],
            no_reply=vals["no_reply"],
            ok=vals["ok"],
            ng=vals["ng"],
        )
        for project_id, vals in buckets.items()
    }


def _company_names_by_id(session: Session, company_ids: set[UUID]) -> dict[UUID, str]:
    if not company_ids:
        return {}
    rows = session.scalars(select(Company).where(Company.id.in_(company_ids))).all()
    return {row.id: row.name for row in rows if (row.name or "").strip()}


def _to_list_item(
    row: Project,
    *,
    proposed: ProposedTalentStats | None = None,
    distributor_company_name: str | None = None,
    email_received_at: str | None = None,
) -> ProjectListItem:
    skills = row.required_skills if isinstance(row.required_skills, list) else []
    stats = proposed or ProposedTalentStats()
    return ProjectListItem(
        id=str(row.id),
        title=row.title,
        project_code=row.project_code,
        required_skills=[str(s) for s in skills],
        rate_min=row.rate_min,
        rate_max=row.rate_max,
        location=row.location,
        work_style=row.work_style,
        working_hours=row.working_hours,
        start_date=row.start_date,
        foreign_nationality_ng=row.foreign_nationality_ng,
        commerce_flow_limit=row.commerce_flow_limit,
        settlement_range=row.settlement_range,
        interview_count=row.interview_count,
        headcount=row.headcount,
        summary=row.summary,
        status=row.status,
        email_id=str(row.email_id),
        created_at=row.created_at.isoformat() if row.created_at else "",
        distributor_company_id=str(row.distributor_company_id) if row.distributor_company_id else None,
        distributor_company_name=distributor_company_name,
        proposed_talent_count=stats.total,
        proposed_no_reply_count=stats.no_reply,
        proposed_ok_count=stats.ok,
        proposed_ng_count=stats.ng,
        email_received_at=email_received_at,
    )


def _email_received_at_by_id(session: Session, email_ids: set[UUID]) -> dict[UUID, str]:
    if not email_ids:
        return {}
    rows = session.scalars(select(Email).where(Email.id.in_(email_ids))).all()
    return {
        row.id: row.received_at.isoformat()
        for row in rows
        if row.received_at is not None
    }


def _normalize_string_list(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    return [str(v).strip() for v in values if str(v).strip()]


def _to_detail(session: Session, row: Project) -> ProjectDetail:
    email = session.get(Email, row.email_id)
    company_names = _company_names_by_id(
        session,
        {row.distributor_company_id} if row.distributor_company_id else set(),
    )
    distributor_name = (
        company_names.get(row.distributor_company_id) if row.distributor_company_id else None
    )
    stats = _proposed_talent_stats(session, [row.id])
    base = _to_list_item(
        row,
        proposed=stats.get(row.id),
        distributor_company_name=distributor_name,
        email_received_at=email.received_at.isoformat() if email and email.received_at else None,
    )
    return ProjectDetail(
        **base.model_dump(),
        proposal_cc_emails=[str(a) for a in row.proposal_cc_emails] if isinstance(row.proposal_cc_emails, list) else [],
        email_subject=email.subject if email else None,
        email_from=email.from_address if email else None,
        email_label=email.label if email else None,
    )


@router.get("", response_model=list[ProjectListItem])
def list_projects(session: Session = Depends(get_db)) -> list[ProjectListItem]:
    rows = list(session.scalars(select(Project).order_by(Project.created_at.desc()).limit(200)).all())
    stats = _proposed_talent_stats(session, [row.id for row in rows])
    company_names = _company_names_by_id(
        session,
        {row.distributor_company_id for row in rows if row.distributor_company_id},
    )
    received_at = _email_received_at_by_id(session, {row.email_id for row in rows})
    return [
        _to_list_item(
            row,
            proposed=stats.get(row.id),
            distributor_company_name=(
                company_names.get(row.distributor_company_id) if row.distributor_company_id else None
            ),
            email_received_at=received_at.get(row.email_id),
        )
        for row in rows
    ]


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: UUID, session: Session = Depends(get_db)) -> ProjectDetail:
    row = session.get(Project, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"})
    return _to_detail(session, row)


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: UUID,
    body: ProjectUpdateRequest,
    session: Session = Depends(get_db),
) -> ProjectDetail:
    """案件情報を部分更新する。"""
    row = session.get(Project, project_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"},
        )

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "更新する項目がありません。"},
        )

    if "title" in updates:
        title = str(updates["title"] or "").strip()
        if not title:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "案件名は必須です。"},
            )
        row.title = title
    if "project_code" in updates:
        text = updates["project_code"]
        row.project_code = str(text).strip() if text is not None and str(text).strip() else None
    if "required_skills" in updates:
        row.required_skills = _normalize_string_list(updates["required_skills"])
    if "rate_min" in updates:
        row.rate_min = updates["rate_min"]
    if "rate_max" in updates:
        row.rate_max = updates["rate_max"]
    if "location" in updates:
        text = updates["location"]
        row.location = str(text).strip() if text is not None and str(text).strip() else None
    if "work_style" in updates:
        text = updates["work_style"]
        row.work_style = str(text).strip() if text is not None and str(text).strip() else None
    if "working_hours" in updates:
        text = updates["working_hours"]
        row.working_hours = str(text).strip() if text is not None and str(text).strip() else None
    if "start_date" in updates:
        text = updates["start_date"]
        row.start_date = str(text).strip() if text is not None and str(text).strip() else None
    if "foreign_nationality_ng" in updates:
        row.foreign_nationality_ng = updates["foreign_nationality_ng"]
    if "commerce_flow_limit" in updates:
        text = updates["commerce_flow_limit"]
        row.commerce_flow_limit = str(text).strip() if text is not None and str(text).strip() else None
    if "settlement_range" in updates:
        text = updates["settlement_range"]
        row.settlement_range = str(text).strip() if text is not None and str(text).strip() else None
    if "interview_count" in updates:
        row.interview_count = updates["interview_count"]
    if "headcount" in updates:
        row.headcount = updates["headcount"]
    if "summary" in updates:
        text = updates["summary"]
        row.summary = str(text).strip() if text is not None and str(text).strip() else None
    if "proposal_cc_emails" in updates:
        row.proposal_cc_emails = _normalize_string_list(updates["proposal_cc_emails"])
    if "status" in updates and updates["status"] is not None:
        row.status = updates["status"]

    if row.rate_min is not None and row.rate_max is not None and row.rate_min > row.rate_max:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "単価下限は上限以下にしてください。"},
        )

    row.updated_at = datetime.now().astimezone()
    session.commit()
    session.refresh(row)
    return _to_detail(session, row)


@router.delete("/{project_id}")
def delete_project(project_id: UUID, session: Session = Depends(get_db)) -> dict:
    """案件と関連するマッチ・提案・返信・取込元メールを削除する。"""
    try:
        deleted = delete_project_cascade(session, project_id)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"},
        ) from None
    return {"status": "ok", "message": "案件を削除しました", "deleted": deleted}


def _skill_sheet_presence(session: Session, talent_ids: set[UUID] | list[UUID]) -> dict[UUID, bool]:
    """人材ごとのスキルシート有無（access_status=ok が1件以上）。"""
    ids = list(talent_ids)
    if not ids:
        return {}
    rows = session.execute(
        select(TalentSkillSheet.talent_id)
        .where(
            TalentSkillSheet.talent_id.in_(ids),
            TalentSkillSheet.access_status == "ok",
        )
        .distinct()
    ).all()
    return {row[0]: True for row in rows}


@router.get("/{project_id}/matches", response_model=list[ProjectMatchItem])
def list_project_matches(project_id: UUID, session: Session = Depends(get_db)) -> list[ProjectMatchItem]:
    """直近 match_run における当該案件の人材採点結果をルールスコア降順で返す。"""
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"},
        )

    latest_run = session.scalar(select(MatchRun).order_by(MatchRun.started_at.desc()).limit(1))
    if latest_run is None:
        return []

    matches = list(
        session.scalars(
            select(Match)
            .where(Match.match_run_id == latest_run.id, Match.project_id == project_id)
            .order_by(Match.score.desc())
        ).all()
    )
    if not matches:
        return []

    talent_ids = {m.talent_id for m in matches}
    talents = {
        t.id: t
        for t in session.scalars(select(Talent).where(Talent.id.in_(talent_ids))).all()
    }
    company_names = _company_names_by_id(
        session,
        {t.introducer_company_id for t in talents.values() if t.introducer_company_id},
    )
    skill_sheets = _skill_sheet_presence(session, talent_ids)

    items: list[ProjectMatchItem] = []
    for match in matches:
        talent = talents.get(match.talent_id)
        skills = talent.skills if talent and isinstance(talent.skills, list) else []
        introducer_id = talent.introducer_company_id if talent else None
        source_company = None
        if talent is not None:
            if introducer_id and introducer_id in company_names:
                source_company = company_names[introducer_id]
            else:
                source_company = (talent.source_company_name or "").strip() or None
        judgment: str | None = None
        reply_id: str | None = None
        reply_body: str | None = None
        reply_received_at: str | None = None
        status = "none"
        talent_side = ProposalSideStatus()
        project_side = ProposalSideStatus()
        try:
            talent_side = talent_proposal_side_status(session, match_id=match.id)
            project_side = project_proposal_side_status(
                session,
                project_id=match.project_id,
                talent_id=match.talent_id,
            )
            reply = latest_reply_for_match(
                session,
                match_id=match.id,
                project_id=match.project_id,
                talent_id=match.talent_id,
            )
            if reply is not None:
                judgment = reply.judgment
                reply_id = str(reply.id)
                reply_body = reply.body_text
                reply_received_at = reply.received_at.isoformat() if reply.received_at else None
            status = compute_outreach_status(
                session,
                match_id=match.id,
                project_id=match.project_id,
                talent_id=match.talent_id,
            )
        except Exception:  # noqa: BLE001
            # outreach テーブル未作成時などでも採点一覧は返す
            session.rollback()
            judgment = None
            reply_id = None
            reply_body = None
            reply_received_at = None
            status = "none"
            talent_side = ProposalSideStatus()
            project_side = ProposalSideStatus()
        items.append(
            ProjectMatchItem(
                match_id=str(match.id),
                match_run_id=str(match.match_run_id),
                talent_id=str(match.talent_id),
                display_name=talent.display_name if talent else None,
                source_company_name=source_company,
                introducer_company_id=str(introducer_id) if introducer_id else None,
                skills=[str(s) for s in skills],
                desired_rate=talent.desired_rate if talent else None,
                has_skill_sheet=bool(skill_sheets.get(match.talent_id)),
                score=match.score,
                score_band=match.score_band,
                score_breakdown=match.score_breakdown if isinstance(match.score_breakdown, dict) else None,
                ai_score=match.ai_score,
                reason=match.reason,
                reply_judgment=judgment,
                reply_id=reply_id,
                reply_body=reply_body,
                reply_received_at=reply_received_at,
                outreach_status=status,
                talent_proposal_status=talent_side.status,
                talent_proposal_reply_judgment=talent_side.reply_judgment,
                talent_proposal_reply_id=talent_side.reply_id,
                talent_proposal_reply_body=talent_side.reply_body,
                talent_proposal_reply_received_at=talent_side.reply_received_at,
                project_proposal_status=project_side.status,
                project_proposal_reply_judgment=project_side.reply_judgment,
                project_proposal_reply_id=project_side.reply_id,
                project_proposal_reply_body=project_side.reply_body,
                project_proposal_reply_received_at=project_side.reply_received_at,
            )
        )
    return items
