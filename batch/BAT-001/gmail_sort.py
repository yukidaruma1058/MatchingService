"""BAT-001: メール振り分けバッチ。

処理概要:
  1. ``gmail_sort_source_label`` 付きの未振り分けメールを Gmail から取得
  2. 件名を優先してキーワード照合し、曖昧な場合のみ本文先頭も参照して要員/案件/要確認に分類
  3. Gmail ラベルを付け替え（ソースラベルを除去）
  4. ``emails`` テーブルへ振り分け結果を upsert

起動: ``python -m app.main sort``（画面・API からの手動実行）
"""

from __future__ import annotations

import time
import uuid
import logging
from dataclasses import dataclass

from classifier import classify_email, parse_keywords
from db import SortSettings, load_all_settings, load_sort_settings, upsert_sorted_email

from app.ai_concurrency import map_parallel, resolve_ai_concurrency
from app.config import Settings, settings
from app.gmail_credentials import ensure_gmail_credentials_file
from app.db_bootstrap import create_session_factory, ensure_schema
from app.gmail_client import GmailClient, GmailConfigError, GmailMessage
from app.label_settings import load_ingest_settings, load_sort_settings
from app.logging_util import get_batch_logger, log_error_event, log_event
from app.proposal_cc import resolve_proposal_cc


@dataclass
class SortBatchStats:
    """1 回のバッチ実行結果の集計値。"""

    scanned: int = 0        # 対象ラベル付きメールの走査件数
    sorted_count: int = 0   # 振り分け成功件数
    skipped: int = 0        # 既に振り分け済みでスキップした件数
    failed: int = 0         # 取得・ラベル更新などで失敗した件数


