"""Gmail ラベル設定の読込（BAT-002 取込・提案・返信同期で共通）。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import SystemSetting


@dataclass(frozen=True)
class GmailLabelSettings:
    """Gmail 上の人材 / 案件ラベル（設定画面で指定）。"""

    talent_label: str
    project_label: str


# 後方互換の別名
SortSettings = GmailLabelSettings


@dataclass(frozen=True)
class IngestSettings:
    """BAT-002 取込・要約設定。"""

    talent_label: str
    project_label: str
    processed_talent_label: str
    processed_project_label: str


def _load_db_values(session: Session) -> dict[str, object]:
    return {row.key: row.value for row in session.scalars(select(SystemSetting)).all()}


def _pick(db_values: dict[str, object], key: str, env_value: str) -> str:
    if key in db_values:
        raw = db_values[key]
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, list):
            return "\n".join(str(item) for item in raw)
    return env_value.strip()


def processed_label_for(base_label: str) -> str:
    """人材用/案件用ラベル名から処理済みラベルを生成する。"""
    base = (base_label or "").strip() or "未設定"
    if base.endswith("（処理済み）") or base.endswith("(処理済み)"):
        return base
    return f"{base}（処理済み）"


def reply_label_for(base_label: str) -> str:
    """人材用/案件用ラベル名から返信用ラベルを生成する。"""
    base = (base_label or "").strip() or "未設定"
    if base.endswith("返信"):
        return base
    return f"{base}返信"


def load_gmail_label_settings(session: Session, cfg: Settings) -> GmailLabelSettings:
    db_values = _load_db_values(session)
    talent_label = _pick(db_values, "gmail_sort_label_talent", cfg.gmail_sort_label_talent or cfg.gmail_label_talent)
    project_label = _pick(db_values, "gmail_sort_label_project", cfg.gmail_sort_label_project or cfg.gmail_label_project)
    return GmailLabelSettings(
        talent_label=talent_label,
        project_label=project_label,
    )


def load_sort_settings(session: Session, cfg: Settings) -> GmailLabelSettings:
    """後方互換。load_gmail_label_settings と同じ。"""
    return load_gmail_label_settings(session, cfg)


def load_ingest_settings(session: Session, cfg: Settings) -> IngestSettings:
    label_settings = load_gmail_label_settings(session, cfg)
    return IngestSettings(
        talent_label=label_settings.talent_label,
        project_label=label_settings.project_label,
        processed_talent_label=processed_label_for(label_settings.talent_label),
        processed_project_label=processed_label_for(label_settings.project_label),
    )


def move_to_reply_label(
    client: object,
    *,
    message_ids: list[str],
    base_label: str,
) -> str:
    """返信用ラベルを作成し、指定メールを人材/案件・処理済みから貼り替える。"""
    reply = reply_label_for(base_label)
    processed = processed_label_for(base_label)
    base = (base_label or "").strip()
    ensure_label = getattr(client, "ensure_label")
    relabel_message = getattr(client, "relabel_message")
    ensure_label(reply)
    remove_names = [name for name in (base, processed) if name and name != reply]
    for message_id in message_ids:
        mid = (message_id or "").strip()
        if not mid:
            continue
        relabel_message(
            mid,
            add_label_names=[reply],
            remove_label_names=remove_names,
        )
    return reply
