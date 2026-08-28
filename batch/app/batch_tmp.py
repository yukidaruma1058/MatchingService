"""バッチ実行時の一時ファイル用ディレクトリ。

/batch は Docker で read-only マウントされるため、PIPELINE 間連携ファイルなどは
BATCH_LOG_PATH と同じ書き込み可能ボリューム配下（既定: log/batch_tmp）に置く。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def resolve_batch_tmp_dir() -> Path:
    """書き込み可能なバッチ一時ディレクトリを返す（存在しなければ作成）。"""
    explicit = (os.environ.get("BATCH_TMP_DIR") or "").strip()
    if explicit:
        path = Path(explicit)
    else:
        log_path = (os.environ.get("BATCH_LOG_PATH") or "").strip()
        if log_path:
            path = Path(log_path).resolve().parent / "batch_tmp"
        else:
            path = Path(tempfile.gettempdir()) / "matching-batch"
    path.mkdir(parents=True, exist_ok=True)
    return path
