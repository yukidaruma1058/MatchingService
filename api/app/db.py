"""API 用の DB セッションと system_settings アクセス。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Base, SystemSetting
from app.setting_keys import DEFAULT_SETTINGS

SETTING_KEY_INGEST_RETENTION_DAYS = "ingest_data_retention_days"


def create_session_factory(database_url: str | None = None):
    engine = create_engine(database_url or settings.database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def ensure_schema(engine) -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE talents ADD COLUMN IF NOT EXISTS source_company_name VARCHAR(255)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE talents ADD COLUMN IF NOT EXISTS is_foreign_national BOOLEAN"
        )
        conn.exec_driver_sql(
            "ALTER TABLE talents ADD COLUMN IF NOT EXISTS commerce_flow VARCHAR(64)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE talents ADD COLUMN IF NOT EXISTS gender VARCHAR(16)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS foreign_nationality_ng BOOLEAN"
        )
        conn.exec_driver_sql(
            "ALTER TABLE projects ALTER COLUMN foreign_nationality_ng DROP NOT NULL"
        )
        conn.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS commerce_flow_limit VARCHAR(64)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS interview_count SMALLINT"
        )
        conn.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS headcount SMALLINT"
        )
        conn.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS working_hours VARCHAR(128)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS settlement_range VARCHAR(64)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE emails ADD COLUMN IF NOT EXISTS cc_addresses JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
        conn.exec_driver_sql(
            "ALTER TABLE talents ADD COLUMN IF NOT EXISTS proposal_cc_emails JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
        conn.exec_driver_sql(
            "ALTER TABLE projects ADD COLUMN IF NOT EXISTS proposal_cc_emails JSONB NOT NULL DEFAULT '[]'::jsonb"
        )
        conn.exec_driver_sql(
            "ALTER TABLE matches ADD COLUMN IF NOT EXISTS recommendation_points TEXT"
        )
        conn.exec_driver_sql(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'talent_skill_sheets'
              ) THEN
                ALTER TABLE talent_skill_sheets
                  ALTER COLUMN original_attachment_id TYPE TEXT;
              END IF;
            END $$;
            """
        )
        conn.exec_driver_sql(
            "ALTER TABLE talent_skill_sheets ADD COLUMN IF NOT EXISTS experience_text TEXT"
        )
        conn.exec_driver_sql(
            "ALTER TABLE talent_skill_sheets ADD COLUMN IF NOT EXISTS experience_extract_status VARCHAR(16)"
        )
        conn.exec_driver_sql(
            "ALTER TABLE talent_skill_sheets ADD COLUMN IF NOT EXISTS experience_extracted_at TIMESTAMPTZ"
        )
        # 1通の返信を複数提案へ紐づけ可能にする
        conn.exec_driver_sql(
            "ALTER TABLE outreach_replies DROP CONSTRAINT IF EXISTS outreach_replies_gmail_message_id_key"
        )
        conn.exec_driver_sql(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_outreach_replies_message_gmail'
              ) THEN
                ALTER TABLE outreach_replies
                  ADD CONSTRAINT uq_outreach_replies_message_gmail
                  UNIQUE (outreach_message_id, gmail_message_id);
              END IF;
            END $$;
            """
        )
        conn.exec_driver_sql(
            """
            DELETE FROM system_settings
            WHERE key IN ('auto_match_enabled', 'gmail_label_talent_reply')
            """
        )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as session:
        from app.skill_catalog import seed_skill_master

        seed_skill_master(session)
        session.commit()


def _normalize_setting_value(raw: Any) -> Any:
    if isinstance(raw, (str, int, float, bool, list, dict)) or raw is None:
        return raw
    return str(raw)


def load_settings(session: Session) -> dict[str, Any]:
    """DB の設定値をデフォルトとマージして返す。"""
    merged = dict(DEFAULT_SETTINGS)
    rows = session.scalars(select(SystemSetting)).all()
    for row in rows:
        merged[row.key] = _normalize_setting_value(row.value)
    return merged


def upsert_settings(session: Session, values: dict[str, Any]) -> dict[str, Any]:
    """指定キーを system_settings へ upsert し、マージ後の全設定を返す。"""
    now_expr = func.now()
    for key, value in values.items():
        stmt = insert(SystemSetting).values(key=key, value=value, updated_at=now_expr)
        stmt = stmt.on_conflict_do_update(
            index_elements=[SystemSetting.key],
            set_={"value": value, "updated_at": now_expr},
        )
        session.execute(stmt)
    session.commit()
    return load_settings(session)
