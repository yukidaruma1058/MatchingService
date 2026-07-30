"""BAT-009: 案件配信メールへ選択要員をまとめて返信提案する（手動のみ）。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.constraint_rules import resolve_proposal_commerce_flow
from app.db_bootstrap import create_session_factory, ensure_schema
from app.email_db import load_all_settings
from app.gmail_client import GmailClient, GmailConfigError
from app.gmail_credentials import ensure_gmail_credentials_file
from app.label_settings import load_sort_settings, move_to_reply_label
from app.logging_util import get_batch_logger, log_error_event, log_event
from app.models import (
    Company,
    Email,
    Match,
    OutreachMessage,
    OutreachMessageTalent,
    Project,
    Talent,
)
from app.outreach_party import resolve_source_party
from app.outreach_templates import (
    DEFAULT_TALENT_PROPOSE_TEMPLATE,
    SETTING_KEY_TEMPLATE_TALENT_PROPOSE,
    TalentProposeLine,
    render_talent_propose_body,
)
from app.drive_client import DriveClient
from app.skill_sheet_propose import prepare_proposal_attachments
from app.talent_recommendation import resolve_recommendation_points

SETTING_KEY_OWN_COMPANY_NAME = "own_company_name"


@dataclass
class ProjectProposeStats:
    sent: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)
    outreach_message_id: str | None = None


def _talent_company_name(session: Session, talent: Talent) -> str | None:
    if talent.introducer_company_id:
        company = session.get(Company, talent.introducer_company_id)
        if company and (company.name or "").strip():
            return company.name.strip()
    name = (talent.source_company_name or "").strip()
    return name or None


def _already_proposed_talent_ids(session: Session, project_id: UUID) -> set[UUID]:
    rows = session.execute(
        select(OutreachMessageTalent.talent_id)
        .join(OutreachMessage, OutreachMessage.id == OutreachMessageTalent.outreach_message_id)
        .where(
            OutreachMessage.kind == "project_proposal",
            OutreachMessage.status == "sent",
            OutreachMessage.project_id == project_id,
        )
    ).all()
    return {row[0] for row in rows}


def _build_body(
    session: Session,
    *,
    project: Project,
    source_email: Email | None,
    talents: list[tuple[Talent, Match]],
    template: str | None = None,
    own_company_name: str | None = None,
    cfg: Settings | None = None,
) -> str:
    _ = cfg  # 呼び出し互換のため残す（おすすめポイントは採点済みを利用）
    lines = [
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
                own_company_name=own_company_name,
                talent_company_name=_talent_company_name(session, talent),
                affiliation=talent.affiliation,
                commerce_flow=talent.commerce_flow,
            )
            or None,
        )
        for talent, match in talents
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
    return render_talent_propose_body(
        template=template or DEFAULT_TALENT_PROPOSE_TEMPLATE,
        project_title=project.title,
        talents=lines,
        company_name=company_name,
        contact_name=contact_name,
    )


def run_project_propose_batch(
    *,
    project_id: UUID,
    match_ids: list[UUID],
    body_text: str | None = None,
    to_address: str | None = None,
    cc_addresses: list[str] | None = None,
    cfg: Settings | None = None,
) -> ProjectProposeStats:
    cfg = cfg or settings
    logger = get_batch_logger()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    stats = ProjectProposeStats()

    if not match_ids:
        stats.failed = 1
        stats.errors.append("match_ids is empty")
        return stats

    session_factory, engine = create_session_factory(cfg.database_url)
    ensure_schema(engine)
    ensure_gmail_credentials_file()

    with session_factory() as session:
        project = session.get(Project, project_id)
        if project is None:
            stats.failed = 1
            stats.errors.append("project not found")
            return stats

        matches = list(session.scalars(select(Match).where(Match.id.in_(match_ids))).all())
        if len(matches) != len(set(match_ids)):
            stats.failed = 1
            stats.errors.append("some match_ids were not found")
            return stats

        for match in matches:
            if match.project_id != project_id:
                stats.failed = 1
                stats.errors.append("all matches must belong to the same project")
                return stats

        # 画面から明示選択された match_ids は返信 OK 条件をスキップする
        already = _already_proposed_talent_ids(session, project_id)
        selected: list[tuple[Talent, Match]] = []
        for match in matches:
            if match.talent_id in already:
                continue
            talent = session.get(Talent, match.talent_id)
            if talent is None:
                stats.failed = 1
                stats.errors.append(f"talent missing: {match.talent_id}")
                return stats
            selected.append((talent, match))

        if not selected:
            stats.failed = 1
            stats.errors.append("selected talents were already proposed")
            return stats

        source_email = session.get(Email, project.email_id)
        if source_email is None or not source_email.thread_id or not source_email.gmail_message_id:
            stats.failed = 1
            stats.errors.append("project source email thread is missing")
            return stats

        override_body = (body_text or "").strip() or None
        if override_body:
            body = body_text or ""
        else:
            settings_map = load_all_settings(session)
            talent_template = str(settings_map.get(SETTING_KEY_TEMPLATE_TALENT_PROPOSE) or "").strip() or None
            own_company = str(settings_map.get(SETTING_KEY_OWN_COMPANY_NAME) or "").strip() or None
            body = _build_body(
                session,
                project=project,
                source_email=source_email,
                talents=selected,
                template=talent_template,
                own_company_name=own_company,
                cfg=cfg,
            )
        subject = source_email.subject or project.title

        try:
            client = GmailClient(cfg.gmail_credentials_path, cfg.gmail_token_path)
            client.connect()
            rfc_id = client.get_rfc822_message_id(source_email.gmail_message_id)
            to_resolved = (to_address or "").strip() or client.resolve_reply_recipient(
                source_email.gmail_message_id,
                fallback=source_email.from_address,
            )
            # 動作確認用: 連携 Gmail 自身への送信ガードを一時無効化（後で戻す）
            # me = client.get_authenticated_email()
            # if me and to_resolved.lower() == me.lower():
            #     raise GmailConfigError(
            #         "ERR-0022",
            #         f"返信先が連携 Gmail 自身（{me}）のため送信を中止しました。元メールの From/Reply-To を確認してください。",
            #     )
            apply_from = str(load_all_settings(session).get("apply_from_address") or "").strip() or None
            if cc_addresses is None:
                cc_resolved = (
                    list(project.proposal_cc_emails or [])
                    if isinstance(project.proposal_cc_emails, list)
                    else []
                )
            else:
                cc_resolved = [str(addr).strip() for addr in cc_addresses if str(addr).strip()]
            attachments_payload: list[dict] = []
            try:
                drive = DriveClient(cfg.gmail_credentials_path, cfg.gmail_token_path)
                drive.connect()
                prepared, link_lines = prepare_proposal_attachments(
                    session,
                    talent_ids=[t.id for t, _ in selected],
                    drive=drive,
                )
                if link_lines:
                    body = (body or "").rstrip() + "\n" + "\n".join(link_lines) + "\n"
                attachments_payload = [
                    {
                        "filename": item.filename,
                        "content_type": item.content_type,
                        "data": item.data,
                    }
                    for item in prepared
                ]
            except GmailConfigError as drive_exc:
                log_error_event(
                    logger,
                    event="outreach.project_propose.skill_sheet_skipped",
                    error_code=drive_exc.error_code,
                    detail=drive_exc.message,
                    operation="スキルシート添付準備",
                    method_name="run_project_propose_batch",
                    job_id=job_id,
                    function_id="BAT-009",
                    module_name="BAT-009.project_propose",
                )
            sent_id = client.send_reply(
                to_address=to_resolved,
                subject=subject,
                body_text=body,
                thread_id=source_email.thread_id,
                from_address=apply_from,
                in_reply_to_message_id=rfc_id,
                references=rfc_id,
                cc_addresses=cc_resolved,
                attachments=attachments_payload or None,
            )
            try:
                sort_settings = load_sort_settings(session, cfg)
                move_to_reply_label(
                    client,
                    message_ids=[source_email.gmail_message_id, sent_id],
                    base_label=sort_settings.project_label,
                )
            except Exception as label_exc:  # noqa: BLE001
                log_error_event(
                    logger,
                    event="outreach.project_propose.label_failed",
                    error_code=getattr(label_exc, "error_code", "ERR-0021"),
                    detail=str(label_exc),
                    operation="返信用ラベル貼替",
                    method_name="run_project_propose_batch",
                    job_id=job_id,
                    function_id="BAT-009",
                    module_name="BAT-009.project_propose",
                )
        except Exception as exc:  # noqa: BLE001
            stats.failed = 1
            stats.errors.append(str(exc))
            log_error_event(
                logger,
                event="outreach.project_propose.failed",
                error_code=getattr(exc, "error_code", "ERR-0022"),
                detail=str(exc),
                operation="案件提案送信",
                method_name="run_project_propose_batch",
                job_id=job_id,
                function_id="BAT-009",
                module_name="BAT-009.project_propose",
            )
            return stats

        now = datetime.now().astimezone()
        outreach = OutreachMessage(
            id=uuid.uuid4(),
            kind="project_proposal",
            match_id=None,
            talent_id=None,
            project_id=project_id,
            status="sent",
            gmail_message_id=sent_id,
            thread_id=source_email.thread_id,
            in_reply_to_email_id=source_email.id,
            subject=f"Re: {subject}" if not subject.lower().startswith("re:") else subject,
            body_text=body,
            sent_at=now,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        session.add(outreach)
        session.flush()
        for talent, match in selected:
            session.add(
                OutreachMessageTalent(
                    outreach_message_id=outreach.id,
                    talent_id=talent.id,
                    match_id=match.id,
                )
            )
        session.commit()
        stats.sent = 1
        stats.outreach_message_id = str(outreach.id)

    log_event(
        logger,
        logging.INFO,
        event="outreach.project_propose.finished",
        message="Project propose batch finished",
        operation="案件提案送信完了",
        method_name="run_project_propose_batch",
        job_id=job_id,
        function_id="BAT-009",
        module_name="BAT-009.project_propose",
        extra={"sent": stats.sent, "talents": len(match_ids)},
    )
    return stats
