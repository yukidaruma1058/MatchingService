"""人材 API。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.batch_runner import BatchRunTimeoutError, read_last_batch_error, run_batch_job, start_batch_job
from app.deps import get_db
from app.entity_delete import delete_talent_cascade
from app.manual_entity import create_manual_placeholder_email
from app.match_run_query import latest_completed_match_run
from app.models import Company, Email, Match, MatchRun, OutreachMessage, OutreachReply, Project, Talent, TalentSkillSheet
from app.outreach_status import (
    ProposalSideStatus,
    compute_outreach_status,
    is_valid_outreach_reply,
    latest_reply_for_match,
    project_proposal_side_status,
    talent_proposal_side_status,
)
from app.schemas import TalentDetail, TalentListItem, TalentSkillSheetItem

router = APIRouter(prefix="/api/talents", tags=["talents"])



class TalentMatchItem(BaseModel):
    match_id: str
    match_run_id: str
    project_id: str
    project_title: str | None = None
    project_code: str | None = None
    location: str | None = None
    rate_min: int | None = None
    rate_max: int | None = None
    required_skills: list[str] = []
    distributor_company_id: str | None = None
    distributor_company_name: str | None = None
    score: int
    score_band: str | None = None
    score_breakdown: dict | None = None
    ai_score: int | None = None
    reason: str | None = None
    # 後方互換（統合ステータス: 人材提案優先）
    reply_judgment: str | None = None
    reply_id: str | None = None
    reply_body: str | None = None
    reply_received_at: str | None = None
    outreach_status: str = "none"
    # 案件提案結果（人材紹介メールへ）
    talent_proposal_status: str = "none"
    talent_proposal_reply_judgment: str | None = None
    talent_proposal_reply_id: str | None = None
    talent_proposal_reply_body: str | None = None
    talent_proposal_reply_received_at: str | None = None
    # 人材提案結果（案件配信元へ）
    project_proposal_status: str = "none"
    project_proposal_reply_judgment: str | None = None
    project_proposal_reply_id: str | None = None
    project_proposal_reply_body: str | None = None
    project_proposal_reply_received_at: str | None = None


class TalentUpdateRequest(BaseModel):
    """人材プロフィールの部分更新。送信したフィールドだけ反映する。"""

    display_name: str | None = Field(None, min_length=1, max_length=128)
    affiliation: str | None = None
    age: int | None = Field(None, ge=0, le=120)
    gender: str | None = Field(None, max_length=16)
    experience_years: int | None = Field(None, ge=0, le=80)
    desired_rate: int | None = Field(None, ge=0, le=1000)
    available_from: str | None = Field(None, max_length=64)
    work_style: str | None = Field(None, max_length=255)
    nearest_station: str | None = Field(None, max_length=64)
    skills: list[str] | None = None
    source_company_name: str | None = Field(None, max_length=255)
    is_foreign_national: bool | None = None
    commerce_flow: str | None = Field(None, max_length=64)
    summary: str | None = None
    proposal_cc_emails: list[str] | None = None
    status: str | None = Field(None, pattern="^(active|inactive)$")


class TalentCreateRequest(BaseModel):
    """画面からの人材登録（タイトル+本文 → AI要約）。"""

    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)


@dataclass(frozen=True)
class ProposedProjectStats:
    total: int = 0
    no_reply: int = 0
    ok: int = 0
    ng: int = 0


def _proposed_project_stats(session: Session, talent_ids: list[UUID]) -> dict[UUID, ProposedProjectStats]:
    """人材紹介メールへ送った案件提案を、案件単位で件数内訳する。

    - total: 提案済み案件数
    - no_reply: 未返信（返信なし / 判定不明）
    - ok / ng: 最新返信の判定
    """
    if not talent_ids:
        return {}
    talent_id_expr = func.coalesce(OutreachMessage.talent_id, Match.talent_id)
    proposal_rows = session.execute(
        select(
            talent_id_expr.label("talent_id"),
            OutreachMessage.project_id,
            OutreachMessage.id.label("message_id"),
            OutreachMessage.sent_at,
        )
        .select_from(OutreachMessage)
        .outerjoin(Match, Match.id == OutreachMessage.match_id)
        .where(
            OutreachMessage.kind == "talent_proposal",
            OutreachMessage.status == "sent",
            OutreachMessage.project_id.is_not(None),
            talent_id_expr.in_(talent_ids),
        )
        .order_by(talent_id_expr, OutreachMessage.project_id, OutreachMessage.sent_at.desc())
    ).all()

    latest_message_by_key: dict[tuple[UUID, UUID], UUID] = {}
    for row in proposal_rows:
        if row.talent_id is None or row.project_id is None:
            continue
        key = (row.talent_id, row.project_id)
        if key not in latest_message_by_key:
            latest_message_by_key[key] = row.message_id

    if not latest_message_by_key:
        return {}

    message_ids = list(latest_message_by_key.values())
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
    for (talent_id, _project_id), message_id in latest_message_by_key.items():
        buckets[talent_id]["total"] += 1
        judgment = latest_judgment.get(message_id)
        if judgment == "ok":
            buckets[talent_id]["ok"] += 1
        elif judgment == "ng":
            buckets[talent_id]["ng"] += 1
        else:
            # 未返信・判定不明は「返信なし」として集計
            buckets[talent_id]["no_reply"] += 1

    return {
        talent_id: ProposedProjectStats(
            total=vals["total"],
            no_reply=vals["no_reply"],
            ok=vals["ok"],
            ng=vals["ng"],
        )
        for talent_id, vals in buckets.items()
    }


def _skill_sheet_presence(session: Session, talent_ids: list[UUID]) -> dict[UUID, bool]:
    """人材ごとのスキルシート有無（access_status=ok が1件以上）。"""
    if not talent_ids:
        return {}
    rows = session.execute(
        select(TalentSkillSheet.talent_id)
        .where(
            TalentSkillSheet.talent_id.in_(talent_ids),
            TalentSkillSheet.access_status == "ok",
        )
        .distinct()
    ).all()
    return {row[0]: True for row in rows}


def _to_list_item(
    row: Talent,
    *,
    proposed: ProposedProjectStats | None = None,
    has_skill_sheet: bool = False,
    company_name: str | None = None,
    email_received_at: str | None = None,
) -> TalentListItem:
    skills = row.skills if isinstance(row.skills, list) else []
    stats = proposed or ProposedProjectStats()
    resolved_company = (company_name or "").strip() or (row.source_company_name or "").strip() or None
    return TalentListItem(
        id=str(row.id),
        display_name=row.display_name,
        skills=[str(s) for s in skills],
        desired_rate=row.desired_rate,
        available_from=row.available_from,
        work_style=row.work_style,
        nearest_station=row.nearest_station,
        is_foreign_national=row.is_foreign_national,
        commerce_flow=row.commerce_flow,
        summary=row.summary,
        status=row.status,
        email_id=str(row.email_id),
        created_at=row.created_at.isoformat() if row.created_at else "",
        affiliation=row.affiliation,
        age=row.age,
        source_company_name=resolved_company,
        introducer_company_id=str(row.introducer_company_id) if row.introducer_company_id else None,
        proposed_project_count=stats.total,
        proposed_no_reply_count=stats.no_reply,
        proposed_ok_count=stats.ok,
        proposed_ng_count=stats.ng,
        has_skill_sheet=has_skill_sheet,
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


def _company_names_by_id(session: Session, company_ids: set[UUID]) -> dict[UUID, str]:
    if not company_ids:
        return {}
    rows = session.scalars(select(Company).where(Company.id.in_(company_ids))).all()
    return {row.id: row.name for row in rows if (row.name or "").strip()}


def _to_detail(session: Session, row: Talent) -> TalentDetail:
    email = session.get(Email, row.email_id)
    company_names = _company_names_by_id(
        session,
        {row.introducer_company_id} if row.introducer_company_id else set(),
    )
    company_name = company_names.get(row.introducer_company_id) if row.introducer_company_id else None
    stats = _proposed_project_stats(session, [row.id])
    sheets = list(
        session.scalars(
            select(TalentSkillSheet)
            .where(TalentSkillSheet.talent_id == row.id)
            .order_by(TalentSkillSheet.created_at.desc())
        ).all()
    )
    has_skill_sheet = any(s.access_status == "ok" for s in sheets)
    base = _to_list_item(
        row,
        proposed=stats.get(row.id),
        has_skill_sheet=has_skill_sheet,
        company_name=company_name,
        email_received_at=email.received_at.isoformat() if email and email.received_at else None,
    )
    return TalentDetail(
        **base.model_dump(),
        gender=row.gender,
        experience_years=row.experience_years,
        proposal_cc_emails=[str(a) for a in row.proposal_cc_emails] if isinstance(row.proposal_cc_emails, list) else [],
        email_subject=email.subject if email else None,
        email_from=email.from_address if email else None,
        email_label=email.label if email else None,
        skill_sheets=[
            TalentSkillSheetItem(
                id=str(s.id),
                filename=s.filename or "",
                content_type=s.content_type,
                size_bytes=s.size_bytes,
                source_type=s.source_type,
                access_status=s.access_status,
                web_view_link=s.web_view_link,
                error_message=s.error_message,
                experience_extract_status=s.experience_extract_status,
            )
            for s in sheets
        ],
    )


@router.get("", response_model=list[TalentListItem])
def list_talents(session: Session = Depends(get_db)) -> list[TalentListItem]:
    rows = list(session.scalars(select(Talent).order_by(Talent.created_at.desc())).all())
    talent_ids = [row.id for row in rows]
    stats = _proposed_project_stats(session, talent_ids)
    sheets = _skill_sheet_presence(session, talent_ids)
    company_names = _company_names_by_id(
        session,
        {row.introducer_company_id for row in rows if row.introducer_company_id},
    )
    received_at = _email_received_at_by_id(session, {row.email_id for row in rows})
    return [
        _to_list_item(
            row,
            proposed=stats.get(row.id),
            has_skill_sheet=bool(sheets.get(row.id)),
            company_name=company_names.get(row.introducer_company_id) if row.introducer_company_id else None,
            email_received_at=received_at.get(row.email_id),
        )
        for row in rows
    ]


@router.post("", response_model=TalentDetail, status_code=201)
def create_talent(body: TalentCreateRequest, session: Session = Depends(get_db)) -> TalentDetail:
    """タイトル+本文を AI 要約して人材登録する。ルール採点はバックグラウンドで実行する。"""
    title = body.title.strip()
    text = body.body.strip()
    if not title:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "タイトルを入力してください。"},
        )
    if not text:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "本文を入力してください。"},
        )

    email = create_manual_placeholder_email(
        session,
        email_type="talent",
        subject=title,
        body_text=text,
    )
    email_id = email.id
    session.commit()

    try:
        result = run_batch_job(
            "manual_register",
            timeout_seconds=600,
            extra_env={"MANUAL_EMAIL_ID": str(email_id)},
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "ERR-0030", "error_message": str(exc)},
        ) from exc
    except BatchRunTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={"error_code": "ERR-0030", "error_message": "AI要約がタイムアウトしました。"},
        ) from exc

    if result.exit_code != 0:
        error = read_last_batch_error(after_byte_offset=result.log_offset_before) or {
            "error_code": "ERR-0030",
            "error_message": "人材の AI 要約登録に失敗しました。",
        }
        raise HTTPException(status_code=500, detail=error)

    row = session.scalar(select(Talent).where(Talent.email_id == email_id))
    if row is None:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "ERR-0030", "error_message": "人材の登録結果が見つかりません。"},
        )

    try:
        start_batch_job("match", extra_env={"MATCH_TALENT_IDS": str(row.id)})
    except FileNotFoundError:
        pass

    session.refresh(row)
    return _to_detail(session, row)


@router.get("/{talent_id}", response_model=TalentDetail)
def get_talent(talent_id: UUID, session: Session = Depends(get_db)) -> TalentDetail:
    row = session.get(Talent, talent_id)
    if row is None:
        raise HTTPException(status_code=404, detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"})
    return _to_detail(session, row)


@router.patch("/{talent_id}", response_model=TalentDetail)
def update_talent(
    talent_id: UUID,
    body: TalentUpdateRequest,
    session: Session = Depends(get_db),
) -> TalentDetail:
    """人材プロフィールを部分更新する。"""
    row = session.get(Talent, talent_id)
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

    if "display_name" in updates:
        name = str(updates["display_name"] or "").strip()
        if not name:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "名前は必須です。"},
            )
        row.display_name = name
    if "affiliation" in updates:
        text = updates["affiliation"]
        row.affiliation = str(text).strip() if text is not None and str(text).strip() else None
    if "age" in updates:
        row.age = updates["age"]
    if "gender" in updates:
        text = updates["gender"]
        row.gender = str(text).strip()[:16] if text is not None and str(text).strip() else None
    if "experience_years" in updates:
        row.experience_years = updates["experience_years"]
    if "desired_rate" in updates:
        row.desired_rate = updates["desired_rate"]
    if "available_from" in updates:
        text = updates["available_from"]
        row.available_from = str(text).strip() if text is not None and str(text).strip() else None
    if "work_style" in updates:
        text = updates["work_style"]
        row.work_style = str(text).strip() if text is not None and str(text).strip() else None
    if "nearest_station" in updates:
        text = updates["nearest_station"]
        row.nearest_station = str(text).strip() if text is not None and str(text).strip() else None
    if "skills" in updates:
        row.skills = _normalize_string_list(updates["skills"])
    if "source_company_name" in updates:
        text = updates["source_company_name"]
        row.source_company_name = str(text).strip() if text is not None and str(text).strip() else None
    if "is_foreign_national" in updates:
        row.is_foreign_national = updates["is_foreign_national"]
    if "commerce_flow" in updates:
        text = updates["commerce_flow"]
        row.commerce_flow = str(text).strip() if text is not None and str(text).strip() else None
    if "summary" in updates:
        text = updates["summary"]
        row.summary = str(text).strip() if text is not None and str(text).strip() else None
    if "proposal_cc_emails" in updates:
        row.proposal_cc_emails = _normalize_string_list(updates["proposal_cc_emails"])
    if "status" in updates and updates["status"] is not None:
        row.status = updates["status"]

    row.updated_at = datetime.now().astimezone()
    session.commit()
    session.refresh(row)
    return _to_detail(session, row)


@router.delete("/{talent_id}")
def delete_talent(talent_id: UUID, session: Session = Depends(get_db)) -> dict:
    """人材と関連するマッチ・提案・返信・取込元メールを削除する。"""
    try:
        deleted = delete_talent_cascade(session, talent_id)
    except LookupError:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"},
        ) from None
    return {"status": "ok", "message": "人材を削除しました", "deleted": deleted}


@router.get("/{talent_id}/matches", response_model=list[TalentMatchItem])
def list_talent_matches(talent_id: UUID, session: Session = Depends(get_db)) -> list[TalentMatchItem]:
    """直近 match_run における当該人材の案件採点結果をルールスコア降順で返す。"""
    talent = session.get(Talent, talent_id)
    if talent is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"},
        )

    latest_run = latest_completed_match_run(session)
    if latest_run is None:
        return []

    matches = list(
        session.scalars(
            select(Match)
            .where(Match.match_run_id == latest_run.id, Match.talent_id == talent_id)
            .order_by(Match.score.desc())
        ).all()
    )
    if not matches:
        return []

    project_ids = {m.project_id for m in matches}
    projects = {
        p.id: p
        for p in session.scalars(select(Project).where(Project.id.in_(project_ids))).all()
    }
    company_names = _company_names_by_id(
        session,
        {p.distributor_company_id for p in projects.values() if p.distributor_company_id},
    )

    items: list[TalentMatchItem] = []
    for match in matches:
        project = projects.get(match.project_id)
        distributor_id = project.distributor_company_id if project else None
        distributor_name = company_names.get(distributor_id) if distributor_id else None

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
            session.rollback()
            judgment = None
            reply_id = None
            reply_body = None
            reply_received_at = None
            status = "none"
            talent_side = ProposalSideStatus()
            project_side = ProposalSideStatus()
        items.append(
            TalentMatchItem(
                match_id=str(match.id),
                match_run_id=str(match.match_run_id),
                project_id=str(match.project_id),
                project_title=project.title if project else None,
                project_code=project.project_code if project else None,
                location=project.location if project else None,
                rate_min=project.rate_min if project else None,
                rate_max=project.rate_max if project else None,
                required_skills=list(project.required_skills or []) if project else [],
                distributor_company_id=str(distributor_id) if distributor_id else None,
                distributor_company_name=distributor_name,
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
