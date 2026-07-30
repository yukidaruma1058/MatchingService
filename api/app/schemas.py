"""API リクエスト / レスポンスの Pydantic スキーマ。"""

from typing import Literal

from pydantic import BaseModel, Field

GmailAuthStatus = Literal["connected", "disconnected", "expired"]


class SettingsResponse(BaseModel):
    """設定画面で利用する system_settings の取得レスポンス。"""

    ingest_data_retention_days: int = Field(0, ge=0, le=3650)
    gmail_sort_source_label: str = "SES未振り分け"
    gmail_sort_label_talent: str = "SES人材紹介"
    gmail_sort_label_project: str = "SES案件配信"
    gmail_sort_unknown_label: str = "SES要確認"
    gmail_sort_keywords_talent: str = "人材\n要員\nスキルシート\nご紹介"
    gmail_sort_keywords_project: str = "案件\n募集\n開発\nお問い合わせ"
    ai_assist_enabled: bool = False
    ai_judgement_top_n: int = Field(5, ge=1, le=20)
    own_company_name: str = ""
    apply_from_address: str = ""
    reply_keywords_ok: str = "よろしくお願いします\n前向き\n候補として\nご提案ください"
    reply_keywords_ng: str = "見送り\n他決\n辞退\n今回は結構"
    outreach_template_project_propose: str = ""
    outreach_template_talent_propose: str = ""
    # 人材提案メールの単価に加算する万円（0 = 加算なし）
    talent_propose_rate_markup_man_yen: int = Field(0, ge=0, le=100)
    skill_sheet_drive_folder_id: str = ""
    gmail_connected_account: str | None = None
    gmail_auth_status: GmailAuthStatus = "disconnected"
    gmail_last_checked_at: str | None = None
    gmail_error_code: str | None = None
    gmail_setup_required: bool = False
    gmail_setup_message: str | None = None
    gmail_oauth_client_configured: bool = False
    gmail_oauth_client_id: str | None = None
    gmail_oauth_redirect_uri: str = ""


class SettingsUpdateRequest(BaseModel):
    """設定画面からの部分更新リクエスト。"""

    ingest_data_retention_days: int | None = Field(None, ge=0, le=3650)
    gmail_sort_source_label: str | None = None
    gmail_sort_label_talent: str | None = None
    gmail_sort_label_project: str | None = None
    gmail_sort_unknown_label: str | None = None
    gmail_sort_keywords_talent: str | None = None
    gmail_sort_keywords_project: str | None = None
    ai_assist_enabled: bool | None = None
    ai_judgement_top_n: int | None = Field(None, ge=1, le=20)
    own_company_name: str | None = None
    apply_from_address: str | None = None
    reply_keywords_ok: str | None = None
    reply_keywords_ng: str | None = None
    outreach_template_project_propose: str | None = None
    outreach_template_talent_propose: str | None = None
    talent_propose_rate_markup_man_yen: int | None = Field(None, ge=0, le=100)
    skill_sheet_drive_folder_id: str | None = None
    gmail_oauth_client_id: str | None = None
    gmail_oauth_client_secret: str | None = None
    gmail_oauth_project_id: str | None = None


class EmailListItem(BaseModel):
    id: str
    gmail_message_id: str
    subject: str
    from_address: str
    label: str
    email_type: str
    status: str
    received_at: str
    talent_id: str | None = None
    project_id: str | None = None


class EmailDetail(BaseModel):
    id: str
    gmail_message_id: str
    subject: str
    from_address: str
    label: str
    email_type: str
    status: str
    received_at: str
    body_text: str


class EmailReclassifyRequest(BaseModel):
    """判別不能メールを人材 / 案件へ手動振り分けする。"""

    email_type: Literal["talent", "project"]


class EmailReclassifyResponse(BaseModel):
    id: str
    email_type: str
    label: str
    status: str
    message: str


class TalentListItem(BaseModel):
    id: str
    display_name: str
    skills: list[str]
    desired_rate: int | None = None
    available_from: str | None = None
    work_style: str | None = None
    nearest_station: str | None = None
    is_foreign_national: bool | None = None
    commerce_flow: str | None = None
    summary: str | None = None
    status: str
    email_id: str
    created_at: str
    affiliation: str | None = None
    age: int | None = None
    source_company_name: str | None = None
    introducer_company_id: str | None = None
    proposed_project_count: int = 0
    proposed_no_reply_count: int = 0
    proposed_ok_count: int = 0
    proposed_ng_count: int = 0
    has_skill_sheet: bool = False
    email_received_at: str | None = None


