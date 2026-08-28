"""batch_tmp ユーティリティのテスト。"""

from __future__ import annotations

import os
from pathlib import Path

from app.batch_tmp import resolve_batch_tmp_dir


def test_resolve_batch_tmp_dir_uses_batch_tmp_dir_env(tmp_path, monkeypatch):
    target = tmp_path / "custom-tmp"
    monkeypatch.setenv("BATCH_TMP_DIR", str(target))
    monkeypatch.delenv("BATCH_LOG_PATH", raising=False)

    resolved = resolve_batch_tmp_dir()

    assert resolved == target
    assert target.is_dir()


def test_resolve_batch_tmp_dir_defaults_to_log_parent_batch_tmp(tmp_path, monkeypatch):
    log_file = tmp_path / "logs" / "batch.log"
    log_file.parent.mkdir(parents=True)
    log_file.write_text("", encoding="utf-8")
    monkeypatch.delenv("BATCH_TMP_DIR", raising=False)
    monkeypatch.setenv("BATCH_LOG_PATH", str(log_file))

    resolved = resolve_batch_tmp_dir()

    assert resolved == (tmp_path / "logs" / "batch_tmp")
    assert resolved.is_dir()
