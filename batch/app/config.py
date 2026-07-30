"""バッチ共通の環境変数・設定値読込。

Pydantic Settings で ``.env`` と環境変数から値を取得する。
BAT-001 固有の Gmail 振り分け設定もここで一元管理する。
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """バッチ実行に必要な設定値の集合。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- DB 接続 ---
    database_url: str = "postgresql+psycopg://matching:matching@db:5432/matching"

    # --- Gmail OAuth（secrets ボリュームからマウント） ---
    gmail_credentials_path: str = "/secrets/credentials.json"
    gmail_token_path: str = "/secrets/token.json"
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_oauth_project_id: str = "matching-service"
    gmail_oauth_redirect_uri: str = "http://localhost:8000/api/gmail/oauth/callback"

    # --- BAT-001: メール振り分けラベル・キーワード ---
    # system_settings テーブルに値があればそちらを優先（db.load_sort_settings 参照）
    gmail_sort_source_label: str = "SES未振り分け"       # 振り分け対象の Gmail ラベル
    gmail_sort_label_talent: str = "SES人材紹介"         # 要員メールと判定したときの付与ラベル
    gmail_sort_label_project: str = "SES案件配信"        # 案件メールと判定したときの付与ラベル
    gmail_sort_unknown_label: str = "SES要確認"          # 判別不能時の付与ラベル
    gmail_sort_keywords_talent: str = Field(
        default="人材\n要員\nスキルシート\nご紹介"       # 要員判定用キーワード（改行 or | 区切り）
    )
    gmail_sort_keywords_project: str = Field(
        default="案件\n募集\n開発\nお問い合わせ"         # 案件判定用キーワード（改行 or | 区切り）
    )
    gmail_processed_label_talent: str = "SES人材紹介（処理済み）"
    gmail_processed_label_project: str = "SES案件配信（処理済み）"

    # 旧環境変数名との互換（gmail_sort_label_* 未設定時のフォールバック）
    gmail_label_talent: str = "SES人材紹介"
    gmail_label_project: str = "SES案件配信"

    # --- AI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    cursor_api_key: str = ""  # Cursor SDK / エージェント用（CURSOR_API_KEY）
    # BAT-002 要約 / BAT-004 AI判定の LLM 並列度（1=直列、推奨 2〜3、上限 4）
    ai_concurrency: int = 3

    # --- Google Routes（BAT-003 通勤） ---
    google_maps_api_key: str = ""
    google_routes_monthly_warn: int = 8000
    google_routes_monthly_limit: int = 10000

    # --- バッチ起動 ---
    batch_job: str = "sort"                              # デフォルト実行ジョブ（BAT-001）
    batch_log_path: str = "log/batch.log"                # バッチ JSON ログの出力先
    sort_body_preview_chars: int = 500                   # 振り分け判定に使う本文先頭文字数
    ingest_data_retention_days: int = 0                  # 取込データ保持日数（0=削除しない）


settings = Settings()