class TalentSkillSheetItem(BaseModel):
    id: str
    filename: str
    content_type: str | None = None
    size_bytes: int | None = None
    source_type: str
    access_status: str
    web_view_link: str | None = None
    error_message: str | None = None
    experience_extract_status: str | None = None


class TalentDetail(TalentListItem):
    gender: str | None = None
    experience_years: int | None = None
    proposal_cc_emails: list[str] = []
    email_subject: str | None = None
    email_from: str | None = None
    email_label: str | None = None
    skill_sheets: list[TalentSkillSheetItem] = []


class ProjectListItem(BaseModel):
    id: str
    title: str
    project_code: str | None = None
    required_skills: list[str]
    rate_min: int | None = None
    rate_max: int | None = None
    location: str | None = None
    work_style: str | None = None
    working_hours: str | None = None
    start_date: str | None = None
    foreign_nationality_ng: bool | None = None
    commerce_flow_limit: str | None = None
    settlement_range: str | None = None
    interview_count: int | None = None
    headcount: int | None = None
    summary: str | None = None
    status: str
    email_id: str
    created_at: str
    distributor_company_id: str | None = None
    distributor_company_name: str | None = None
    proposed_talent_count: int = 0
    proposed_no_reply_count: int = 0
    proposed_ok_count: int = 0
    proposed_ng_count: int = 0
    email_received_at: str | None = None


class ProjectDetail(ProjectListItem):
    proposal_cc_emails: list[str] = []
    email_subject: str | None = None
    email_from: str | None = None
    email_label: str | None = None


class DashboardDailyPoint(BaseModel):
    date: str
    emails_total: int = 0
    emails_project: int = 0
    emails_talent: int = 0
    # 供給内訳（葉。合計 = emails_total）
    project_unproposed: int = 0  # 案件メール・人材未提案
    project_proposed: int = 0  # 案件メール・人材提案済み
    talent_unproposed: int = 0  # 人材メール・案件未提案
    talent_proposed: int = 0  # 人材メール・案件提案済み
    emails_other: int = 0  # 振り分け不可など
    proposals_project_offer: int = 0  # 案件提案（talent_proposal）
    proposals_talent_offer: int = 0  # 人材提案（project_proposal）


class DashboardCompanyIngest(BaseModel):
    company_id: str | None = None
    company_name: str
    emails_project: int = 0
    emails_talent: int = 0
    emails_total: int = 0


class DashboardFunnelConstraintLoss(BaseModel):
    foreign_nationality: int = 0
    commerce_flow: int = 0
    other_zero: int = 0
    total: int = 0


class DashboardFunnel(BaseModel):
    ingested: int = 0
    proposable: int = 0
    proposed: int = 0
    replied: int = 0
    ok: int = 0
    constraint_loss: DashboardFunnelConstraintLoss = DashboardFunnelConstraintLoss()


class DashboardScoreBandOk(BaseModel):
    score_band: str
    proposed_count: int = 0
    ok_count: int = 0
    ok_rate: float = 0.0


class DashboardResponse(BaseModel):
    talent_count: int
    project_count: int
    pending_email_count: int
    # 送信済み提案メール（全期間）
    talent_proposal_sent_count: int = 0  # 案件提案（talent_proposal）
    project_proposal_sent_count: int = 0  # 要員提案（project_proposal）
    # ルール採点が一度もない（matches 未登場）の active 人材 / open 案件
    unscored_talent_count: int = 0
    unscored_project_count: int = 0
    period_range: str = "month"
    period_days: int = 30
    period_start: str
    period_end: str
    can_go_forward: bool = False
    emails_total: int = 0
    emails_project: int = 0
    emails_talent: int = 0
    project_unproposed: int = 0
    project_proposed: int = 0
    talent_unproposed: int = 0
    talent_proposed: int = 0
    emails_other: int = 0
    proposals_project_offer: int = 0
    proposals_talent_offer: int = 0
    project_proposed_rate: float = 0.0
    talent_proposed_rate: float = 0.0
    daily: list[DashboardDailyPoint] = []
    by_company: list[DashboardCompanyIngest] = []
    funnel: DashboardFunnel = DashboardFunnel()
    ok_by_score_band: list[DashboardScoreBandOk] = []


class DashboardSortQueueResponse(BaseModel):
    """振り分け対象ラベル（gmail_sort_source_label）の Gmail 件数。"""

    label: str
    count: int | None = None
    capped: bool = False
    cached: bool = False
    fetched_at: str | None = None
    expires_at: str | None = None
    cache_ttl_seconds: int = 900
    error_code: str | None = None
    error_message: str | None = None
