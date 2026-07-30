"""BAT-007: 要員紹介メールへ案件提案を返信送信する（同一人材の複数案件は1通にまとめる）。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.email_db import load_all_settings
from app.gmail_client import GmailClient, GmailConfigError
from app.gmail_credentials import ensure_gmail_credentials_file
from app.label_settings import load_sort_settings, move_to_reply_label
from app.logging_util import get_batch_logger, log_error_event, log_event
from app.models import Email, Match, OutreachMessage, Project, Talent
from app.outreach_party import resolve_source_party
from app.outreach_templates import (
    DEFAULT_PROJECT_PROPOSE_TEMPLATE,
    ProjectProposeLine,
    SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP,
    SETTING_KEY_TEMPLATE_PROJECT_PROPOSE,
    parse_talent_propose_rate_markup,
    render_project_propose_body,
)
from app.talent_recommendation import resolve_recommendation_points


@dataclass
class TalentProposeStats:
    scanned: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


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


def _build_body(
    session: Session,
    *,
    talent: Talent,
    source_email: Email | None,
    items: list[tuple[Project, Match]],
    template: str | None = None,
    rate_markdown_man_yen: int = 0,
) -> str:
    projects = [
        ProjectProposeLine(
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
        for project, match in items
    ]
    company_name, contact_name = resolve_source_party(
        session,
        source_email,
        company_name_fallback=talent.source_company_name,
    )
    return render_project_propose_body(
        template=template or DEFAULT_PROJECT_PROPOSE_TEMPLATE,
        company_name=company_name,
        contact_name=contact_name,
        projects=projects,
        rate_markdown_man_yen=rate_markdown_man_yen,
    )


def _send_combined(
    session: Session,
    client: GmailClient,
    *,
    talent: Talent,
    source_email: Email,
    items: list[tuple[Match, Project]],
    body_text: str,
    cfg: Settings | None = None,
    to_address: str | None = None,
    cc_addresses: list[str] | None = None,
) -> str:
    if not source_email.thread_id or not source_email.gmail_message_id:
        raise GmailConfigError("ERR-0022", "人材紹介メールの thread_id / gmail_message_id がありません")

    first_project = items[0][1]
    subject = source_email.subject or first_project.title or "案件のご提案"
    rfc_id = client.get_rfc822_message_id(source_email.gmail_message_id)
    resolved_to = (to_address or "").strip() or client.resolve_reply_recipient(
        source_email.gmail_message_id,
        fallback=source_email.from_address,
    )
    if cc_addresses is None:
        resolved_cc = (
            list(talent.proposal_cc_emails or []) if isinstance(talent.proposal_cc_emails, list) else []
        )
    else:
        resolved_cc = [str(addr).strip() for addr in cc_addresses if str(addr).strip()]
    # 動作確認用: 連携 Gmail 自身への送信ガードを一時無効化（後で戻す）
    # me = client.get_authenticated_email()
    # if me and resolved_to.lower() == me.lower():
    #     raise GmailConfigError(
    #         "ERR-0022",
    #         f"返信先が連携 Gmail 自身（{me}）のため送信を中止しました。元メールの From/Reply-To を確認してください。",
    #     )
    apply_from = str(load_all_settings(session).get("apply_from_address") or "").strip() or None
    sent_id = client.send_reply(
        to_address=resolved_to,
        subject=subject,
        body_text=body_text,
        thread_id=source_email.thread_id,
        from_address=apply_from,
        in_reply_to_message_id=rfc_id,
        references=rfc_id,
        cc_addresses=resolved_cc,
    )
    try:
        sort_settings = load_sort_settings(session, cfg or settings)
        move_to_reply_label(
            client,
            message_ids=[source_email.gmail_message_id, sent_id],
            base_label=sort_settings.talent_label,
        )
    except Exception as exc:  # noqa: BLE001
        log_error_event(
            get_batch_logger(),
            event="outreach.talent_propose.label_failed",
            error_code=getattr(exc, "error_code", "ERR-0021"),
            detail=str(exc),
            operation="返信用ラベル貼替",
            method_name="_send_combined",
            job_id="unknown",
            function_id="BAT-007",
            module_name="BAT-007.talent_propose",
        )
    now = datetime.now().astimezone()
    reply_subject = f"Re: {subject}" if not subject.lower().startswith("re:") else subject
    for match, project in items:
        session.add(
            OutreachMessage(
                id=uuid.uuid4(),
                kind="talent_proposal",
                match_id=match.id,
                talent_id=talent.id,
                project_id=project.id,
                status="sent",
                gmail_message_id=sent_id,
                thread_id=source_email.thread_id,
                in_reply_to_email_id=source_email.id,
                subject=reply_subject,
                body_text=body_text,
                sent_at=now,
                error_message=None,
                created_at=now,
                updated_at=now,
            )
        )
    session.flush()
    return sent_id


def run_talent_propose_batch(
    *,
    match_ids: list[UUID],
    body_text: str | None = None,
    body_by_match_id: dict[UUID, str] | None = None,
    to_address: str | None = None,
    cc_addresses: list[str] | None = None,
    cfg: Settings | None = None,
) -> TalentProposeStats:
    """要員側への案件提案を送信する（手動・match_ids 必須）。同一人材は1通にまとめる。"""
    cfg = cfg or settings
    logger = get_batch_logger()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    stats = TalentProposeStats()
    # 旧形式（matchごと本文）は先頭の本文をまとめて1通に使う
    legacy_bodies = body_by_match_id or {}
    combined_body = (body_text or "").strip() or None
    if combined_body is None and legacy_bodies:
        # 複数キーがある場合も、同じ編集本文想定で最初の非空を採用
        for value in legacy_bodies.values():
            text = (value or "").strip()
            if text:
                combined_body = text
                break

    log_event(
        logger,
        logging.INFO,
        event="outreach.talent_propose.started",
        message="Talent propose batch started",
        operation="要員提案送信開始",
        method_name="run_talent_propose_batch",
        job_id=job_id,
        function_id="BAT-007",
        module_name="BAT-007.talent_propose",
    )

    if not match_ids:
        stats.failed = 1
        stats.errors.append("match_ids is empty")
        return stats

    session_factory, engine = create_session_factory(cfg.database_url)
    ensure_schema(engine)
    ensure_gmail_credentials_file()

    with session_factory() as session:
        settings_map = load_all_settings(session)
        project_template = str(settings_map.get(SETTING_KEY_TEMPLATE_PROJECT_PROPOSE) or "").strip() or None
        rate_markdown = parse_talent_propose_rate_markup(
            settings_map.get(SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP)
        )
        matches = list(session.scalars(select(Match).where(Match.id.in_(match_ids))).all())
        stats.scanned = len(matches)
        already = _already_sent_match_ids(session, [m.id for m in matches])
        targets = [m for m in matches if m.id not in already]
        stats.skipped = len(matches) - len(targets)

        if not targets:
            session.commit()
            return stats

        # 人材ごとにまとめる（人材詳細は常に1人材、マッチング画面は複数人材になり得る）
        by_talent: dict[UUID, list[Match]] = {}
        for match in targets:
            by_talent.setdefault(match.talent_id, []).append(match)

        client = GmailClient(cfg.gmail_credentials_path, cfg.gmail_token_path)
        client.connect()

        for talent_id, talent_matches in by_talent.items():
            talent = session.get(Talent, talent_id)
            if talent is None:
                stats.failed += 1
                stats.errors.append(f"talent missing: {talent_id}")
                continue
            source_email = session.get(Email, talent.email_id)
            if source_email is None:
                stats.failed += 1
                stats.errors.append(f"email missing for talent {talent.id}")
                continue

            items: list[tuple[Match, Project]] = []
            project_pairs: list[tuple[Project, Match]] = []
            ok = True
            for match in talent_matches:
                project = session.get(Project, match.project_id)
                if project is None:
                    stats.failed += 1
                    stats.errors.append(f"project missing for match {match.id}")
                    ok = False
                    break
                items.append((match, project))
                project_pairs.append((project, match))
            if not ok or not items:
                continue

            body = (
                combined_body
                if combined_body is not None
                else _build_body(
                    session,
                    talent=talent,
                    source_email=source_email,
                    items=project_pairs,
                    template=project_template,
                    rate_markdown_man_yen=rate_markdown,
                )
            )
            try:
                _send_combined(
                    session,
                    client,
                    talent=talent,
                    source_email=source_email,
                    items=items,
                    body_text=body,
                    cfg=cfg,
                    to_address=to_address,
                    cc_addresses=cc_addresses,
                )
                session.commit()
                stats.sent += 1
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                stats.failed += 1
                stats.errors.append(str(exc))
                log_error_event(
                    logger,
                    event="outreach.talent_propose.failed",
                    error_code=getattr(exc, "error_code", "ERR-0022"),
                    detail=str(exc),
                    operation="要員提案送信",
                    method_name="run_talent_propose_batch",
                    job_id=job_id,
                    function_id="BAT-007",
                    module_name="BAT-007.talent_propose",
                )

    log_event(
        logger,
        logging.INFO,
        event="outreach.talent_propose.finished",
        message="Talent propose batch finished",
        operation="要員提案送信完了",
        method_name="run_talent_propose_batch",
        job_id=job_id,
        function_id="BAT-007",
        module_name="BAT-007.talent_propose",
        extra={"sent": stats.sent, "skipped": stats.skipped, "failed": stats.failed},
    )
    return stats
