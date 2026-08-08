"""バッチが参照する DB テーブルの SQLAlchemy モデル定義。

スキーマの正は ``.docker/db/init/``。
ここではバッチ処理に必要なテーブルのみを定義する。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, SmallInteger, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """全モデルの基底クラス。"""


class Email(Base):
    """Gmail から取り込んだメールの管理テーブル。"""

    __tablename__ = "emails"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    gmail_message_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(128))
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    from_address: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    # 案件紹介下書き用: ヘッダー/フッター除去後のコア原文（LLM 抽出・キャッシュ）
    body_core_text: Mapped[str | None] = mapped_column(Text)
    email_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    source_company_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    cc_addresses: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Company(Base):
    """紹介元・配信元企業マスタ。"""

    __tablename__ = "companies"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="both")
    domain: Mapped[str | None] = mapped_column(String(255))
    default_email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Contact(Base):
    """企業ごとの担当者。"""

    __tablename__ = "contacts"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    company_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="primary")
    phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SkillCategory(Base):
    """スキルカテゴリマスタ。"""

    __tablename__ = "skill_categories"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_uncategorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Skill(Base):
    """スキルマスタ。"""

    __tablename__ = "skills"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    category_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Talent(Base):
    """BAT-002 で AI 抽出した人材情報。"""

    __tablename__ = "talents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    email_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    introducer_company_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    affiliation: Mapped[str | None] = mapped_column(String(255))
    age: Mapped[int | None] = mapped_column(SmallInteger)
    gender: Mapped[str | None] = mapped_column(String(16))
    experience_years: Mapped[int | None] = mapped_column(SmallInteger)
    desired_rate: Mapped[int | None] = mapped_column(Integer)
    available_from: Mapped[str | None] = mapped_column(String(64))
    work_style: Mapped[str | None] = mapped_column(String(255))
    nearest_station: Mapped[str | None] = mapped_column(String(64))
    skills: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    source_company_name: Mapped[str | None] = mapped_column(String(255))
    is_foreign_national: Mapped[bool | None] = mapped_column(Boolean)
    commerce_flow: Mapped[str | None] = mapped_column(String(64))
    summary: Mapped[str | None] = mapped_column(Text)
    proposal_cc_emails: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Project(Base):
    """BAT-002 で AI 抽出した案件情報。"""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    email_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, nullable=False)
    distributor_company_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    project_code: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    required_skills: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    rate_min: Mapped[int | None] = mapped_column(Integer)
    rate_max: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String(128))
    work_style: Mapped[str | None] = mapped_column(String(255))
    working_hours: Mapped[str | None] = mapped_column(String(128))
    start_date: Mapped[str | None] = mapped_column(String(64))
    foreign_nationality_ng: Mapped[bool | None] = mapped_column(Boolean)
    commerce_flow_limit: Mapped[str | None] = mapped_column(String(64))
    settlement_range: Mapped[str | None] = mapped_column(String(64))
    interview_count: Mapped[int | None] = mapped_column(SmallInteger)
    headcount: Mapped[int | None] = mapped_column(SmallInteger)
    summary: Mapped[str | None] = mapped_column(Text)
    proposal_cc_emails: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemSetting(Base):
    """画面の設定画面で保存される key-value 設定。"""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MatchRun(Base):
    """BAT-003 マッチング実行単位。"""

    __tablename__ = "match_runs"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    ai_judgement_top_n: Mapped[int | None] = mapped_column(SmallInteger)
    ai_assist_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    stats: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Match(Base):
    """人材×案件のルールスコア結果。"""

    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("match_run_id", "talent_id", "project_id"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    match_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    talent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    project_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    score_band: Mapped[str | None] = mapped_column(String(8))
    score_breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_score: Mapped[int | None] = mapped_column(SmallInteger)
    reason: Mapped[str | None] = mapped_column(Text)
    recommendation_points: Mapped[str | None] = mapped_column(Text)
    ai_judged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommuteCache(Base):
    """Google Routes 通勤時間キャッシュ。"""

    __tablename__ = "commute_cache"
    __table_args__ = (UniqueConstraint("origin_key", "destination_key", "provider"),)

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    origin_key: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_key: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="google_routes")
    raw_status: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommuteApiUsage(Base):
    """Google Routes 月次呼び出し回数。"""

    __tablename__ = "commute_api_usage"

    year_month: Mapped[str] = mapped_column(String(7), primary_key=True)
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutreachMessage(Base):
    """提案メール送信履歴（要員提案 / 案件提案）。"""

    __tablename__ = "outreach_messages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    match_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    talent_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    project_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    gmail_message_id: Mapped[str | None] = mapped_column(String(128))
    thread_id: Mapped[str | None] = mapped_column(String(128))
    in_reply_to_email_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    subject: Mapped[str | None] = mapped_column(Text)
    body_text: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutreachMessageTalent(Base):
    """案件提案メールに含めた要員。"""

    __tablename__ = "outreach_message_talents"

    outreach_message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    talent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    match_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))


class OutreachReply(Base):
    """要員提案メールへの返信と OK/NG 判定。"""

    __tablename__ = "outreach_replies"
    __table_args__ = (
        UniqueConstraint(
            "outreach_message_id",
            "gmail_message_id",
            name="uq_outreach_replies_message_gmail",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    outreach_message_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    gmail_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(128))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)
    judgment: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    judgment_source: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    labeled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TalentSkillSheet(Base):
    """人材スキルシート（共有ドライブ上のファイルメタ）。"""

    __tablename__ = "talent_skill_sheets"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    talent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    email_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    # Gmail attachmentId は 128 超になり得るため Text
    original_attachment_id: Mapped[str | None] = mapped_column(Text)
    drive_file_id: Mapped[str | None] = mapped_column(String(128))
    drive_folder_id: Mapped[str | None] = mapped_column(String(128))
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content_type: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    access_status: Mapped[str] = mapped_column(String(32), nullable=False, default="failed")
    error_message: Mapped[str | None] = mapped_column(Text)
    web_view_link: Mapped[str | None] = mapped_column(Text)
    experience_text: Mapped[str | None] = mapped_column(Text)
    experience_extract_status: Mapped[str | None] = mapped_column(String(16))
    experience_extracted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
