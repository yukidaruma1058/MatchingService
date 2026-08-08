"""マッチ実行（match_runs）参照ヘルパー。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import MatchRun


def latest_completed_match_run(session: Session) -> MatchRun | None:
    """画面・集計で使う最新の完了済み match_run。

    status=running の空 run が最新でも、採点結果が消えたように見えないようにする。
    """
    return session.scalar(
        select(MatchRun)
        .where(MatchRun.status == "completed")
        .order_by(MatchRun.started_at.desc())
        .limit(1)
    )
