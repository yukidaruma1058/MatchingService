"""BAT-002: メール取込・AI要約バッチ。

処理概要:
  1. 人材用 / 案件用ラベル付きメールを Gmail から一括取得（ラベル並列）
  2. DB に既にある gmail_message_id はスキップ（failed は再試行）
  3. Gemini で 20 通パックを最大 10 本同時送信し、欠けた通は 1 分後に 20 通パック直列へフォールバック
  4. talents/projects へ保存する（Gmail ラベルは変更しない）
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from db import (
    already_ingested_gmail_ids,
    extract_email_address,
    get_email_by_gmail_id,
    link_company_contact_for_ingest,
    mark_email_status,
    resolve_ingest_contact_email,
    upsert_project_from_email,
    upsert_talent_from_email,
)
from summarizer import EmailExtractRequest, ExtractionResult, extract_email_fields_batch

from app.ai_concurrency import resolve_ai_concurrency
from app.batch_job_id import resolve_batch_job_id
from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.email_db import load_all_settings, upsert_sorted_email
from app.gemini_llm import resolve_gemini_batch_parallel
from app.gmail_client import GmailClient, GmailConfigError, GmailMessage
from app.gmail_credentials import ensure_gmail_credentials_file
from app.proposal_cc import resolve_proposal_cc
from app.label_settings import load_ingest_settings
from app.logging_util import get_batch_logger, log_error_event, log_event

# 1 ラベルあたりの取込上限（ページング）
_INGEST_LIST_MAX = 1000


@dataclass
class IngestBatchStats:
    scanned: int = 0
    ingested: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass
class _FetchedMail:
    message_id: str
    message: GmailMessage
    body: str
    proposal_cc: list[str]


@dataclass
class _ExtractedMail:
    fetched: _FetchedMail
    extraction: ExtractionResult | None = None
    error: BaseException | None = None


class GmailIngestBatch:
    """BAT-002 メール取込・要約バッチ。"""

    function_id = "BAT-002"

    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or settings
        self.logger = get_batch_logger()
        self.job_id = resolve_batch_job_id(default_prefix="job")
        self.ai_concurrency = resolve_ai_concurrency(getattr(self.cfg, "ai_concurrency", 3))
        self.ingest_scope = (os.environ.get("INGEST_SCOPE") or "all").strip().lower()
        self._stats_lock = threading.Lock()
        self._session_factory = None

    def run(self) -> IngestBatchStats:
        started = time.perf_counter()
        stats = IngestBatchStats()

        if self.ingest_scope == "skill_sheets":
            # スキルシート取込は AI 採点（BAT-004）側へ移管済み
            log_event(
                self.logger,
                logging.INFO,
                event="gmail_ingest.started",
                message="Skill sheet ingest skipped (deferred to AI judge)",
                operation="スキルシート取込",
                method_name="run",
                job_id=self.job_id,
                function_id=self.function_id,
                extra={"ingest_scope": "skill_sheets", "deferred_to": "ai_judge"},
            )
            return stats

        log_event(
            self.logger,
            logging.INFO,
            event="gmail_ingest.started",
            message="Gmail ingest batch started",
            operation="メール取込開始",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            extra={"ai_concurrency": self.ai_concurrency, "ingest_scope": self.ingest_scope},
        )

        session_factory, engine = create_session_factory(self.cfg.database_url)
        ensure_schema(engine)
        self._session_factory = session_factory

        with session_factory() as session:
            ingest_settings = load_ingest_settings(session, self.cfg)
            db_settings = load_all_settings(session)

        if not ensure_gmail_credentials_file(self.cfg, db_settings):
            log_error_event(
                self.logger,
                event="batch.job.failed",
                error_code="ERR-0018",
                detail="Gmail credentials file not found",
                operation="Gmail認証準備",
                method_name="run",
                job_id=self.job_id,
                function_id=self.function_id,
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
                function_id=self.function_id,
            )
            raise

        linked_gmail_address = client.get_authenticated_email()

        required_input_labels = [
            ingest_settings.talent_label,
            ingest_settings.project_label,
        ]
        if self.ingest_scope == "talent":
            required_input_labels = [ingest_settings.talent_label]
        elif self.ingest_scope == "project":
            required_input_labels = [ingest_settings.project_label]
        try:
            # 人材 / 案件ラベルは Gmail フィルタ側で作成済みであること
            client.require_labels(required_input_labels)
        except GmailConfigError as exc:
            log_error_event(
                self.logger,
                event="batch.job.failed",
                error_code=exc.error_code,
                detail=exc.message,
                operation="Gmailラベル準備",
                method_name="require_labels",
                job_id=self.job_id,
                function_id=self.function_id,
            )
            raise

        targets = (
            ("talent", ingest_settings.talent_label),
            ("project", ingest_settings.project_label),
        )
        if self.ingest_scope == "talent":
            targets = (targets[0],)
        elif self.ingest_scope == "project":
            targets = (targets[1],)

        batch_parallel_total = resolve_gemini_batch_parallel(
            getattr(self.cfg, "gemini_batch_parallel", 10)
        )
        # 人材と案件を同時に回すときは合計が上限を超えないよう半分ずつ
        batch_parallel = (
            max(1, batch_parallel_total // 2) if len(targets) > 1 else batch_parallel_total
        )

        log_event(
            self.logger,
            logging.INFO,
            event="gmail_ingest.ai_config",
            message="AI provider key status for BAT-002",
            operation="AI要約",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            extra={
                "has_cursor_key": bool(getattr(self.cfg, "cursor_api_key", "").strip()),
                "has_openai_key": bool(getattr(self.cfg, "openai_api_key", "").strip()),
                "has_anthropic_key": bool(getattr(self.cfg, "anthropic_api_key", "").strip()),
                "has_gemini_key": bool(getattr(self.cfg, "gemini_api_key", "").strip()),
                "openai_model": getattr(self.cfg, "openai_model", ""),
                "anthropic_model": getattr(self.cfg, "anthropic_model", ""),
                "gemini_model": getattr(self.cfg, "gemini_model", ""),
                "gemini_batch_size": getattr(self.cfg, "gemini_batch_size", 20),
                "gemini_batch_parallel": batch_parallel,
                "gemini_batch_parallel_total": batch_parallel_total,
                "gemini_batch_wave_interval_seconds": getattr(
                    self.cfg, "gemini_batch_wave_interval_seconds", 60
                ),
                "ai_concurrency": self.ai_concurrency,
            },
        )

        clients = [client]
        if len(targets) > 1:
            extra = GmailClient(self.cfg.gmail_credentials_path, self.cfg.gmail_token_path)
            extra.connect()
            clients.append(extra)

        extracted_by_label: list[tuple[str, str, list[_ExtractedMail]]] = []
        if len(targets) == 1:
            email_type, source_label = targets[0]
            extracted_by_label.append(
                (
                    email_type,
                    source_label,
                    self._fetch_and_extract_label(
                        client=clients[0],
                        stats=stats,
                        email_type=email_type,
                        source_label=source_label,
                        batch_parallel=batch_parallel,
                    ),
                )
            )
        else:
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(
                        self._fetch_and_extract_label,
                        client=clients[index],
                        stats=stats,
                        email_type=email_type,
                        source_label=source_label,
                        batch_parallel=batch_parallel,
                    )
                    for index, (email_type, source_label) in enumerate(targets)
                ]
                for index, future in enumerate(futures):
                    email_type, source_label = targets[index]
                    extracted_by_label.append(
                        (email_type, source_label, future.result())
                    )

        with session_factory() as session:
            for email_type, source_label, extracted in extracted_by_label:
                self._persist_extracted(
                    session=session,
                    stats=stats,
                    email_type=email_type,
                    source_label=source_label,
                    items=extracted,
                    linked_gmail_address=linked_gmail_address,
                )
            session.commit()

        duration_ms = int((time.perf_counter() - started) * 1000)
        log_event(
            self.logger,
            logging.INFO,
            event="gmail_ingest.finished",
            message="Gmail ingest batch finished",
            operation="メール取込完了",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            duration_ms=duration_ms,
            extra={
                "scanned": stats.scanned,
                "ingested": stats.ingested,
                "skipped": stats.skipped,
                "failed": stats.failed,
                "ai_concurrency": self.ai_concurrency,
                "ingest_scope": self.ingest_scope,
            },
        )

        return stats

    def _fetch_and_extract_label(
        self,
        *,
        client: GmailClient,
        stats: IngestBatchStats,
        email_type: str,
        source_label: str,
        batch_parallel: int = 10,
    ) -> list[_ExtractedMail]:
        try:
            message_ids = client.list_message_ids_with_label(
                source_label, max_results=_INGEST_LIST_MAX
            )
        except GmailConfigError as exc:
            log_error_event(
                self.logger,
                event="gmail_ingest.message_failed",
                error_code=exc.error_code,
                detail=exc.message,
                operation="Gmailメール一覧取得",
                method_name="list_message_ids_with_label",
                job_id=self.job_id,
                function_id=self.function_id,
                module_name="BAT-002.gmail_ingest",
                extra={"label_type": email_type, "source_label": source_label},
            )
            with self._stats_lock:
                stats.failed += 1
            return []

        already: set[str] = set()
        if self._session_factory is not None and message_ids:
            with self._session_factory() as session:
                already = already_ingested_gmail_ids(session, message_ids, retry_failed=True)
                session.commit()

        pending_ids = [mid for mid in message_ids if mid not in already]
        skipped_count = len(message_ids) - len(pending_ids)
        if skipped_count:
            with self._stats_lock:
                stats.skipped += skipped_count
                stats.scanned += skipped_count

        fetch_results = client.fetch_messages(pending_ids, chunk_size=20)
        fetched: list[_FetchedMail] = []
        for message_id, message, fetch_error in fetch_results:
            with self._stats_lock:
                stats.scanned += 1
            if fetch_error is not None:
                with self._stats_lock:
                    stats.failed += 1
                if isinstance(fetch_error, GmailConfigError):
                    self._log_message_failed(message_id, fetch_error, "Gmail本文取得", "fetch_messages")
                else:
                    log_error_event(
                        self.logger,
                        event="gmail_ingest.message_failed",
                        error_code="ERR-0030",
                        detail=str(fetch_error),
                        operation="Gmail本文取得",
                        method_name="fetch_messages",
                        job_id=self.job_id,
                        function_id=self.function_id,
                        module_name="BAT-002.gmail_ingest",
                        gmail_message_id=message_id,
                    )
                continue
            assert message is not None

            body = message.body_text or message.body_html
            proposal_cc = resolve_proposal_cc(
                header_cc=list(message.cc_addresses),
                body_text=message.body_text or message.body_html,
                exclude=[message.from_address, *message.to_addresses],
            )
            fetched.append(
                _FetchedMail(
                    message_id=message_id,
                    message=message,
                    body=body,
                    proposal_cc=proposal_cc,
                )
            )

        log_event(
            self.logger,
            logging.INFO,
            event="gmail_ingest.label_targets",
            message="Gmail label targets loaded",
            operation="メール取込対象",
            method_name="_fetch_and_extract_label",
            job_id=self.job_id,
            function_id=self.function_id,
            extra={
                "label_type": email_type,
                "source_label": source_label,
                "listed": len(message_ids),
                "targets": len(fetched),
                "skipped_already_ingested": skipped_count,
            },
        )
        log_event(
            self.logger,
            logging.INFO,
            event="gmail_ingest.fetch_progress",
            message="Gmail fetch progress",
            operation="Gmail本文取得",
            method_name="_fetch_and_extract_label",
            job_id=self.job_id,
            function_id=self.function_id,
            extra={
                "label_type": email_type,
                "source_label": source_label,
                "done": len(fetched),
                "total": len(fetched),
                "listed": len(message_ids),
            },
        )

        requests = [
            EmailExtractRequest(
                item_id=item.message_id,
                subject=item.message.subject,
                body=item.body,
                from_header=item.message.from_header or item.message.from_address,
            )
            for item in fetched
        ]

        def _log_ai_progress(done: int, total: int) -> None:
            log_event(
                self.logger,
                logging.INFO,
                event="gmail_ingest.ai_progress",
                message="AI extraction progress",
                operation="AI要約",
                method_name="_fetch_and_extract_label",
                job_id=self.job_id,
                function_id=self.function_id,
                extra={
                    "label_type": email_type,
                    "source_label": source_label,
                    "done": done,
                    "total": total,
                },
            )

        by_id = extract_email_fields_batch(
            email_type,  # type: ignore[arg-type]
            requests,
            self.cfg,  # type: ignore[arg-type]
            batch_size=getattr(self.cfg, "gemini_batch_size", 20),
            batch_parallel=batch_parallel,
            on_progress=_log_ai_progress,
        )
        return [
            _ExtractedMail(fetched=item, extraction=by_id.get(item.message_id))
            for item in fetched
        ]

    def _persist_extracted(
        self,
        *,
        session,
        stats: IngestBatchStats,
        email_type: str,
        source_label: str,
        items: list[_ExtractedMail],
        linked_gmail_address: str | None = None,
    ) -> list[str]:
        success_ids: list[str] = []
        for item in items:
            message = item.fetched.message
            message_id = item.fetched.message_id
            body = item.fetched.body
            proposal_cc = item.fetched.proposal_cc

            if item.error is not None:
                with self._stats_lock:
                    stats.failed += 1
                log_error_event(
                    self.logger,
                    event="gmail_ingest.message_failed",
                    error_code="ERR-0025",
                    detail=str(item.error),
                    operation="AI要約",
                    method_name="extract_email_fields",
                    job_id=self.job_id,
                    function_id=self.function_id,
                    module_name="BAT-002.gmail_ingest",
                    gmail_message_id=message_id,
                )
                continue

            extraction = item.extraction
            if extraction is None or not extraction.data:
                with self._stats_lock:
                    stats.failed += 1
                try:
                    with session.begin_nested():
                        upsert_sorted_email(
                            session,
                            gmail_message_id=message.message_id,
                            thread_id=message.thread_id,
                            label=source_label,
                            from_address=message.from_address,
                            subject=message.subject,
                            received_at=message.received_at,
                            body_text=body,
                            body_html=message.body_html or None,
                            email_type=email_type,
                            cc_addresses=proposal_cc,
                        )
                        mark_email_status(
                            session,
                            gmail_message_id=message.message_id,
                            status="failed",
                            body_text=body,
                            body_html=message.body_html or None,
                        )
                except Exception as exc:
                    log_error_event(
                        self.logger,
                        event="gmail_ingest.message_failed",
                        error_code="ERR-0015",
                        detail=str(exc),
                        operation="DB保存",
                        method_name="upsert",
                        job_id=self.job_id,
                        function_id=self.function_id,
                        module_name="BAT-002.gmail_ingest",
                        gmail_message_id=message_id,
                    )
                log_error_event(
                    self.logger,
                    event="gmail_ingest.message_failed",
                    error_code=(extraction.error_code if extraction else None) or "ERR-0025",
                    detail="AI extraction returned empty payload",
                    operation="AI要約",
                    method_name="extract_email_fields",
                    job_id=self.job_id,
                    function_id=self.function_id,
                    module_name="BAT-002.gmail_ingest",
                    gmail_message_id=message_id,
                )
                continue

            entity_status = "inactive" if extraction.needs_review and email_type == "talent" else (
                "closed" if extraction.needs_review and email_type == "project" else (
                    "active" if email_type == "talent" else "open"
                )
            )
            email_status = "needs_review" if extraction.needs_review else "summarized"

            try:
                with session.begin_nested():
                    upsert_sorted_email(
                        session,
                        gmail_message_id=message.message_id,
                        thread_id=message.thread_id,
                        label=source_label,
                        from_address=message.from_address,
                        subject=message.subject,
                        received_at=message.received_at,
                        body_text=body,
                        body_html=message.body_html or None,
                        email_type=email_type,
                        cc_addresses=proposal_cc,
                    )
                    session.flush()
                    email_row = get_email_by_gmail_id(session, message.message_id)
                    if email_row is None:
                        raise RuntimeError("email row missing after upsert")

                    entity_data = dict(extraction.data)
                    entity_data["proposal_cc_emails"] = proposal_cc

                    contact_email = resolve_ingest_contact_email(
                        from_address=message.from_address
                        or extract_email_address(message.from_header),
                        reply_to_address=message.reply_to_address
                        or extract_email_address(message.reply_to_header),
                        linked_gmail_address=linked_gmail_address,
                    ) or message.from_address
                    party_header = message.from_header
                    if (
                        message.reply_to_address
                        and contact_email
                        and contact_email.lower() == message.reply_to_address.lower()
                        and message.reply_to_header
                    ):
                        party_header = message.reply_to_header

                    if email_type == "talent":
                        entity_id = upsert_talent_from_email(
                            session,
                            email_id=email_row.id,
                            data=entity_data,
                            status="active" if not extraction.needs_review else "inactive",
                        )
                        link_company_contact_for_ingest(
                            session,
                            email_id=email_row.id,
                            email_type="talent",
                            company_name=extraction.data.get("source_company_name"),
                            contact_name=extraction.data.get("contact_name"),
                            contact_email=contact_email,
                            from_header=party_header,
                            talent_id=entity_id,
                        )
                    else:
                        entity_id = upsert_project_from_email(
                            session,
                            email_id=email_row.id,
                            data=entity_data,
                            status="open" if not extraction.needs_review else "closed",
                        )
                        link_company_contact_for_ingest(
                            session,
                            email_id=email_row.id,
                            email_type="project",
                            company_name=extraction.data.get("source_company_name"),
                            contact_name=extraction.data.get("contact_name"),
                            contact_email=contact_email,
                            from_header=party_header,
                            project_id=entity_id,
                        )

                    mark_email_status(
                        session,
                        gmail_message_id=message.message_id,
                        status=email_status,
                        label=source_label,
                        body_text=body,
                        body_html=message.body_html or None,
                    )
            except Exception as exc:
                with self._stats_lock:
                    stats.failed += 1
                log_error_event(
                    self.logger,
                    event="gmail_ingest.message_failed",
                    error_code="ERR-0015",
                    detail=str(exc),
                    operation="DB保存",
                    method_name="upsert",
                    job_id=self.job_id,
                    function_id=self.function_id,
                    module_name="BAT-002.gmail_ingest",
                    gmail_message_id=message_id,
                )
                continue

            success_ids.append(message_id)
            with self._stats_lock:
                stats.ingested += 1
            if extraction.provider == "heuristic":
                log_event(
                    self.logger,
                    logging.WARNING,
                    event="gmail_ingest.ai_fallback_heuristic",
                    message="AI keys missing or AI failed; used rule-based extraction",
                    operation="AI要約",
                    method_name="extract_email_fields",
                    job_id=self.job_id,
                    function_id=self.function_id,
                    gmail_message_id=message_id,
                    extra={
                        "has_cursor_key": bool(getattr(self.cfg, "cursor_api_key", "").strip()),
                        "has_openai_key": bool(getattr(self.cfg, "openai_api_key", "").strip()),
                    },
                )
            log_event(
                self.logger,
                logging.INFO,
                event="gmail_ingest.message_ingested",
                message="Gmail message ingested",
                operation="メール取込",
                method_name="_persist_extracted",
                job_id=self.job_id,
                function_id=self.function_id,
                extra={
                    "gmail_message_id": message.message_id,
                    "thread_id": message.thread_id,
                    "email_type": email_type,
                    "label_type": email_type,
                    "provider": extraction.provider,
                    "needs_review": extraction.needs_review,
                    "entity_status": entity_status,
                },
            )
        return success_ids

    def _log_message_failed(
        self,
        message_id: str,
        exc: GmailConfigError,
        operation: str,
        method_name: str,
    ) -> None:
        log_error_event(
            self.logger,
            event="gmail_ingest.message_failed",
            error_code=exc.error_code,
            detail=exc.message,
            operation=operation,
            method_name=method_name,
            job_id=self.job_id,
            function_id=self.function_id,
            module_name="BAT-002.gmail_ingest",
            gmail_message_id=message_id,
        )


def run_ingest_batch() -> IngestBatchStats:
    """バッチランナー（app.main）向けエントリポイント。"""
    return GmailIngestBatch().run()


def main() -> None:
    run_ingest_batch()


if __name__ == "__main__":
    main()
