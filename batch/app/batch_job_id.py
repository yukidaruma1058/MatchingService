"""バッチ実行ごとの job_id を解決する（パイプライン進捗の相関用）。"""

from __future__ import annotations

import os
import uuid


def resolve_batch_job_id(*, default_prefix: str = "job") -> str:
    """環境変数 PIPELINE_JOB_ID があればそれを使い、なければ新規 ID を返す。"""
    pipeline_id = (os.environ.get("PIPELINE_JOB_ID") or "").strip()
    if pipeline_id:
        return pipeline_id
    batch_id = (os.environ.get("BATCH_JOB_ID") or "").strip()
    if batch_id:
        return batch_id
    return f"{default_prefix}_{uuid.uuid4().hex[:12]}"