class GmailSortBatch:
    """BAT-001 メール振り分けバッチの実行クラス。"""

    function_id = "BAT-001"

    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or settings
        self.logger = get_batch_logger()
        self.job_id = f"job_{uuid.uuid4().hex[:12]}"
        self.fetch_concurrency = resolve_ai_concurrency(getattr(self.cfg, "ai_concurrency", 3))

    def run(self) -> SortBatchStats:
        """振り分けバッチを 1 回実行する。"""
        started = time.perf_counter()
        stats = SortBatchStats()

        log_event(
            self.logger,
            logging.INFO,
            event="gmail_sort.started",
            message="Gmail sort batch started",
            operation="メール振り分け開始",
            method_name="run",
            job_id=self.job_id,
        )

        # --- 準備: DB 接続と振り分け設定の読込 ---
        session_factory, engine = create_session_factory(self.cfg.database_url)
        ensure_schema(engine)

        with session_factory() as session:
            sort_settings = load_sort_settings(session, self.cfg)
            ingest_settings = load_ingest_settings(session, self.cfg)
            db_settings = load_all_settings(session)

        talent_keywords = parse_keywords(sort_settings.talent_keywords)
        project_keywords = parse_keywords(sort_settings.project_keywords)

        log_event(
            self.logger,
            logging.INFO,
            event="gmail_sort.settings_loaded",
            message="Sort settings loaded",
            operation="振り分け設定読込",
            method_name="run",
            job_id=self.job_id,
            extra={
                "source_label": sort_settings.source_label,
                "talent_label": sort_settings.talent_label,
                "project_label": sort_settings.project_label,
                "unknown_label": sort_settings.unknown_label,
                "processed_talent_label": ingest_settings.processed_talent_label,
                "processed_project_label": ingest_settings.processed_project_label,
                "talent_keywords": talent_keywords,
                "project_keywords": project_keywords,
            },
        )

        # --- Gmail 認証 ---
        if not ensure_gmail_credentials_file(self.cfg, db_settings):
            log_error_event(
                self.logger,
                event="batch.job.failed",
                error_code="ERR-0018",
                detail="Gmail credentials file not found",
                operation="Gmail認証準備",
                method_name="run",
                job_id=self.job_id,
            )
            raise GmailConfigError("ERR-0018", "Gmail credentials file not found")

        client = GmailClient(self.cfg.gmail_credentials_path, self.cfg.gmail_token_path)
        try:
            client.connect()
        except GmailConfigError as exc:
            log_error_event(
                self.logger,
                event="batch.job.failed",
                error_code=exc.error_code,
                detail=exc.message,
                operation="Gmail認証",
                method_name="connect",
                job_id=self.job_id,
            )
            raise

        required_labels = [
            sort_settings.source_label,
            sort_settings.talent_label,
            sort_settings.project_label,
            sort_settings.unknown_label,
            ingest_settings.processed_talent_label,
            ingest_settings.processed_project_label,
        ]
        destination_labels = [
            sort_settings.talent_label,
            sort_settings.project_label,
            sort_settings.unknown_label,
            ingest_settings.processed_talent_label,
            ingest_settings.processed_project_label,
        ]
        try:
            # 人材用 / 案件用 / 要確認 / 処理済み などが無ければ自動作成
            client.ensure_labels(required_labels)
        except GmailConfigError as exc:
            log_error_event(
                self.logger,
                event="batch.job.failed",
                error_code=exc.error_code,
                detail=exc.message,
                operation="Gmailラベル準備",
                method_name="ensure_labels",
                job_id=self.job_id,
            )
            raise

        # --- 対象メール一覧の取得 ---
        try:
            message_ids = client.list_message_ids_with_label(sort_settings.source_label)
        except GmailConfigError as exc:
            log_error_event(
                self.logger,
                event="batch.job.failed",
                error_code=exc.error_code,
                detail=exc.message,
                operation="Gmailメール一覧取得",
                method_name="list_message_ids_with_label",
                job_id=self.job_id,
            )
            raise

        log_event(
            self.logger,
            logging.INFO,
            event="gmail_sort.messages_loaded",
            message="Gmail messages loaded for sorting",
            operation="Gmailメール一覧取得",
            method_name="list_message_ids_with_label",
            job_id=self.job_id,
            extra={
                "source_label": sort_settings.source_label,
                "count": len(message_ids),
            },
        )

        # --- メールごとの振り分け処理（fetch は軽度並列、以降は直列） ---
        fetch_results = map_parallel(
            message_ids,
            lambda message_id: self._fetch_one(client, message_id),
            concurrency=self.fetch_concurrency,
        )
        for message_id, message, fetch_error in fetch_results:
            stats.scanned += 1
            if fetch_error is not None:
                stats.failed += 1
                if isinstance(fetch_error, GmailConfigError):
                    log_error_event(
                        self.logger,
                        event="gmail_sort.message_failed",
                        error_code=fetch_error.error_code,
                        detail=fetch_error.message,
                        operation="Gmail本文取得",
                        method_name="fetch_message",
                        job_id=self.job_id,
                        gmail_message_id=message_id,
                    )
                else:
                    log_error_event(
                        self.logger,
                        event="gmail_sort.message_failed",
                        error_code="ERR-0030",
                        detail=str(fetch_error),
                        operation="Gmail本文取得",
                        method_name="fetch_message",
                        job_id=self.job_id,
                        gmail_message_id=message_id,
                    )
                continue
            assert message is not None

            # 振り分け先ラベルが既に付いているメールはスキップ
            if client.has_any_label(message.label_ids, destination_labels):
                stats.skipped += 1
                continue

            # 件名優先でキーワード判定（曖昧なときだけ本文先頭も参照）
            body_preview = (message.body_text or message.body_html or "")[: self.cfg.sort_body_preview_chars]
            decision = classify_email(
                message.subject,
                body_preview,
                talent_keywords=talent_keywords,
                project_keywords=project_keywords,
                talent_label=sort_settings.talent_label,
                project_label=sort_settings.project_label,
                unknown_label=sort_settings.unknown_label,
            )

            # Gmail ラベル付け替え: 判定ラベルを付与し、ソースラベルを除去
            try:
                client.relabel_message(
                    message_id,
                    add_label_names=[decision.target_label],
                    remove_label_names=[sort_settings.source_label],
                )
            except GmailConfigError as exc:
                stats.failed += 1
                log_error_event(
                    self.logger,
                    event="gmail_sort.message_failed",
                    error_code=exc.error_code,
                    detail=exc.message,
                    operation="Gmailラベル更新",
                    method_name="relabel_message",
                    job_id=self.job_id,
                    gmail_message_id=message_id,
                )
                continue

            # DB へ振り分け結果を記録（既存レコードの本文・status は上書きしない）
            cc_resolved = resolve_proposal_cc(
                header_cc=list(message.cc_addresses),
                body_text=message.body_text or message.body_html,
                exclude=[message.from_address, *message.to_addresses],
            )
            with session_factory() as session:
                upsert_sorted_email(
                    session,
                    gmail_message_id=message.message_id,
                    thread_id=message.thread_id,
                    label=decision.target_label,
                    from_address=message.from_address,
                    subject=message.subject,
                    received_at=message.received_at,
                    body_text=message.body_text or None,
                    body_html=message.body_html or None,
                    email_type=decision.email_type,
                    cc_addresses=cc_resolved,
                )
                session.commit()

            stats.sorted_count += 1
            log_event(
                self.logger,
                logging.INFO,
                event="gmail_sort.message_sorted",
                message="Gmail message sorted",
                operation="メール振り分け",
                method_name="run",
                job_id=self.job_id,
                gmail_message_id=message_id,
                extra={
                    "email_type": decision.email_type,
                    "target_label": decision.target_label,
                    "subject": message.subject[:120],
                    "talent_hits": decision.talent_hits,
                    "project_hits": decision.project_hits,
                },
            )

        # --- 完了ログ ---
        duration_ms = int((time.perf_counter() - started) * 1000)
        log_event(
            self.logger,
            logging.INFO,
            event="gmail_sort.finished",
            message="Gmail sort batch finished",
            operation="メール振り分け完了",
            method_name="run",
            job_id=self.job_id,
            duration_ms=duration_ms,
            extra={
                "scanned": stats.scanned,
                "sorted": stats.sorted_count,
                "skipped": stats.skipped,
                "failed": stats.failed,
            },
        )
        return stats

    def _fetch_one(
        self,
        client: GmailClient,
        message_id: str,
    ) -> tuple[str, GmailMessage | None, BaseException | None]:
        try:
            return message_id, client.fetch_message(message_id), None
        except BaseException as exc:  # noqa: BLE001
            return message_id, None, exc


def run_sort_batch(cfg: Settings | None = None) -> SortBatchStats:
    """BAT-001 を実行する公開関数。テストや将来の API 連携から呼び出す。"""
    return GmailSortBatch(cfg).run()
