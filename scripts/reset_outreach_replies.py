"""登録済みの提案結果（outreach_replies）を削除し、返信待ち状態に戻す。"""

from __future__ import annotations

import sys
from pathlib import Path

_BATCH_ROOT = Path(__file__).resolve().parents[1] / "batch"
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from sqlalchemy import text

from app.config import settings
from app.db_bootstrap import create_session_factory, ensure_schema


def main() -> int:
    session_factory, engine = create_session_factory(settings.database_url)
    ensure_schema(engine)
    with session_factory() as session:
        before = session.execute(text("SELECT COUNT(*) FROM outreach_replies")).scalar_one()
        session.execute(text("DELETE FROM outreach_replies"))
        session.commit()
        after = session.execute(text("SELECT COUNT(*) FROM outreach_replies")).scalar_one()
    print(f"outreach_replies: before={before} deleted={before - after} after={after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
