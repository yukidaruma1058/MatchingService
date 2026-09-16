"""ダッシュボード高スコア一覧の提案済み表示。提案メールは変更しない。"""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DashboardHiddenMatch

_DISPLAY_PROPOSED = "proposed"
_DISPLAY_UNPROPOSED = "unproposed"


def set_dashboard_pair_proposed(
    session: Session,
    talent_id: UUID,
    project_id: UUID,
    *,
    proposed: bool = True,
) -> None:
    display_as = _DISPLAY_PROPOSED if proposed else _DISPLAY_UNPROPOSED
    existing = session.scalar(
        select(DashboardHiddenMatch).where(
            DashboardHiddenMatch.talent_id == talent_id,
            DashboardHiddenMatch.project_id == project_id,
        )
    )
    if existing is None:
        session.add(
            DashboardHiddenMatch(
                id=uuid4(),
                talent_id=talent_id,
                project_id=project_id,
                display_as=display_as,
            )
        )
        return
    existing.display_as = display_as
