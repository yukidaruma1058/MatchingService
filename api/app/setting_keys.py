"""system_settings のキー名とデフォルト値。"""

from __future__ import annotations

from typing import Any

SETTING_KEY_INGEST_RETENTION_DAYS = "ingest_data_retention_days"
SETTING_KEY_GMAIL_SORT_LABEL_TALENT = "gmail_sort_label_talent"
SETTING_KEY_GMAIL_SORT_LABEL_PROJECT = "gmail_sort_label_project"
SETTING_KEY_GMAIL_OAUTH_CLIENT_ID = "gmail_oauth_client_id"
SETTING_KEY_GMAIL_OAUTH_CLIENT_SECRET = "gmail_oauth_client_secret"
SETTING_KEY_GMAIL_OAUTH_PROJECT_ID = "gmail_oauth_project_id"
SETTING_KEY_AI_ASSIST_ENABLED = "ai_assist_enabled"
SETTING_KEY_AI_JUDGEMENT_TOP_N = "ai_judgement_top_n"
SETTING_KEY_DASHBOARD_RULE_SCORE_MIN = "dashboard_rule_score_min"
SETTING_KEY_OWN_COMPANY_NAME = "own_company_name"
SETTING_KEY_APPLY_FROM_ADDRESS = "apply_from_address"
SETTING_KEY_REPLY_KEYWORDS_OK = "reply_keywords_ok"
SETTING_KEY_REPLY_KEYWORDS_NG = "reply_keywords_ng"
SETTING_KEY_TEMPLATE_PROJECT_PROPOSE = "outreach_template_project_propose"
SETTING_KEY_TEMPLATE_TALENT_PROPOSE = "outreach_template_talent_propose"
SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP = "talent_propose_rate_markup_man_yen"
SETTING_KEY_SKILL_SHEET_DRIVE_FOLDER_ID = "skill_sheet_drive_folder_id"

GMAIL_INGEST_LABEL_SETTING_KEYS = (
    SETTING_KEY_GMAIL_SORT_LABEL_TALENT,
    SETTING_KEY_GMAIL_SORT_LABEL_PROJECT,
)

DEFAULT_SETTINGS: dict[str, Any] = {
    SETTING_KEY_INGEST_RETENTION_DAYS: 0,
    SETTING_KEY_GMAIL_SORT_LABEL_TALENT: "SES人材紹介",
    SETTING_KEY_GMAIL_SORT_LABEL_PROJECT: "SES案件配信",
    SETTING_KEY_AI_ASSIST_ENABLED: False,
    SETTING_KEY_AI_JUDGEMENT_TOP_N: 5,
    SETTING_KEY_DASHBOARD_RULE_SCORE_MIN: 50,
    SETTING_KEY_OWN_COMPANY_NAME: "",
    SETTING_KEY_APPLY_FROM_ADDRESS: "",
    SETTING_KEY_REPLY_KEYWORDS_OK: "よろしくお願いします\n前向き\n候補として\nご提案ください",
    SETTING_KEY_REPLY_KEYWORDS_NG: "見送り\n他決\n辞退\n今回は結構",
    SETTING_KEY_TEMPLATE_PROJECT_PROPOSE: (
        "{{company_name}}\n"
        "{{contact_name}} 様ご関係各位\n"
        "\n"
        "お世話になっております。マッチング結果に基づき、以下の案件をご提案いたします。\n"
        "\n"
        "{{items}}"
        "ご検討のほど、よろしくお願いいたします。\n"
    ),
    SETTING_KEY_TEMPLATE_TALENT_PROPOSE: (
        "{{company_name}}\n"
        "{{contact_name}} 様\n"
        "\n"
        "お世話になっております。以下の要員をご提案いたします。\n"
        "\n"
        "■ 案件: {{project_title}}\n"
        "\n"
        "{{items}}"
        "ご検討のほど、よろしくお願いいたします。\n"
    ),
    SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP: 0,
    SETTING_KEY_SKILL_SHEET_DRIVE_FOLDER_ID: "",
}
