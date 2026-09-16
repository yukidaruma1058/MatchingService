"""API サーバーの環境変数・設定値読込。"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """API 実行に必要な設定値の集合。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://matching:matching@db:5432/matching"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    cursor_api_key: str = ""  # Cursor SDK / エージェント用（CURSOR_API_KEY）
    anthropic_api_key: str = ""  # Claude API（ANTHROPIC_API_KEY）
    anthropic_model: str = "claude-haiku-4-5-20251001"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    google_maps_api_key: str = ""
    google_routes_monthly_warn: int = 8000
    google_routes_monthly_limit: int = 10000

    gmail_credentials_path: Path = Path("/secrets/credentials.json")
    gmail_token_path: Path = Path("/secrets/token.json")
    # 空の場合はリクエスト / API_PUBLIC_BASE_URL / localhost から自動生成
    gmail_oauth_redirect_uri: str = ""
    web_settings_url: str = ""
    api_public_base_url: str = ""
    web_public_base_url: str = ""
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_oauth_project_id: str = "matching-service"


settings = Settings()
