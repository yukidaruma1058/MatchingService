"""バッチ共通の環境変数・設定値読込。

Pydantic Settings で ``.env`` と環境変数から値を取得する。
Gmail 取込ラベル設定もここで一元管理する。
"""

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

    # --- BAT-002: Gmail 取込ラベル ---
    # system_settings テーブルに値があればそちらを優先（label_settings.load_gmail_label_settings 参照）
    gmail_sort_label_talent: str = "SES人材紹介"
    gmail_sort_label_project: str = "SES案件配信"
    gmail_processed_label_talent: str = "SES人材紹介（処理済み）"
    gmail_processed_label_project: str = "SES案件配信（処理済み）"

    # 旧環境変数名との互換
    gmail_label_talent: str = "SES人材紹介"
    gmail_label_project: str = "SES案件配信"

    # --- AI ---
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    cursor_api_key: str = ""  # Cursor SDK / エージェント用（CURSOR_API_KEY）
    anthropic_api_key: str = ""  # Claude API（ANTHROPIC_API_KEY）
    anthropic_model: str = "claude-haiku-4-5-20251001"
    # BAT-002 要約 / BAT-004 AI判定の LLM 並列度（1=直列、推奨 3〜4、上限 8）
    # 実効値は API レート制限次第。429 が出る場合は下げる。
    ai_concurrency: int = 3

    # --- Google Routes（BAT-003 通勤） ---
    google_maps_api_key: str = ""
    google_routes_monthly_warn: int = 8000
    google_routes_monthly_limit: int = 10000

    # --- バッチ起動 ---
    batch_job: str = "pipeline"                          # デフォルト実行ジョブ
    batch_log_path: str = "log/batch.log"                # バッチ JSON ログの出力先
    ingest_data_retention_days: int = 0                  # 取込データ保持日数（0=削除しない）


settings = Settings()
