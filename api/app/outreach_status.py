"""マッチの outreach 進行ステータスを算出する。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Email, OutreachMessage, OutreachMessageTalent, OutreachReply


def latest_talent_proposal(session: Session, match_id: UUID) -> OutreachMessage | None:
    """人材紹介メールへの案件提案（talent_proposal）。"""
    return session.scalar(
        select(OutreachMessage)
        .where(
            OutreachMessage.kind == "talent_proposal",
            OutreachMessage.match_id == match_id,
            OutreachMessage.status == "sent",
        )
        .order_by(OutreachMessage.sent_at.desc())
        .limit(1)
    )


def _aware(value: datetime, *, fallback: datetime | None = None) -> datetime:
    if value.tzinfo is not None:
        return value
    ref = fallback if fallback is not None and fallback.tzinfo is not None else datetime.now().astimezone()
    return value.replace(tzinfo=ref.tzinfo)


def is_valid_outreach_reply(
    session: Session,
    proposal: OutreachMessage,
    reply: OutreachReply,
) -> bool:
    """スレッド内の元メールや提案送信前メールを「返信」と誤認しない。"""
    # 手動設定は常に有効
    if (reply.gmail_message_id or "").startswith("manual:"):
        return True
    if reply.judgment_source == "manual":
        return True

    if proposal.gmail_message_id and reply.gmail_message_id == proposal.gmail_message_id:
        return False

    if proposal.in_reply_to_email_id is not None:
        source = session.get(Email, proposal.in_reply_to_email_id)
        if source and source.gmail_message_id and reply.gmail_message_id == source.gmail_message_id:
            return False

    if proposal.sent_at is not None and reply.received_at is not None:
        sent_at = _aware(proposal.sent_at)
        received_at = _aware(reply.received_at, fallback=sent_at)
        if received_at <= sent_at:
            return False

    return True


def latest_reply_for_proposal(session: Session, proposal_id: UUID) -> OutreachReply | None:
    proposal = session.get(OutreachMessage, proposal_id)
    replies = list(
        session.scalars(
            select(OutreachReply)
            .where(OutreachReply.outreach_message_id == proposal_id)
            .order_by(OutreachReply.received_at.desc())
        ).all()
    )
    if proposal is None:
        return replies[0] if replies else None
    for reply in replies:
        if is_valid_outreach_reply(session, proposal, reply):
            return reply
    return None


def latest_project_proposal(
    session: Session,
    *,
    project_id: UUID,
    talent_id: UUID,
) -> OutreachMessage | None:
    """案件配信元への人材提案（project_proposal）。"""
    return session.scalar(
        select(OutreachMessage)
        .join(OutreachMessageTalent, OutreachMessageTalent.outreach_message_id == OutreachMessage.id)
        .where(
            OutreachMessage.kind == "project_proposal",
            OutreachMessage.status == "sent",
            OutreachMessage.project_id == project_id,
            OutreachMessageTalent.talent_id == talent_id,
        )
        .order_by(OutreachMessage.sent_at.desc())
        .limit(1)
    )


def has_project_proposal(session: Session, *, project_id: UUID, talent_id: UUID) -> bool:
    return latest_project_proposal(session, project_id=project_id, talent_id=talent_id) is not None


@dataclass(frozen=True)
class ProposalSideStatus:
    status: str = "none"
    reply_judgment: str | None = None
    reply_id: str | None = None
    reply_body: str | None = None
    reply_received_at: str | None = None


def _side_status_from_proposal(
    session: Session,
    proposal: OutreachMessage | None,
    *,
    sent_status: str,
) -> ProposalSideStatus:
    if proposal is None:
        return ProposalSideStatus()
    reply = latest_reply_for_proposal(session, proposal.id)
    if reply is not None and reply.judgment in {"ok", "ng", "unknown"}:
        return ProposalSideStatus(
            status=f"reply_{reply.judgment}",
            reply_judgment=reply.judgment,
            reply_id=str(reply.id),
            reply_body=reply.body_text,
            reply_received_at=reply.received_at.isoformat() if reply.received_at else None,
        )
    return ProposalSideStatus(status=sent_status)


def talent_proposal_side_status(session: Session, *, match_id: UUID) -> ProposalSideStatus:
    """案件提案結果（人材紹介メールへ案件を送った結果）。"""
    return _side_status_from_proposal(
        session,
        latest_talent_proposal(session, match_id),
        sent_status="talent_sent",
    )


def project_proposal_side_status(
    session: Session,
    *,
    project_id: UUID,
    talent_id: UUID,
) -> ProposalSideStatus:
    """人材提案結果（案件配信元へ人材を送った結果）。"""
    return _side_status_from_proposal(
        session,
        latest_project_proposal(session, project_id=project_id, talent_id=talent_id),
        sent_status="project_sent",
    )


def compute_outreach_status(session: Session, *, match_id: UUID, project_id: UUID, talent_id: UUID) -> str:
    """後方互換用の統合ステータス。人材提案があれば優先し、なければ案件提案を返す。"""
    project_side = project_proposal_side_status(session, project_id=project_id, talent_id=talent_id)
    if project_side.status != "none":
        return project_side.status
    return talent_proposal_side_status(session, match_id=match_id).status


def latest_active_proposal(
    session: Session,
    *,
    match_id: UUID,
    project_id: UUID,
    talent_id: UUID,
) -> OutreachMessage | None:
    """進行度の高い提案（案件側があれば優先、なければ人材側）を返す。"""
    project_proposal = latest_project_proposal(session, project_id=project_id, talent_id=talent_id)
    if project_proposal is not None:
        return project_proposal
    return latest_talent_proposal(session, match_id)


def latest_reply_for_match(
    session: Session,
    *,
    match_id: UUID,
    project_id: UUID,
    talent_id: UUID,
) -> OutreachReply | None:
    proposal = latest_active_proposal(
        session,
        match_id=match_id,
        project_id=project_id,
        talent_id=talent_id,
    )
    if proposal is None:
        return None
    return latest_reply_for_proposal(session, proposal.id)


def latest_reply_judgment(session: Session, match_id: UUID, *, project_id: UUID, talent_id: UUID) -> str | None:
    reply = latest_reply_for_match(
        session,
        match_id=match_id,
        project_id=project_id,
        talent_id=talent_id,
    )
    return reply.judgment if reply else None
