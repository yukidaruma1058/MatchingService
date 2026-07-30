"""BAT-003: 通勤キャッシュと月次 API 利用カウンタ。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import CommuteApiUsage, CommuteCache
from google_routes import fetch_transit_duration_minutes, normalize_place_key


def current_year_month(now: datetime | None = None) -> str:
    stamp = now or datetime.now(timezone.utc)
    return stamp.strftime("%Y-%m")


def get_monthly_usage(session: Session, year_month: str | None = None) -> int:
    ym = year_month or current_year_month()
    row = session.get(CommuteApiUsage, ym)
    return int(row.request_count) if row else 0


def increment_monthly_usage(session: Session, year_month: str | None = None) -> int:
    ym = year_month or current_year_month()
    now = datetime.now(timezone.utc)
    stmt = insert(CommuteApiUsage).values(year_month=ym, request_count=1, updated_at=now)
    stmt = stmt.on_conflict_do_update(
        index_elements=[CommuteApiUsage.year_month],
        set_={
            "request_count": CommuteApiUsage.request_count + 1,
            "updated_at": now,
        },
    )
    session.execute(stmt)
    session.flush()
    return get_monthly_usage(session, ym)


def get_cached_commute(
    session: Session,
    *,
    origin: str,
    destination: str,
    provider: str = "google_routes",
) -> CommuteCache | None:
    origin_key = normalize_place_key(origin)
    destination_key = normalize_place_key(destination)
    if not origin_key or not destination_key:
        return None
    return session.scalar(
        select(CommuteCache).where(
            CommuteCache.origin_key == origin_key,
            CommuteCache.destination_key == destination_key,
            CommuteCache.provider == provider,
        )
    )


def upsert_commute_cache(
    session: Session,
    *,
    origin: str,
    destination: str,
    duration_minutes: int | None,
    status: str,
    provider: str = "google_routes",
) -> None:
    origin_key = normalize_place_key(origin)
    destination_key = normalize_place_key(destination)
    if not origin_key or not destination_key:
        return
    now = datetime.now(timezone.utc)
    stmt = insert(CommuteCache).values(
        id=uuid4(),
        origin_key=origin_key,
        destination_key=destination_key,
        duration_minutes=duration_minutes,
        provider=provider,
        raw_status=status[:64],
        fetched_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[CommuteCache.origin_key, CommuteCache.destination_key, CommuteCache.provider],
        set_={
            "duration_minutes": duration_minutes,
            "raw_status": status[:64],
            "fetched_at": now,
        },
    )
    session.execute(stmt)


def resolve_commute_minutes(
    session: Session,
    *,
    api_key: str,
    origin: str | None,
    destination: str | None,
    monthly_warn: int,
    monthly_limit: int,
    logger: Any = None,
) -> tuple[int | None, str, bool]:
    """キャッシュ優先で通勤分を返す。

    Returns:
        (minutes, status, called_api)
    """
    if not origin or not destination:
        return None, "missing_place", False

    cached = get_cached_commute(session, origin=origin, destination=destination)
    if cached is not None:
        return cached.duration_minutes, cached.raw_status or "cache_hit", False

    if not api_key.strip():
        return None, "no_api_key", False

    usage = get_monthly_usage(session)
    if usage >= monthly_limit:
        return None, "monthly_limit", False
    if usage >= monthly_warn and logger is not None:
        logger.warning(
            "Google Routes monthly usage warning: %s/%s",
            usage,
            monthly_limit,
        )

    result = fetch_transit_duration_minutes(
        api_key=api_key,
        origin=origin,
        destination=destination,
    )
    increment_monthly_usage(session)
    upsert_commute_cache(
        session,
        origin=origin,
        destination=destination,
        duration_minutes=result.duration_minutes,
        status=result.status,
    )
    return result.duration_minutes, result.status, True
