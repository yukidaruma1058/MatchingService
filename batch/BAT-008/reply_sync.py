"""BAT-008: 提案メールへの返信を同期し、ラベル付与と OK/NG 判定を行う。

対象 kind:
  - talent_proposal: 人材紹介メールへの案件提案（人材詳細から送信）
  - project_proposal: 案件配信メールへの人材提案（案件詳細から送信）

同一送信メールに複数案件/人材が含まれる場合、返信1通を各提案レコードへ紐づけ、
AI（Cursor → OpenAI、失敗時はキーワード）で候補ごとに OK/NG 判定する。
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.gmail_client import GmailClient, GmailMessage
from app.gmail_credentials import ensure_gmail_credentials_file
from app.logging_util import get_batch_logger, log_error_event, log_event
from app.models import (
    Email,
    OutreachMessage,
    OutreachMessageTalent,
    OutreachReply,
    Project,
    SystemSetting,
    Talent,
)
from app.reply_ai_judgment import ReplyJudgeItem, judge_replies_with_ai
from app.reply_judgment import parse_keywords, resolve_item_index_for_title

ProposalKind = Literal["talent_proposal", "project_proposal"]
ReplySyncKind = Literal["talent_proposal", "project_proposal", "all"]


@dataclass
class ReplySyncStats:
    threads: int = 0
    new_replies: int = 0
    labeled: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def _load_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(SystemSetting, key)
    if row is None:
        return default
    return row.value if row.value is not None else default


def _resolve_kind(kind: ReplySyncKind | None = None) -> ReplySyncKind:
    if kind in {"talent_proposal", "project_proposal", "all"}:
        return kind
    raw = os.environ.get("REPLY_SYNC_KIND", "all").strip().lower()
    if raw in {"talent_proposal", "project_proposal", "all"}:
        return raw  # type: ignore[return-value]
    return "all"


def _kinds_to_sync(kind: ReplySyncKind) -> list[ProposalKind]:
    if kind == "all":
        return ["talent_proposal", "project_proposal"]
    return [kind]


def _reply_label_for(session: Session, proposal_kind: ProposalKind) -> str:
    """返信ラベル = 人材用/案件用ラベル + 「返信」。"""
    from app.label_settings import load_sort_settings, reply_label_for
    from app.config import settings as app_settings

    sort_settings = load_sort_settings(session, app_settings)
    if proposal_kind == "project_proposal":
        return reply_label_for(sort_settings.project_label)
    return reply_label_for(sort_settings.talent_label)


def _item_title_for_proposal(session: Session, proposal: OutreachMessage) -> str | None:
    if proposal.kind == "talent_proposal" and proposal.project_id is not None:
        project = session.get(Project, proposal.project_id)
        return project.title if project else None
    if proposal.kind == "project_proposal":
        link = session.scalar(
            select(OutreachMessageTalent).where(
                OutreachMessageTalent.outreach_message_id == proposal.id
            )
        )
        if link is None:
            return None
        talent = session.get(Talent, link.talent_id)
        return talent.display_name if talent else None
    return None


def _item_index_for_proposal(session: Session, proposal: OutreachMessage) -> int | None:
    return resolve_item_index_for_title(
        proposal.body_text,
        _item_title_for_proposal(session, proposal),
    )


def _existing_reply_keys(session: Session) -> set[tuple[UUID, str]]:
    rows = session.execute(
        select(OutreachReply.outreach_message_id, OutreachReply.gmail_message_id)
    ).all()
    return {(row[0], row[1]) for row in rows}


def _source_gmail_ids(session: Session, group: list[OutreachMessage]) -> set[str]:
    """提案の返信元（案件配信/人材紹介の元メール）を除外するための ID 集合。"""
    ids: set[str] = set()
    for proposal in group:
        if proposal.in_reply_to_email_id is None:
            continue
        email = session.get(Email, proposal.in_reply_to_email_id)
        if email and email.gmail_message_id:
            ids.add(email.gmail_message_id)
    return ids


def _proposal_sent_at(proposal: OutreachMessage) -> datetime | None:
    if proposal.sent_at is None:
        return None
    sent = proposal.sent_at
    if sent.tzinfo is None:
        return sent.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return sent


def _is_message_after_proposal(msg: GmailMessage, proposal: OutreachMessage) -> bool:
    """提案送信より後のメールだけを返信候補とする（スレッド内の元メール誤検知を防ぐ）。"""
    sent_at = _proposal_sent_at(proposal)
    if sent_at is None:
        return True
    received = msg.received_at
    if received.tzinfo is None and sent_at.tzinfo is not None:
        received = received.replace(tzinfo=sent_at.tzinfo)
    return received > sent_at


def _is_valid_auto_reply(session: Session, proposal: OutreachMessage, reply: OutreachReply) -> bool:
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
    sent_at = _proposal_sent_at(proposal)
    if sent_at is not None and reply.received_at is not None:
        received = reply.received_at
        if received.tzinfo is None:
            received = received.replace(tzinfo=sent_at.tzinfo)
        if received <= sent_at:
            return False
    return True


def _purge_invalid_auto_replies(
    *,
    session: Session,
    proposals: list[OutreachMessage],
    known_keys: set[tuple[UUID, str]],
) -> int:
    """提案送信前・返信元メールを誤って取り込んだ auto 返信を削除する。"""
    if not proposals:
        return 0
    removed = 0
    rows = list(
        session.scalars(
            select(OutreachReply).where(
                OutreachReply.outreach_message_id.in_([p.id for p in proposals]),
                OutreachReply.judgment_source == "auto",
            )
        ).all()
    )
    proposal_by_id = {p.id: p for p in proposals}
    for row in rows:
        proposal = proposal_by_id.get(row.outreach_message_id)
        if proposal is None:
            continue
        if _is_valid_auto_reply(session, proposal, row):
            continue
        session.delete(row)
        known_keys.discard((row.outreach_message_id, row.gmail_message_id))
        removed += 1
    if removed:
        session.commit()
    return removed


def _delete_invalid_auto_replies(
    *,
    session: Session,
    group: list[OutreachMessage],
    message_id: str,
    known_keys: set[tuple[UUID, str]],
) -> int:
    """誤って取り込んだ auto 返信（元メールなど）を削除する。"""
    removed = 0
    rows = list(
        session.scalars(
            select(OutreachReply).where(
                OutreachReply.outreach_message_id.in_([p.id for p in group]),
                OutreachReply.gmail_message_id == message_id,
                OutreachReply.judgment_source == "auto",
            )
        ).all()
    )
    for row in rows:
        session.delete(row)
        known_keys.discard((row.outreach_message_id, row.gmail_message_id))
        removed += 1
    return removed


def _judge_items_for_group(
    session: Session,
    proposals: list[OutreachMessage],
    item_index_by_proposal: dict[UUID, int | None],
) -> list[ReplyJudgeItem]:
    items: list[ReplyJudgeItem] = []
    for proposal in proposals:
        title = _item_title_for_proposal(session, proposal) or "(無題)"
        items.append(
            ReplyJudgeItem(
                proposal_id=proposal.id,
                title=title,
                item_index=item_index_by_proposal.get(proposal.id),
            )
        )
    return items


def _sync_proposals(
    *,
    session: Session,
    client: GmailClient,
    proposal_kind: ProposalKind,
    reply_label: str,
    ok_keywords: list[str],
    ng_keywords: list[str],
    known_keys: set[tuple[UUID, str]],
    stats: ReplySyncStats,
    cfg: Settings,
) -> None:
    proposals = list(
        session.scalars(
            select(OutreachMessage).where(
                OutreachMessage.kind == proposal_kind,
                OutreachMessage.status == "sent",
                OutreachMessage.thread_id.is_not(None),
                OutreachMessage.gmail_message_id.is_not(None),
            )
        ).all()
    )
    if not proposals:
        return

    # 同一送信メール（gmail_message_id）にぶら下がる提案をまとめる
    by_sent_id: dict[str, list[OutreachMessage]] = defaultdict(list)
    for proposal in proposals:
        assert proposal.gmail_message_id
        by_sent_id[proposal.gmail_message_id].append(proposal)

    stats.threads += len(by_sent_id)
    _purge_invalid_auto_replies(session=session, proposals=proposals, known_keys=known_keys)

    try:
        client.ensure_label(reply_label)
    except Exception as exc:  # noqa: BLE001
        log_error_event(
            get_batch_logger(),
            event="outreach.reply_sync.label_failed",
            error_code=getattr(exc, "error_code", "ERR-0020"),
            detail=str(exc),
            operation="返信ラベル準備",
            method_name="run_reply_sync_batch",
            job_id="unknown",
            function_id="BAT-008",
            module_name="BAT-008.reply_sync",
            extra={"proposal_kind": proposal_kind, "reply_label": reply_label},
        )

    for sent_id, group in by_sent_id.items():
        thread_id = group[0].thread_id
        assert thread_id
        try:
            message_ids = client.list_thread_message_ids(thread_id)
        except Exception as exc:  # noqa: BLE001
            stats.failed += 1
            stats.errors.append(str(exc))
            continue

        source_ids = _source_gmail_ids(session, group)
        item_index_by_proposal = {
            proposal.id: _item_index_for_proposal(session, proposal) for proposal in group
        }

        for message_id in message_ids:
            if message_id == sent_id:
                continue

            # 返信元の案件配信/人材紹介メールは「返信」ではない
            if message_id in source_ids:
                removed = _delete_invalid_auto_replies(
                    session=session,
                    group=group,
                    message_id=message_id,
                    known_keys=known_keys,
                )
                if removed:
                    try:
                        session.commit()
                    except Exception as exc:  # noqa: BLE001
                        session.rollback()
                        stats.failed += 1
                        stats.errors.append(str(exc))
                continue

            missing = [p for p in group if (p.id, message_id) not in known_keys]
            existing_by_proposal = {
                row.outreach_message_id: row
                for row in session.scalars(
                    select(OutreachReply).where(
                        OutreachReply.outreach_message_id.in_([p.id for p in group]),
                        OutreachReply.gmail_message_id == message_id,
                    )
                ).all()
            }

            # 既存分は本文を再取得せず、提案前メールなら削除、それ以外は AI で auto 判定を直す
            if not missing:
                changed = False
                rejudge_proposals: list[OutreachMessage] = []
                body_for_ai: str | None = None
                for proposal in group:
                    existing = existing_by_proposal.get(proposal.id)
                    if existing is None or existing.judgment_source != "auto":
                        continue
                    sent_at = _proposal_sent_at(proposal)
                    received = existing.received_at
                    if sent_at is not None:
                        if received.tzinfo is None and sent_at.tzinfo is not None:
                            received = received.replace(tzinfo=sent_at.tzinfo)
                        if received <= sent_at:
                            session.delete(existing)
                            known_keys.discard((proposal.id, message_id))
                            changed = True
                            continue
                    rejudge_proposals.append(proposal)
                    if body_for_ai is None:
                        body_for_ai = existing.body_text
                if rejudge_proposals:
                    judgments = judge_replies_with_ai(
                        _judge_items_for_group(
                            session, rejudge_proposals, item_index_by_proposal
                        ),
                        body_for_ai,
                        cfg=cfg,
                        ok_keywords=ok_keywords,
                        ng_keywords=ng_keywords,
                    )
                    for proposal in rejudge_proposals:
                        existing = existing_by_proposal.get(proposal.id)
                        if existing is None:
                            continue
                        judgment = judgments.get(proposal.id, "unknown")
                        if existing.judgment != judgment:
                            existing.judgment = judgment
                            changed = True
                if changed:
                    try:
                        session.commit()
                    except Exception as exc:  # noqa: BLE001
                        session.rollback()
                        stats.failed += 1
                        stats.errors.append(str(exc))
                continue

            try:
                msg = client.fetch_message(message_id)
                # 提案送信以前のメール（スレッド内の過去メール）は無視し、誤取り込みを掃除
                valid_proposals = [p for p in group if _is_message_after_proposal(msg, p)]
                invalid_proposals = [p for p in group if p not in valid_proposals]
                if invalid_proposals:
                    _delete_invalid_auto_replies(
                        session=session,
                        group=invalid_proposals,
                        message_id=message_id,
                        known_keys=known_keys,
                    )
                if not valid_proposals:
                    session.commit()
                    continue

                now = datetime.now().astimezone()
                labeled_at = None
                try:
                    client.relabel_message(
                        message_id,
                        add_label_names=[reply_label],
                        remove_label_names=[],
                    )
                    labeled_at = now
                    stats.labeled += 1
                except Exception:  # noqa: BLE001
                    labeled_at = None

                judgments = judge_replies_with_ai(
                    _judge_items_for_group(session, valid_proposals, item_index_by_proposal),
                    msg.body_text,
                    cfg=cfg,
                    ok_keywords=ok_keywords,
                    ng_keywords=ng_keywords,
                )
                for proposal in valid_proposals:
                    judgment = judgments.get(proposal.id, "unknown")
                    existing = existing_by_proposal.get(proposal.id)
                    if existing is not None:
                        if existing.judgment_source == "auto":
                            existing.judgment = judgment
                            existing.body_text = msg.body_text
                            existing.received_at = msg.received_at
                        known_keys.add((proposal.id, message_id))
                        continue

                    reply = OutreachReply(
                        id=uuid.uuid4(),
                        outreach_message_id=proposal.id,
                        gmail_message_id=message_id,
                        thread_id=msg.thread_id,
                        received_at=msg.received_at,
                        body_text=msg.body_text,
                        judgment=judgment,
                        judgment_source="auto",
                        labeled_at=labeled_at,
                        created_at=now,
                    )
                    session.add(reply)
                    known_keys.add((proposal.id, message_id))
                    stats.new_replies += 1
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                stats.failed += 1
                stats.errors.append(str(exc))


def run_reply_sync_batch(
    cfg: Settings | None = None,
    *,
    kind: ReplySyncKind | None = None,
) -> ReplySyncStats:
    cfg = cfg or settings
    logger = get_batch_logger()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    stats = ReplySyncStats()
    sync_kind = _resolve_kind(kind)

    log_event(
        logger,
        logging.INFO,
        event="outreach.reply_sync.started",
        message="Reply sync batch started",
        operation="返信同期開始",
        method_name="run_reply_sync_batch",
        job_id=job_id,
        function_id="BAT-008",
        module_name="BAT-008.reply_sync",
        extra={"kind": sync_kind},
    )

    session_factory, engine = create_session_factory(cfg.database_url)
    ensure_schema(engine)
    ensure_gmail_credentials_file()

    with session_factory() as session:
        ok_keywords = parse_keywords(str(_load_setting(session, "reply_keywords_ok", "") or ""))
        ng_keywords = parse_keywords(str(_load_setting(session, "reply_keywords_ng", "") or ""))
        client = GmailClient(cfg.gmail_credentials_path, cfg.gmail_token_path)
        client.connect()
        known_keys = _existing_reply_keys(session)

        for proposal_kind in _kinds_to_sync(sync_kind):
            reply_label = _reply_label_for(session, proposal_kind)
            _sync_proposals(
                session=session,
                client=client,
                proposal_kind=proposal_kind,
                reply_label=reply_label,
                ok_keywords=ok_keywords,
                ng_keywords=ng_keywords,
                known_keys=known_keys,
                stats=stats,
                cfg=cfg,
            )

    log_event(
        logger,
        logging.INFO,
        event="outreach.reply_sync.finished",
        message="Reply sync batch finished",
        operation="返信同期完了",
        method_name="run_reply_sync_batch",
        job_id=job_id,
        function_id="BAT-008",
        module_name="BAT-008.reply_sync",
        extra={
            "kind": sync_kind,
            "new_replies": stats.new_replies,
            "labeled": stats.labeled,
            "failed": stats.failed,
            "threads": stats.threads,
        },
    )
    return stats
