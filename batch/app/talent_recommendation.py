"""提案メール用おすすめポイントの解決ヘルパー。

本番の生成は BAT-004（AI採点）で行い matches.recommendation_points に保存する。
matches.reason（採点根拠）はメールに載せない。
提案時は保存済み recommendation_points がある場合のみ載せる。
"""

from __future__ import annotations

from typing import Any, Sequence


def resolve_recommendation_points(
    *,
    stored: str | None,
    display_name: str | None = None,
    skills: Sequence[Any] | None = None,
    reason: str | None = None,
) -> str | None:
    # 互換のため余分な引数は受け取るが、保存済み文言以外は使わない
    _ = (display_name, skills, reason)
    text = (stored or "").strip()
    return text or None
