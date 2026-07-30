"""FastAPI 共通依存関係。"""

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db import create_session_factory, ensure_schema

_session_factory, _engine = create_session_factory()
ensure_schema(_engine)


def get_db() -> Generator[Session, None, None]:
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()
