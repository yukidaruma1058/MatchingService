"""提案・返信 API（要員提案 / 案件提案 / 返信上書き）。"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.batch_runner import BatchRunTimeoutError, read_last_batch_error, run_batch_job
from app.constraint_rules import resolve_proposal_commerce_flow
from app.db import load_settings
from app.deps import get_db
from app.models import (
    Company,
    Email,
    Match,
    OutreachMessage,
    OutreachMessageTalent,
    OutreachReply,
    Project,
    Talent,
    TalentSkillSheet,
)
from app.outreach_party import resolve_source_party
from app.outreach_status import (
    compute_outreach_status,
    latest_project_proposal,
    latest_reply_for_proposal,
    latest_talent_proposal,
    project_proposal_side_status,
    talent_proposal_side_status,
)
from app.outreach_templates import (
    TalentProposeLine,
    parse_talent_propose_rate_markup,
    render_talent_propose_body,
)
from app.setting_keys import (
    SETTING_KEY_OWN_COMPANY_NAME,
    SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP,
    SETTING_KEY_TEMPLATE_PROJECT_PROPOSE,
    SETTING_KEY_TEMPLATE_TALENT_PROPOSE,
)
from app.skill_sheet_names import extension_from_filename_or_mime, proposal_attachment_filename
from app.talent_proposal_body import TalentProposalProjectLine, build_talent_proposal_body_multi
from app.talent_recommendation import resolve_recommendation_points

router = APIRouter(prefix="/api/outreach", tags=["outreach"])


def _talent_company_name(session: Session, talent: Talent) -> str | None:
    if talent.introducer_company_id:
        company = session.get(Company, talent.introducer_company_id)
        if company and (company.name or "").strip():
            return company.name.strip()
    name = (talent.source_company_name or "").strip()
    return name or None


class TalentProposeDraftInput(BaseModel):
    """本文は1通分。match_id は後方互換のため残す（未使用可）。"""

    match_id: str | None = None
    body_text: str
    to_address: str | None = None
    cc_addresses: list[str] | None = None


class TalentProposeRequest(BaseModel):
    match_ids: list[str] = Field(default_factory=list)
    drafts: list[TalentProposeDraftInput] | None = None
    to_address: str | None = None
    cc_addresses: list[str] | None = None


class TalentProposePreviewRequest(BaseModel):
    match_ids: list[str] = Field(default_factory=list)


class TalentProposeDraft(BaseModel):
    match_ids: list[str]
    match_id: str
    project_ids: list[str]
    project_id: str
    project_titles: list[str]
    project_title: str | None = None
    to_address: str | None = None
    cc_addresses: list[str] = Field(default_factory=list)
    subject: str
    body_text: str
    already_sent: bool = False


class TalentProposePreviewResponse(BaseModel):
    drafts: list[TalentProposeDraft]


class ProjectProposeRequest(BaseModel):
    project_id: str
    match_ids: list[str] = Field(default_factory=list)
    body_text: str | None = None
    to_address: str | None = None
    cc_addresses: list[str] | None = None


class ProjectProposePreviewRequest(BaseModel):
    project_id: str
    match_ids: list[str] = Field(default_factory=list)


# Gmail 添付合計の目安上限（BAT-009 と同じ 20MB）
_MAX_PROPOSAL_ATTACHMENTS_BYTES = 20 * 1024 * 1024


class ProjectProposeAttachmentItem(BaseModel):
    talent_id: str
    talent_name: str | None = None
    filename: str
    original_filename: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    web_view_link: str | None = None


class ProjectProposeDraft(BaseModel):
    project_id: str
    match_ids: list[str]
    talent_ids: list[str]
    talent_names: list[str]
    to_address: str | None = None
    cc_addresses: list[str] = Field(default_factory=list)
    subject: str
    body_text: str
    already_sent: bool = False
    attachments: list[ProjectProposeAttachmentItem] = Field(default_factory=list)
    attachments_total_bytes: int = 0
    attachments_over_size_limit: bool = False
    attachments_note: str | None = None


class ProjectProposePreviewResponse(BaseModel):
    draft: ProjectProposeDraft


class MatchStatusUpdateRequest(BaseModel):
    judgment: Literal["ok", "ng", "unknown"]
    kind: Literal["talent_proposal", "project_proposal"] = "talent_proposal"


class OutreachActionResponse(BaseModel):
    status: str
    message: str
    sent: int = 0
    failed: int = 0


class MatchStatusUpdateResponse(BaseModel):
    match_id: str
    kind: Literal["talent_proposal", "project_proposal"] = "talent_proposal"
    judgment: str
    judgment_source: str
    reply_id: str
    reply_body: str | None = None
    reply_received_at: str | None = None
    outreach_status: str
    talent_proposal_status: str = "none"
    project_proposal_status: str = "none"
    message: str = "ステータスを更新しました"


def _proposal_cc_list(entity: Talent | Project | None) -> list[str]:
    if entity is None:
        return []
    raw = getattr(entity, "proposal_cc_emails", None)
    if not isinstance(raw, list):
        return []
    return [str(addr).strip() for addr in raw if str(addr).strip()]


def _build_project_propose_attachments(
    session: Session,
    pending_pairs: list[tuple[Talent, Match]],
) -> tuple[list[ProjectProposeAttachmentItem], int, bool, str | None]:
    """送信時に添付されるスキルシート一覧（プレビュー用。実体ダウンロードはしない）。"""
    talent_ids = [talent.id for talent, _ in pending_pairs]
    if not talent_ids:
        return [], 0, False, None

    talents = {talent.id: talent for talent, _ in pending_pairs}
    sheets = list(
        session.scalars(
            select(TalentSkillSheet).where(
                TalentSkillSheet.talent_id.in_(talent_ids),
                TalentSkillSheet.access_status == "ok",
                TalentSkillSheet.drive_file_id.is_not(None),
            )
        ).all()
    )
    name_counts: Counter[str] = Counter()
    items: list[ProjectProposeAttachmentItem] = []
    total_bytes = 0
    for sheet in sheets:
        talent = talents.get(sheet.talent_id)
        if talent is None:
            continue
        ext = extension_from_filename_or_mime(sheet.filename, sheet.content_type)
        base_name = proposal_attachment_filename(display_name=talent.display_name, ext=ext, index=1)
        name_counts[base_name] += 1
        attach_name = proposal_attachment_filename(
            display_name=talent.display_name,
            ext=ext,
            index=name_counts[base_name],
        )
        size = int(sheet.size_bytes) if sheet.size_bytes is not None else 0
        total_bytes += size
        items.append(
            ProjectProposeAttachmentItem(
                talent_id=str(talent.id),
                talent_name=talent.display_name,
                filename=attach_name,
                original_filename=sheet.filename or None,
                content_type=sheet.content_type,
                size_bytes=sheet.size_bytes,
                web_view_link=sheet.web_view_link,
            )
        )

    over_limit = total_bytes > _MAX_PROPOSAL_ATTACHMENTS_BYTES
    note: str | None = None
    if not items:
        note = "添付可能なスキルシートはありません（access_status=ok かつ Drive 保存済みのみ対象）。"
    elif over_limit:
        note = (
            "合計サイズが上限（約20MB）を超える見込みのため、送信時は添付ではなくリンク案内になる場合があります。"
        )
    return items, total_bytes, over_limit, note


def _parse_uuid(value: str, field_name: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": f"不正な {field_name} です。"},
        ) from exc


def _raise_batch_error(*, fallback_message: str) -> None:
    error = read_last_batch_error()
    if error:
        raise HTTPException(status_code=500, detail=error)
    raise HTTPException(
        status_code=500,
        detail={"error_code": "ERR-0030", "error_message": fallback_message},
    )


def _already_sent_match_ids(session: Session, match_ids: list[UUID]) -> set[UUID]:
    if not match_ids:
        return set()
    rows = session.scalars(
        select(OutreachMessage.match_id).where(
            OutreachMessage.kind == "talent_proposal",
            OutreachMessage.status == "sent",
            OutreachMessage.match_id.in_(match_ids),
        )
    ).all()
    return {mid for mid in rows if mid is not None}


def _reply_subject(source_subject: str | None, project_title: str | None) -> str:
    subject = source_subject or project_title or "案件のご提案"
    if subject.lower().startswith("re:"):
        return subject
    return f"Re: {subject}"


@router.post("/talent-propose/preview", response_model=TalentProposePreviewResponse)
def talent_propose_preview(
    body: TalentProposePreviewRequest,
    session: Session = Depends(get_db),
) -> TalentProposePreviewResponse:
    if not body.match_ids:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "match_ids が空です。"},
        )
    ids = [_parse_uuid(mid, "match_id") for mid in body.match_ids]
    matches = list(session.scalars(select(Match).where(Match.id.in_(ids))).all())
    by_id = {m.id: m for m in matches}
    missing = [str(i) for i in ids if i not in by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象のマッチが見つかりません。"},
        )

    ordered = [by_id[i] for i in ids]
    talent_ids = {m.talent_id for m in ordered}
    if len(talent_ids) != 1:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "案件提案プレビューは同一人材のマッチのみ指定できます。"},
        )

    already = _already_sent_match_ids(session, ids)
    pending = [m for m in ordered if m.id not in already]
    if not pending:
        first = ordered[0]
        talent = session.get(Talent, first.talent_id)
        project = session.get(Project, first.project_id)
        source_email = session.get(Email, talent.email_id) if talent else None
        return TalentProposePreviewResponse(
            drafts=[
                TalentProposeDraft(
                    match_ids=[str(m.id) for m in ordered],
                    match_id=str(first.id),
                    project_ids=[str(m.project_id) for m in ordered],
                    project_id=str(first.project_id),
                    project_titles=[(session.get(Project, m.project_id).title if session.get(Project, m.project_id) else None) or "" for m in ordered],
                    project_title=project.title if project else None,
                    to_address=source_email.from_address if source_email else None,
                    cc_addresses=_proposal_cc_list(talent),
                    subject=_reply_subject(source_email.subject if source_email else None, project.title if project else None),
                    body_text="",
                    already_sent=True,
                )
            ]
        )

    talent = session.get(Talent, pending[0].talent_id)
    if talent is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "人材が見つかりません。"},
        )
    source_email = session.get(Email, talent.email_id)
    project_lines: list[TalentProposalProjectLine] = []
    project_ids: list[str] = []
    project_titles: list[str] = []
    for match in pending:
        project = session.get(Project, match.project_id)
        if project is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "ERR-0012", "error_message": "案件が見つかりません。"},
            )
        project_ids.append(str(project.id))
        project_titles.append(project.title or "")
        project_lines.append(
            TalentProposalProjectLine(
                title=project.title,
                required_skills=project.required_skills if isinstance(project.required_skills, list) else [],
                rate_min=project.rate_min,
                rate_max=project.rate_max,
                work_style=project.work_style,
                start_date=project.start_date,
                score=match.score,
                recommendation_points=resolve_recommendation_points(
                    stored=match.recommendation_points,
                    display_name=talent.display_name,
                    skills=talent.skills if isinstance(talent.skills, list) else [],
                    reason=match.reason,
                ),
                foreign_nationality_ng=project.foreign_nationality_ng,
                commerce_flow_limit=project.commerce_flow_limit,
                working_hours=project.working_hours,
                settlement_range=project.settlement_range,
                interview_count=project.interview_count,
                summary=project.summary,
            )
        )

    company_name, contact_name = resolve_source_party(
        session,
        source_email,
        company_name_fallback=talent.source_company_name,
    )
    settings_map = load_settings(session)
    body_text = build_talent_proposal_body_multi(
        talent_display_name=talent.display_name,
        projects=project_lines,
        template=str(settings_map.get(SETTING_KEY_TEMPLATE_PROJECT_PROPOSE) or ""),
        company_name=company_name,
        contact_name=contact_name,
        rate_markdown_man_yen=parse_talent_propose_rate_markup(
            settings_map.get(SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP)
        ),
    )
    first_project_title = project_titles[0] if project_titles else None
    combined_title = " / ".join(t for t in project_titles if t) or first_project_title
    return TalentProposePreviewResponse(
        drafts=[
            TalentProposeDraft(
                match_ids=[str(m.id) for m in pending],
                match_id=str(pending[0].id),
                project_ids=project_ids,
                project_id=project_ids[0],
                project_titles=project_titles,
                project_title=combined_title,
                to_address=source_email.from_address if source_email else None,
                cc_addresses=_proposal_cc_list(talent),
                subject=_reply_subject(source_email.subject if source_email else None, first_project_title),
                body_text=body_text,
                already_sent=False,
            )
        ]
    )


@router.post("/talent-propose", response_model=OutreachActionResponse)
def talent_propose(body: TalentProposeRequest) -> OutreachActionResponse:
    if not body.match_ids:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "match_ids が空です。"},
        )
    ids = [_parse_uuid(mid, "match_id") for mid in body.match_ids]
    extra_env: dict[str, str] = {
        "OUTREACH_MATCH_IDS": ",".join(str(i) for i in ids),
    }
    to_address = (body.to_address or "").strip() or None
    cc_addresses = body.cc_addresses
    body_text = ""
    if body.drafts:
        # 1通まとめ: 最初の非空本文を採用
        for draft in body.drafts:
            text = draft.body_text.strip()
            if text:
                body_text = draft.body_text
                if draft.to_address and draft.to_address.strip():
                    to_address = draft.to_address.strip()
                if draft.cc_addresses is not None:
                    cc_addresses = draft.cc_addresses
                break
        if not body_text.strip():
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "本文が空です。"},
            )
    payload: dict[str, object] = {}
    if body_text.strip():
        payload["body"] = body_text
        extra_env["OUTREACH_BODY_TEXT"] = body_text
    if to_address:
        payload["to_address"] = to_address
        extra_env["OUTREACH_TO_ADDRESS"] = to_address
    if cc_addresses is not None:
        cleaned_cc = [str(addr).strip() for addr in cc_addresses if str(addr).strip()]
        payload["cc_addresses"] = cleaned_cc
        extra_env["OUTREACH_CC_ADDRESSES"] = ",".join(cleaned_cc)
    if payload:
        extra_env["OUTREACH_BODIES_JSON"] = json.dumps(payload, ensure_ascii=False)

    try:
        result = run_batch_job("talent_propose", extra_env=extra_env)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "ERR-0030", "error_message": str(exc)},
        ) from exc
    except BatchRunTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={"error_code": "ERR-0029", "error_message": "外部サービスへの接続がタイムアウトしました。"},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "error_code": "ERR-0030",
                "error_message": f"要員提案の送信中にエラーが発生しました: {exc}",
            },
        ) from exc
    if result.exit_code != 0:
        _raise_batch_error(fallback_message="案件提案の送信に失敗しました。")
    return OutreachActionResponse(status="ok", message="案件提案を送信しました", sent=1)


@router.post("/project-propose/preview", response_model=ProjectProposePreviewResponse)
def project_propose_preview(
    body: ProjectProposePreviewRequest,
    session: Session = Depends(get_db),
) -> ProjectProposePreviewResponse:
    """案件配信元への人材提案メール下書きを返す。"""
    if not body.match_ids:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "match_ids が空です。"},
        )
    project_id = _parse_uuid(body.project_id, "project_id")
    ids = [_parse_uuid(mid, "match_id") for mid in body.match_ids]
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "案件が見つかりません。"},
        )

    matches = list(session.scalars(select(Match).where(Match.id.in_(ids))).all())
    by_id = {m.id: m for m in matches}
    missing = [str(i) for i in ids if i not in by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象のマッチが見つかりません。"},
        )
    ordered = [by_id[i] for i in ids]
    for match in ordered:
        if match.project_id != project_id:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "選択したマッチが対象案件と一致しません。"},
            )

    already_talent_ids = set(
        session.scalars(
            select(OutreachMessageTalent.talent_id)
            .join(OutreachMessage, OutreachMessage.id == OutreachMessageTalent.outreach_message_id)
            .where(
                OutreachMessage.kind == "project_proposal",
                OutreachMessage.status == "sent",
                OutreachMessage.project_id == project_id,
            )
        ).all()
    )
    pending = [m for m in ordered if m.talent_id not in already_talent_ids]
    source_email = session.get(Email, project.email_id)
    subject = _reply_subject(source_email.subject if source_email else None, project.title)
    to_address = source_email.from_address if source_email else None
    cc_addresses = _proposal_cc_list(project)

    if not pending:
        return ProjectProposePreviewResponse(
            draft=ProjectProposeDraft(
                project_id=str(project_id),
                match_ids=[str(m.id) for m in ordered],
                talent_ids=[str(m.talent_id) for m in ordered],
                talent_names=[],
                to_address=to_address,
                cc_addresses=cc_addresses,
                subject=subject,
                body_text="",
                already_sent=True,
            )
        )

    pending_pairs: list[tuple[Talent, Match]] = []
    talent_ids: list[str] = []
    talent_names: list[str] = []
    for match in pending:
        talent = session.get(Talent, match.talent_id)
        if talent is None:
            raise HTTPException(
                status_code=404,
                detail={"error_code": "ERR-0012", "error_message": "人材が見つかりません。"},
            )
        pending_pairs.append((talent, match))
        talent_ids.append(str(talent.id))
        talent_names.append(talent.display_name or "")

    settings_map = load_settings(session)
    own_company = str(settings_map.get(SETTING_KEY_OWN_COMPANY_NAME) or "").strip() or None
    talent_lines = [
        TalentProposeLine(
            display_name=talent.display_name,
            skills=talent.skills if isinstance(talent.skills, list) else [],
            desired_rate=talent.desired_rate,
            available_from=talent.available_from,
            score=match.score,
            ai_score=match.ai_score,
            recommendation_points=resolve_recommendation_points(
                stored=match.recommendation_points,
                display_name=talent.display_name,
                skills=talent.skills if isinstance(talent.skills, list) else [],
                reason=match.reason,
            ),
            is_foreign_national=talent.is_foreign_national,
            commerce_flow=resolve_proposal_commerce_flow(
                own_company_name=own_company,
                talent_company_name=_talent_company_name(session, talent),
                affiliation=talent.affiliation,
                commerce_flow=talent.commerce_flow,
            )
            or None,
        )
        for talent, match in pending_pairs
    ]

    company_fallback = None
    if project.distributor_company_id:
        company = session.get(Company, project.distributor_company_id)
        if company:
            company_fallback = company.name
    company_name, contact_name = resolve_source_party(
        session,
        source_email,
        company_name_fallback=company_fallback,
    )
    body_text = render_talent_propose_body(
        template=str(settings_map.get(SETTING_KEY_TEMPLATE_TALENT_PROPOSE) or ""),
        project_title=project.title,
        talents=talent_lines,
        company_name=company_name,
        contact_name=contact_name,
    )
    attachments, total_bytes, over_limit, attachments_note = _build_project_propose_attachments(
        session, pending_pairs
    )
    return ProjectProposePreviewResponse(
        draft=ProjectProposeDraft(
            project_id=str(project_id),
            match_ids=[str(m.id) for m in pending],
            talent_ids=talent_ids,
            talent_names=talent_names,
            to_address=to_address,
            cc_addresses=cc_addresses,
            subject=subject,
            body_text=body_text,
            already_sent=False,
            attachments=attachments,
            attachments_total_bytes=total_bytes,
            attachments_over_size_limit=over_limit,
            attachments_note=attachments_note,
        )
    )


@router.post("/project-propose", response_model=OutreachActionResponse)
def project_propose(body: ProjectProposeRequest) -> OutreachActionResponse:
    project_id = _parse_uuid(body.project_id, "project_id")
    match_ids = [_parse_uuid(mid, "match_id") for mid in body.match_ids]
    if not match_ids:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "match_ids が空です。"},
        )
    extra_env: dict[str, str] = {
        "OUTREACH_PROJECT_ID": str(project_id),
        "OUTREACH_MATCH_IDS": ",".join(str(i) for i in match_ids),
    }
    payload: dict[str, object] = {}
    if body.body_text is not None:
        text = body.body_text.strip()
        if not text:
            raise HTTPException(
                status_code=400,
                detail={"error_code": "ERR-0001", "error_message": "本文が空です。"},
            )
        payload["body"] = body.body_text
        extra_env["OUTREACH_BODY_TEXT"] = body.body_text
    to_address = (body.to_address or "").strip() or None
    if to_address:
        payload["to_address"] = to_address
        extra_env["OUTREACH_TO_ADDRESS"] = to_address
    if body.cc_addresses is not None:
        cleaned_cc = [str(addr).strip() for addr in body.cc_addresses if str(addr).strip()]
        payload["cc_addresses"] = cleaned_cc
        extra_env["OUTREACH_CC_ADDRESSES"] = ",".join(cleaned_cc)
    if payload:
        extra_env["OUTREACH_BODIES_JSON"] = json.dumps(payload, ensure_ascii=False)

    try:
        result = run_batch_job(
            "project_propose",
            extra_env=extra_env,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "ERR-0030", "error_message": str(exc)},
        ) from exc
    except BatchRunTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={"error_code": "ERR-0029", "error_message": "外部サービスへの接続がタイムアウトしました。"},
        ) from exc
    if result.exit_code != 0:
        _raise_batch_error(fallback_message="人材提案の送信に失敗しました。")
    return OutreachActionResponse(status="ok", message="人材提案を送信しました", sent=1)


@router.patch("/matches/{match_id}/status", response_model=MatchStatusUpdateResponse)
def update_match_outreach_status(
    match_id: str,
    body: MatchStatusUpdateRequest,
    session: Session = Depends(get_db),
) -> MatchStatusUpdateResponse:
    """提案済みマッチの返信ステータス（承諾/見送り/不明）を手動更新する。"""
    mid = _parse_uuid(match_id, "match_id")
    match = session.get(Match, mid)
    if match is None:
        raise HTTPException(
            status_code=404,
            detail={"error_code": "ERR-0012", "error_message": "対象データが見つかりません。"},
        )

    if body.kind == "project_proposal":
        proposal = latest_project_proposal(
            session,
            project_id=match.project_id,
            talent_id=match.talent_id,
        )
        kind_label = "人材提案"
    else:
        proposal = latest_talent_proposal(session, match.id)
        kind_label = "案件提案"

    if proposal is None:
        raise HTTPException(
            status_code=400,
            detail={
                "error_code": "ERR-0001",
                "error_message": f"{kind_label}送信前のマッチはステータスを変更できません。",
            },
        )

    reply = latest_reply_for_proposal(session, proposal.id)
    now = datetime.now().astimezone()
    if reply is None:
        reply = OutreachReply(
            id=uuid.uuid4(),
            outreach_message_id=proposal.id,
            gmail_message_id=f"manual:{uuid.uuid4()}",
            thread_id=proposal.thread_id,
            received_at=now,
            body_text="（手動でステータスを設定）",
            judgment=body.judgment,
            judgment_source="manual",
            labeled_at=None,
            created_at=now,
        )
        session.add(reply)
    else:
        reply.judgment = body.judgment
        reply.judgment_source = "manual"

    session.commit()
    session.refresh(reply)

    talent_side = talent_proposal_side_status(session, match_id=match.id)
    project_side = project_proposal_side_status(
        session,
        project_id=match.project_id,
        talent_id=match.talent_id,
    )
    status = compute_outreach_status(
        session,
        match_id=match.id,
        project_id=match.project_id,
        talent_id=match.talent_id,
    )
    return MatchStatusUpdateResponse(
        match_id=str(match.id),
        kind=body.kind,
        judgment=reply.judgment,
        judgment_source=reply.judgment_source,
        reply_id=str(reply.id),
        reply_body=reply.body_text,
        reply_received_at=reply.received_at.isoformat() if reply.received_at else None,
        outreach_status=status,
        talent_proposal_status=talent_side.status,
        project_proposal_status=project_side.status,
    )


@router.post("/reply-sync", response_model=OutreachActionResponse)
def trigger_reply_sync(
    kind: Literal["talent_proposal", "project_proposal", "all"] = Query(
        "all",
        description="talent_proposal=案件提案メールへの返信 / project_proposal=人材提案メールへの返信 / all=両方",
    ),
) -> OutreachActionResponse:
    try:
        result = run_batch_job("reply_sync", extra_env={"REPLY_SYNC_KIND": kind})
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail={"error_code": "ERR-0030", "error_message": str(exc)},
        ) from exc
    except BatchRunTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={"error_code": "ERR-0029", "error_message": "外部サービスへの接続がタイムアウトしました。"},
        ) from exc
    if result.exit_code != 0:
        _raise_batch_error(fallback_message="返信同期に失敗しました。")
    label = {
        "talent_proposal": "案件提案メールの返信同期が完了しました",
        "project_proposal": "人材提案メールの返信同期が完了しました",
        "all": "返信同期が完了しました",
    }.get(kind, "返信同期が完了しました")
    return OutreachActionResponse(status="ok", message=label)
