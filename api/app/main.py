"""MatchingService REST API（FastAPI）。

画面（Next.js）から呼び出される HTTP エンドポイントを提供する。
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import create_session_factory, ensure_schema, load_settings
from app.gmail_credentials import ensure_gmail_credentials_file
from app.routers.batches import router as batches_router
from app.routers.companies import router as companies_router
from app.routers.contacts import router as contacts_router
from app.routers.dashboard import router as dashboard_router
from app.routers.emails import router as emails_router
from app.routers.gmail_oauth import router as gmail_oauth_router
from app.routers.match_runs import router as match_runs_router
from app.routers.outreach import router as outreach_router
from app.routers.projects import router as projects_router
from app.routers.settings import router as settings_router
from app.routers.skills import router as skills_router
from app.routers.talents import router as talents_router

app = FastAPI(title="MatchingService API", version="0.1.0")

# 開発時にフロント（localhost:3000）から API へアクセスできるよう CORS を許可。
# allow_credentials=True と allow_origins=["*"] の併用はブラウザ仕様上NGのため credentials は付けない。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(settings_router)
app.include_router(skills_router)
app.include_router(gmail_oauth_router)
app.include_router(batches_router)
app.include_router(dashboard_router)
app.include_router(emails_router)
app.include_router(companies_router)
app.include_router(contacts_router)
app.include_router(talents_router)
app.include_router(projects_router)
app.include_router(match_runs_router)
app.include_router(outreach_router)


@app.on_event("startup")
def ensure_gmail_oauth_files() -> None:
    """起動時に credentials.json を生成する（環境変数または DB 設定がある場合）。"""
    try:
        _session_factory, _engine = create_session_factory()
        ensure_schema(_engine)
        with _session_factory() as session:
            ensure_gmail_credentials_file(load_settings(session))
    except Exception:
        ensure_gmail_credentials_file()


@app.get("/health")
def health() -> dict[str, str]:
    """コンテナ・ロードバランサ向けの生存確認エンドポイント。"""
    return {"status": "ok", "service": "api"}


@app.get("/")
def root() -> dict[str, str]:
    """API の基本情報と Swagger ドキュメントへの導線。"""
    return {
        "message": "MatchingService API",
        "docs": "/docs",
        "openai_model": settings.openai_model,
    }
