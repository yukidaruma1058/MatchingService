"""バッチ共通の DB 接続初期化。"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base


def create_session_factory(database_url: str):
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False), engine


def ensure_schema(engine) -> None:
    Base.metadata.create_all(bind=engine)
    # 既存 DB 向けの後方互換カラム追加
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
    with sessionmaker(bind=engine, autoflush=False, autocommit=False)() as session:
        from app.skill_catalog import seed_skill_master

        seed_skill_master(session)
        session.commit()
