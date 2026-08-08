"""ダッシュボード集計 API。"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, cast, func, or_, select
from sqlalchemy.orm import Session

from app.config import settings as app_settings
from app.db import load_settings
from app.deps import get_db
from app.gmail_client import GmailClient, GmailConfigError
from app.gmail_credentials import ensure_gmail_credentials_file
from app.match_run_query import latest_completed_match_run
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
)
from app.schemas import (
    DashboardCompanyIngest,
    DashboardDailyPoint,
    DashboardFunnel,
    DashboardFunnelConstraintLoss,
    DashboardResponse,
    DashboardScoreBandOk,
    DashboardSortQueueResponse,
)
from app.setting_keys import DEFAULT_SETTINGS, SETTING_KEY_GMAIL_SORT_SOURCE_LABEL
from app.sort_queue_cache import (
    SortQueueCacheEntry,
    get_cached_sort_queue,
    set_cached_sort_queue,
)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

_TZ = ZoneInfo("Asia/Tokyo")
PeriodRange = Literal["week", "month", "half_year", "year"]
_PERIOD_DAYS: dict[PeriodRange, int] = {
    "week": 7,
    "month": 30,
    "half_year": 182,
    "year": 365,
}
_COMPANY_TOP_N = 8


def _parse_end_day(raw: str | None) -> date:
    today = datetime.now(_TZ).date()
    if not raw:
        return today
    try:
        end_day = date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"error_code": "ERR-0001", "error_message": "end は YYYY-MM-DD 形式で指定してください。"},
        ) from exc
    if end_day > today:
        return today
    return end_day


def _period_bounds(period: PeriodRange, end_day: date) -> tuple[date, date, datetime, datetime]:
    """期間の開始・終了日と、DB 比較用の UTC 時刻範囲（終了は翌日 0:00 未満）。"""
    days = _PERIOD_DAYS[period]
    start_day = end_day - timedelta(days=days - 1)
    start_dt = datetime.combine(start_day, datetime.min.time(), tzinfo=_TZ).astimezone(timezone.utc)
    end_exclusive = end_day + timedelta(days=1)
    end_dt = datetime.combine(end_exclusive, datetime.min.time(), tzinfo=_TZ).astimezone(timezone.utc)
    return start_day, end_day, start_dt, end_dt


def _day_series(start_day: date, end_day: date) -> list[date]:
    days: list[date] = []
    cur = start_day
    while cur <= end_day:
        days.append(cur)
        cur += timedelta(days=1)
    return days


def _tokyo_date(column):  # noqa: ANN001
    return cast(func.timezone("Asia/Tokyo", column), Date)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(100.0 * numerator / denominator, 1)


def _unscored_entity_counts(session: Session) -> tuple[int, int]:
    """ルール採点（matches）に一度も出ていない active 人材 / open 案件の件数。"""
    scored_talent_ids = select(Match.talent_id).distinct()
    scored_project_ids = select(Match.project_id).distinct()
    unscored_talent_count = (
        session.scalar(
            select(func.count())
            .select_from(Talent)
            .where(Talent.status == "active", Talent.id.not_in(scored_talent_ids))
        )
        or 0
    )
    unscored_project_count = (
        session.scalar(
            select(func.count())
            .select_from(Project)
            .where(Project.status == "open", Project.id.not_in(scored_project_ids))
        )
        or 0
    )
    return int(unscored_talent_count), int(unscored_project_count)


def _hard_reject_code(breakdown: object) -> str | None:
    if not isinstance(breakdown, dict):
        return None
    code = breakdown.get("hard_reject")
    return str(code) if isinstance(code, str) and code else None


@router.get("", response_model=DashboardResponse)
def get_dashboard(
    session: Session = Depends(get_db),
    range: PeriodRange = Query("month", description="week / month / half_year / year"),
    end: str | None = Query(None, description="期間終了日 YYYY-MM-DD（省略時は今日）"),
) -> DashboardResponse:
    talent_count = session.scalar(select(func.count()).select_from(Talent)) or 0
    project_count = session.scalar(select(func.count()).select_from(Project)) or 0
    pending_email_count = (
        session.scalar(select(func.count()).select_from(Email).where(Email.status.in_(["pending", "failed"]))) or 0
    )
    talent_proposal_sent_count = (
        session.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(OutreachMessage.status == "sent", OutreachMessage.kind == "talent_proposal")
        )
        or 0
    )
    project_proposal_sent_count = (
        session.scalar(
            select(func.count())
            .select_from(OutreachMessage)
            .where(OutreachMessage.status == "sent", OutreachMessage.kind == "project_proposal")
        )
        or 0
    )

    today = datetime.now(_TZ).date()
    end_day = _parse_end_day(end)
    start_day, end_day, start_dt, end_dt = _period_bounds(range, end_day)
    days = _day_series(start_day, end_day)

    period_emails = list(
        session.scalars(
            select(Email).where(Email.created_at >= start_dt, Email.created_at < end_dt)
        ).all()
    )
    email_ids = [e.id for e in period_emails]

    talents_by_email: dict[UUID, Talent] = {}
    projects_by_email: dict[UUID, Project] = {}
    if email_ids:
        for talent in session.scalars(select(Talent).where(Talent.email_id.in_(email_ids))).all():
            talents_by_email[talent.email_id] = talent
        for project in session.scalars(select(Project).where(Project.email_id.in_(email_ids))).all():
            projects_by_email[project.email_id] = project

    proposed_talent_ids = set(
        session.scalars(
            select(OutreachMessage.talent_id).where(
                OutreachMessage.status == "sent",
                OutreachMessage.kind == "talent_proposal",
                OutreachMessage.talent_id.is_not(None),
            )
        ).all()
    )
    proposed_project_ids = set(
        session.scalars(
            select(OutreachMessage.project_id).where(
                OutreachMessage.status == "sent",
                OutreachMessage.kind == "project_proposal",
                OutreachMessage.project_id.is_not(None),
            )
        ).all()
    )

    company_ids = {
        *(t.introducer_company_id for t in talents_by_email.values() if t.introducer_company_id),
        *(p.distributor_company_id for p in projects_by_email.values() if p.distributor_company_id),
    }
    companies = {
        c.id: c
        for c in session.scalars(select(Company).where(Company.id.in_(company_ids))).all()
    } if company_ids else {}

    by_day: dict[date, DashboardDailyPoint] = {
        d: DashboardDailyPoint(date=d.isoformat()) for d in days
    }
    company_counts: dict[str | None, dict[str, int | str | None]] = defaultdict(
        lambda: {"company_id": None, "company_name": "不明", "emails_project": 0, "emails_talent": 0}
    )

    for email in period_emails:
        day = email.created_at.astimezone(_TZ).date() if email.created_at.tzinfo else email.created_at.replace(tzinfo=timezone.utc).astimezone(_TZ).date()
        if day not in by_day:
            continue
        point = by_day[day]
        point.emails_total += 1

        if email.email_type == "project":
            point.emails_project += 1
            project = projects_by_email.get(email.id)
            proposed = bool(project and project.id in proposed_project_ids)
            if proposed:
                point.project_proposed += 1
            else:
                point.project_unproposed += 1
            company_id = project.distributor_company_id if project else None
            key = str(company_id) if company_id else None
            bucket = company_counts[key]
            bucket["company_id"] = str(company_id) if company_id else None
            if company_id and company_id in companies:
                bucket["company_name"] = companies[company_id].name
            bucket["emails_project"] = int(bucket["emails_project"]) + 1
        elif email.email_type == "talent":
            point.emails_talent += 1
            talent = talents_by_email.get(email.id)
            proposed = bool(talent and talent.id in proposed_talent_ids)
            if proposed:
                point.talent_proposed += 1
            else:
                point.talent_unproposed += 1
            company_id = talent.introducer_company_id if talent else None
            key = str(company_id) if company_id else None
            bucket = company_counts[key]
            bucket["company_id"] = str(company_id) if company_id else None
            if company_id and company_id in companies:
                bucket["company_name"] = companies[company_id].name
            bucket["emails_talent"] = int(bucket["emails_talent"]) + 1
        else:
            point.emails_other += 1

    proposal_day = _tokyo_date(OutreachMessage.sent_at)
    proposal_rows = session.execute(
        select(proposal_day.label("day"), OutreachMessage.kind, func.count())
        .where(
            OutreachMessage.status == "sent",
            OutreachMessage.sent_at.is_not(None),
            OutreachMessage.sent_at >= start_dt,
            OutreachMessage.sent_at < end_dt,
            OutreachMessage.kind.in_(["talent_proposal", "project_proposal"]),
        )
        .group_by(proposal_day, OutreachMessage.kind)
    ).all()
    for day, kind, count in proposal_rows:
        if day is None or day not in by_day:
            continue
        point = by_day[day]
        n = int(count)
        if kind == "talent_proposal":
            point.proposals_project_offer += n
        elif kind == "project_proposal":
            point.proposals_talent_offer += n

    daily = [by_day[d] for d in days]

    company_rows = [
        DashboardCompanyIngest(
            company_id=str(row["company_id"]) if row["company_id"] else None,
            company_name=str(row["company_name"]),
            emails_project=int(row["emails_project"]),
            emails_talent=int(row["emails_talent"]),
            emails_total=int(row["emails_project"]) + int(row["emails_talent"]),
        )
        for row in company_counts.values()
    ]
    company_rows.sort(key=lambda r: r.emails_total, reverse=True)
    if len(company_rows) > _COMPANY_TOP_N:
        top = company_rows[:_COMPANY_TOP_N]
        rest = company_rows[_COMPANY_TOP_N:]
        top.append(
            DashboardCompanyIngest(
                company_id=None,
                company_name="その他",
                emails_project=sum(r.emails_project for r in rest),
                emails_talent=sum(r.emails_talent for r in rest),
                emails_total=sum(r.emails_total for r in rest),
            )
        )
        company_rows = top

    funnel = _build_funnel(
        session,
        talent_ids={t.id for t in talents_by_email.values()},
        project_ids={p.id for p in projects_by_email.values()},
        proposed_talent_ids=proposed_talent_ids,
        proposed_project_ids=proposed_project_ids,
    )
    ok_by_score_band = _build_ok_by_score_band(session, start_dt=start_dt, end_dt=end_dt)

    emails_total = sum(p.emails_total for p in daily)
    emails_project = sum(p.emails_project for p in daily)
    emails_talent = sum(p.emails_talent for p in daily)
    project_unproposed = sum(p.project_unproposed for p in daily)
    project_proposed = sum(p.project_proposed for p in daily)
    talent_unproposed = sum(p.talent_unproposed for p in daily)
    talent_proposed = sum(p.talent_proposed for p in daily)
    emails_other = sum(p.emails_other for p in daily)

    unscored_talent_count, unscored_project_count = _unscored_entity_counts(session)

    return DashboardResponse(
        talent_count=int(talent_count),
        project_count=int(project_count),
        pending_email_count=int(pending_email_count),
        talent_proposal_sent_count=int(talent_proposal_sent_count),
        project_proposal_sent_count=int(project_proposal_sent_count),
        unscored_talent_count=unscored_talent_count,
        unscored_project_count=unscored_project_count,
        period_range=range,
        period_days=_PERIOD_DAYS[range],
        period_start=start_day.isoformat(),
        period_end=end_day.isoformat(),
        can_go_forward=end_day < today,
        emails_total=emails_total,
        emails_project=emails_project,
        emails_talent=emails_talent,
        project_unproposed=project_unproposed,
        project_proposed=project_proposed,
        talent_unproposed=talent_unproposed,
        talent_proposed=talent_proposed,
        emails_other=emails_other,
        proposals_project_offer=sum(p.proposals_project_offer for p in daily),
        proposals_talent_offer=sum(p.proposals_talent_offer for p in daily),
        project_proposed_rate=_rate(project_proposed, emails_project),
        talent_proposed_rate=_rate(talent_proposed, emails_talent),
        daily=daily,
        by_company=company_rows,
        funnel=funnel,
        ok_by_score_band=ok_by_score_band,
    )


def _build_funnel(
    session: Session,
    *,
    talent_ids: set[UUID],
    project_ids: set[UUID],
    proposed_talent_ids: set[UUID],
    proposed_project_ids: set[UUID],
) -> DashboardFunnel:
    ingested = len(talent_ids) + len(project_ids)
    if ingested == 0:
        return DashboardFunnel()

    latest_run = latest_completed_match_run(session)
    matches: list[Match] = []
    if latest_run is not None and (talent_ids or project_ids):
        conditions = []
        if talent_ids:
            conditions.append(Match.talent_id.in_(talent_ids))
        if project_ids:
            conditions.append(Match.project_id.in_(project_ids))
        matches = list(
            session.scalars(
                select(Match).where(Match.match_run_id == latest_run.id, or_(*conditions))
            ).all()
        )

    talent_positive: set[UUID] = set()
    project_positive: set[UUID] = set()
    talent_reject: dict[UUID, str] = {}
    project_reject: dict[UUID, str] = {}

    for match in matches:
        code = _hard_reject_code(match.score_breakdown)
        if match.score > 0:
            if match.talent_id in talent_ids:
                talent_positive.add(match.talent_id)
            if match.project_id in project_ids:
                project_positive.add(match.project_id)
        else:
            if match.talent_id in talent_ids and match.talent_id not in talent_positive:
                prev = talent_reject.get(match.talent_id)
                talent_reject[match.talent_id] = _prefer_reject(prev, code)
            if match.project_id in project_ids and match.project_id not in project_positive:
                prev = project_reject.get(match.project_id)
                project_reject[match.project_id] = _prefer_reject(prev, code)

    # Clear reject tags once positive exists
    for tid in talent_positive:
        talent_reject.pop(tid, None)
    for pid in project_positive:
        project_reject.pop(pid, None)

    proposable_talents = talent_ids & talent_positive
    proposable_projects = project_ids & project_positive
    proposable = len(proposable_talents) + len(proposable_projects)

    proposed_talents = proposable_talents & proposed_talent_ids
    proposed_projects = proposable_projects & proposed_project_ids
    proposed = len(proposed_talents) + len(proposed_projects)

    replied_talents, ok_talents = _reply_outcomes_for_talents(session, proposed_talents)
    replied_projects, ok_projects = _reply_outcomes_for_projects(session, proposed_projects)
    replied = len(replied_talents) + len(replied_projects)
    ok = len(ok_talents) + len(ok_projects)

    non_proposable_talents = talent_ids - talent_positive
    non_proposable_projects = project_ids - project_positive
    foreign = 0
    commerce = 0
    other_zero = 0
    for tid in non_proposable_talents:
        code = talent_reject.get(tid)
        if code == "foreign_nationality":
            foreign += 1
        elif code == "commerce_flow":
            commerce += 1
        else:
            other_zero += 1
    for pid in non_proposable_projects:
        code = project_reject.get(pid)
        if code == "foreign_nationality":
            foreign += 1
        elif code == "commerce_flow":
            commerce += 1
        else:
            other_zero += 1

    loss_total = len(non_proposable_talents) + len(non_proposable_projects)
    return DashboardFunnel(
        ingested=ingested,
        proposable=proposable,
        proposed=proposed,
        replied=replied,
        ok=ok,
        constraint_loss=DashboardFunnelConstraintLoss(
            foreign_nationality=foreign,
            commerce_flow=commerce,
            other_zero=other_zero,
            total=loss_total,
        ),
    )


def _prefer_reject(current: str | None, new_code: str | None) -> str:
    order = {"foreign_nationality": 0, "commerce_flow": 1}
    candidates = [c for c in (current, new_code) if c]
    if not candidates:
        return "other_zero"
    return min(candidates, key=lambda c: order.get(c, 9))


def _reply_outcomes_for_talents(
    session: Session, talent_ids: set[UUID]
) -> tuple[set[UUID], set[UUID]]:
    if not talent_ids:
        return set(), set()
    messages = list(
        session.scalars(
            select(OutreachMessage).where(
                OutreachMessage.status == "sent",
                OutreachMessage.kind == "talent_proposal",
                OutreachMessage.talent_id.in_(talent_ids),
            )
        ).all()
    )
    return _reply_outcomes_from_messages(session, messages, entity_id_fn=lambda m: m.talent_id)


def _reply_outcomes_for_projects(
    session: Session, project_ids: set[UUID]
) -> tuple[set[UUID], set[UUID]]:
    if not project_ids:
        return set(), set()
    messages = list(
        session.scalars(
            select(OutreachMessage).where(
                OutreachMessage.status == "sent",
                OutreachMessage.kind == "project_proposal",
                OutreachMessage.project_id.in_(project_ids),
            )
        ).all()
    )
    return _reply_outcomes_from_messages(session, messages, entity_id_fn=lambda m: m.project_id)


def _reply_outcomes_from_messages(
    session: Session,
    messages: list[OutreachMessage],
    *,
    entity_id_fn,
) -> tuple[set[UUID], set[UUID]]:
    if not messages:
        return set(), set()
    message_ids = [m.id for m in messages]
    replies = list(
        session.scalars(
            select(OutreachReply)
            .where(OutreachReply.outreach_message_id.in_(message_ids))
            .order_by(OutreachReply.received_at.desc())
        ).all()
    )
    latest_by_message: dict[UUID, OutreachReply] = {}
    for reply in replies:
        latest_by_message.setdefault(reply.outreach_message_id, reply)

    replied: set[UUID] = set()
    ok: set[UUID] = set()
    for message in messages:
        entity_id = entity_id_fn(message)
        if entity_id is None:
            continue
        reply = latest_by_message.get(message.id)
        if reply is None:
            continue
        replied.add(entity_id)
        if reply.judgment == "ok":
            ok.add(entity_id)
    return replied, ok


def _build_ok_by_score_band(
    session: Session, *, start_dt: datetime, end_dt: datetime
) -> list[DashboardScoreBandOk]:
    messages = list(
        session.scalars(
            select(OutreachMessage).where(
                OutreachMessage.status == "sent",
                OutreachMessage.sent_at.is_not(None),
                OutreachMessage.sent_at >= start_dt,
                OutreachMessage.sent_at < end_dt,
                OutreachMessage.kind.in_(["talent_proposal", "project_proposal"]),
            )
        ).all()
    )
    if not messages:
        return []

    match_ids: set[UUID] = set()
    for message in messages:
        if message.kind == "talent_proposal" and message.match_id is not None:
            match_ids.add(message.match_id)

    project_message_ids = [m.id for m in messages if m.kind == "project_proposal"]
    if project_message_ids:
        links = list(
            session.scalars(
                select(OutreachMessageTalent).where(
                    OutreachMessageTalent.outreach_message_id.in_(project_message_ids)
                )
            ).all()
        )
        for link in links:
            if link.match_id is not None:
                match_ids.add(link.match_id)
    else:
        links = []

    matches = {
        m.id: m
        for m in session.scalars(select(Match).where(Match.id.in_(match_ids))).all()
    } if match_ids else {}

    replies = list(
        session.scalars(
            select(OutreachReply)
            .where(OutreachReply.outreach_message_id.in_([m.id for m in messages]))
            .order_by(OutreachReply.received_at.desc())
        ).all()
    )
    latest_reply: dict[UUID, OutreachReply] = {}
    for reply in replies:
        latest_reply.setdefault(reply.outreach_message_id, reply)

    stats: dict[str, dict[str, int]] = defaultdict(lambda: {"proposed_count": 0, "ok_count": 0})

    for message in messages:
        if message.kind == "talent_proposal":
            mid = message.match_id
            if mid is None or mid not in matches:
                band = "不明"
            else:
                band = matches[mid].score_band or "不明"
            stats[band]["proposed_count"] += 1
            reply = latest_reply.get(message.id)
            if reply is not None and reply.judgment == "ok":
                stats[band]["ok_count"] += 1
        else:
            msg_links = [link for link in links if link.outreach_message_id == message.id]
            if not msg_links:
                band = "不明"
                stats[band]["proposed_count"] += 1
                reply = latest_reply.get(message.id)
                if reply is not None and reply.judgment == "ok":
                    stats[band]["ok_count"] += 1
                continue
            reply = latest_reply.get(message.id)
            for link in msg_links:
                if link.match_id is not None and link.match_id in matches:
                    band = matches[link.match_id].score_band or "不明"
                else:
                    band = "不明"
                stats[band]["proposed_count"] += 1
                if reply is not None and reply.judgment == "ok":
                    stats[band]["ok_count"] += 1

    rows = [
        DashboardScoreBandOk(
            score_band=band,
            proposed_count=vals["proposed_count"],
            ok_count=vals["ok_count"],
            ok_rate=_rate(vals["ok_count"], vals["proposed_count"]),
        )
        for band, vals in stats.items()
    ]
    rows.sort(key=lambda r: (-r.proposed_count, r.score_band))
    return rows


def _sort_source_label(raw: dict) -> str:
    value = raw.get(SETTING_KEY_GMAIL_SORT_SOURCE_LABEL)
    if isinstance(value, str) and value.strip():
        return value.strip()
    default = DEFAULT_SETTINGS.get(SETTING_KEY_GMAIL_SORT_SOURCE_LABEL, "SES未振り分け")
    return str(default)


def _entry_to_response(entry: SortQueueCacheEntry, *, cached: bool) -> DashboardSortQueueResponse:
    payload = entry.to_payload(cached=cached)
    return DashboardSortQueueResponse(
        label=str(payload["label"]),
        count=None if entry.error_code else int(payload["count"]),
        capped=bool(payload["capped"]),
        cached=cached,
        fetched_at=str(payload["fetched_at"]),
        expires_at=str(payload["expires_at"]),
        cache_ttl_seconds=int(payload["cache_ttl_seconds"]),
        error_code=entry.error_code,
        error_message=entry.error_message,
    )


@router.get("/sort-queue", response_model=DashboardSortQueueResponse)
def get_sort_queue(
    session: Session = Depends(get_db),
    refresh: bool = Query(False, description="true のときキャッシュを無視して再取得"),
) -> DashboardSortQueueResponse:
    """振り分け対象ラベルの Gmail 件数を返す（15 分キャッシュ）。

    ダッシュボード本体とは分離し、Gmail API 遅延がチャート表示を止めないようにする。
    """
    raw = load_settings(session)
    label = _sort_source_label(raw)

    if not refresh:
        cached = get_cached_sort_queue()
        if cached is not None and cached.label == label and cached.is_fresh():
            return _entry_to_response(cached, cached=True)

    fetched_at = datetime.now(UTC)

    if not ensure_gmail_credentials_file(raw):
        entry = SortQueueCacheEntry(
            label=label,
            count=0,
            capped=False,
            fetched_at=fetched_at,
            error_code="ERR-0018",
            error_message="Gmail が連携されていません。",
        )
        set_cached_sort_queue(entry)
        return _entry_to_response(entry, cached=False)

    client = GmailClient(str(app_settings.gmail_credentials_path), str(app_settings.gmail_token_path))
    try:
        client.connect()
        count, capped = client.count_messages_with_label(label)
        entry = SortQueueCacheEntry(
            label=label,
            count=count,
            capped=capped,
            fetched_at=fetched_at,
        )
    except GmailConfigError as exc:
        entry = SortQueueCacheEntry(
            label=label,
            count=0,
            capped=False,
            fetched_at=fetched_at,
            error_code=exc.error_code,
            error_message=exc.message,
        )

    set_cached_sort_queue(entry)
    return _entry_to_response(entry, cached=False)
