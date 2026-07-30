"""Google Routes API（TRANSIT）クライアント。"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class RoutesResult:
    duration_minutes: int | None
    status: str
    raw_duration: str | None = None


def normalize_place_key(raw: str | None) -> str:
    text = (raw or "").strip()
    text = re.sub(r"[\s　]+", "", text)
    return text[:255]


def to_address_query(station_or_place: str, *, as_station: bool = False) -> str:
    text = (station_or_place or "").strip()
    if not text:
        return ""
    if as_station and "駅" not in text:
        return f"{text}駅, 日本"
    if "日本" not in text and "東京" not in text and "大阪" not in text:
        return f"{text}, 日本"
    return text


def parse_duration_seconds(duration: str | None) -> int | None:
    if not duration:
        return None
    match = re.fullmatch(r"(\d+)s", duration.strip())
    if not match:
        return None
    return int(match.group(1))


def fetch_transit_duration_minutes(
    *,
    api_key: str,
    origin: str,
    destination: str,
    timeout_seconds: float = 15.0,
) -> RoutesResult:
    """片道 TRANSIT の所要時間（分）を返す。"""
    if not api_key.strip():
        return RoutesResult(duration_minutes=None, status="no_api_key")
    origin_addr = to_address_query(origin, as_station=True)
    dest_addr = to_address_query(destination, as_station=False)
    if not origin_addr or not dest_addr:
        return RoutesResult(duration_minutes=None, status="missing_place")

    payload = {
        "origin": {"address": origin_addr},
        "destination": {"address": dest_addr},
        "travelMode": "TRANSIT",
        "languageCode": "ja",
        "regionCode": "JP",
    }
    request = urllib.request.Request(
        "https://routes.googleapis.com/directions/v2:computeRoutes",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "routes.duration,routes.distanceMeters",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:200]
        return RoutesResult(duration_minutes=None, status=f"http_{exc.code}:{detail}")
    except Exception as exc:  # noqa: BLE001
        return RoutesResult(duration_minutes=None, status=f"error:{exc}")

    routes = body.get("routes") or []
    if not routes:
        return RoutesResult(duration_minutes=None, status="no_route")
    duration = routes[0].get("duration")
    seconds = parse_duration_seconds(duration)
    if seconds is None:
        return RoutesResult(duration_minutes=None, status="bad_duration", raw_duration=duration)
    minutes = max(1, (seconds + 59) // 60)
    return RoutesResult(duration_minutes=minutes, status="ok", raw_duration=duration)
