"""batch/app/purge_ingest.py を API から呼び出す。"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from app.batch_runner import BATCH_ROOT


def purge_all_ingest_data_via_batch(*, skip_drive: bool = False) -> dict[str, int]:
    batch_root = Path(os.environ.get("BATCH_ROOT", str(BATCH_ROOT)))
    path = str(batch_root)
    if path not in sys.path:
        sys.path.insert(0, path)
    from app.purge_ingest import purge_all_ingest_data as _purge

    return _purge(skip_drive=skip_drive)


def purge_summary_message(result: dict[str, Any]) -> str:
    return (
        f"取込データを削除しました（メール {result['deleted_emails']} 件、"
        f"人材 {result['deleted_talents']} 件、案件 {result['deleted_projects']} 件）"
    )
