"""BAT-002: メール取込・AI要約バッチ。

処理概要:
  1. 人材用 / 案件用ラベル付きメールを Gmail から取得
  2. Cursor SDK（優先）または OpenAI で JSON 抽出し talents/projects へ保存
     （AI 要約のみ軽度並列、Gmail fetch / DB / ラベル更新は直列）
  3. emails.status を更新し、Gmail を処理済みラベルへ移動
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass

from db import (
    extract_email_address,
    get_email_by_gmail_id,
    link_company_contact_for_ingest,
    mark_email_status,
    upsert_project_from_email,
    upsert_talent_from_email,
)
from summarizer import ExtractionResult, extract_email_fields

from app.ai_concurrency import map_parallel, resolve_ai_concurrency
from app.config import Settings, settings
from app.db_bootstrap import create_session_factory, ensure_schema
from app.email_db import load_all_settings, upsert_sorted_email
from app.gmail_client import GmailClient, GmailConfigError, GmailMessage
from app.gmail_credentials import ensure_gmail_credentials_file
from app.proposal_cc import resolve_proposal_cc
from app.label_settings import IngestSettings, load_ingest_settings
from app.logging_util import get_batch_logger, log_error_event, log_event
from app.models import Talent
from app.skill_sheet_ingest import ingest_talent_skill_sheets


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


@dataclass
class _PendingSkillSheet:
    talent_id: object
    gmail_message_id: str
    body_text: str | None
    body_html: str | None


class GmailIngestBatch:
    """BAT-002 メール取込・要約バッチ。"""

    function_id = "BAT-002"

    def __init__(self, cfg: Settings | None = None) -> None:
        self.cfg = cfg or settings
        self.logger = get_batch_logger()
        self.job_id = f"job_{uuid.uuid4().hex[:12]}"
        self.ai_concurrency = resolve_ai_concurrency(getattr(self.cfg, "ai_concurrency", 3))

    def run(self) -> IngestBatchStats:
        started = time.perf_counter()
        stats = IngestBatchStats()

        log_event(
            self.logger,
            logging.INFO,
            event="gmail_ingest.started",
            message="Gmail ingest batch started",
            operation="メール取込開始",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            extra={"ai_concurrency": self.ai_concurrency},
        )

        session_factory, engine = create_session_factory(self.cfg.database_url)
        ensure_schema(engine)

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

        required_labels = [
            ingest_settings.talent_label,
            ingest_settings.project_label,
            ingest_settings.processed_talent_label,
            ingest_settings.processed_project_label,
        ]
        try:
            # 人材用 / 案件用 / 処理済み が無ければ自動作成
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
                function_id=self.function_id,
            )
            raise

        targets = (
            ("talent", ingest_settings.talent_label, ingest_settings.processed_talent_label),
            ("project", ingest_settings.project_label, ingest_settings.processed_project_label),
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
                "openai_model": getattr(self.cfg, "openai_model", ""),
                "ai_concurrency": self.ai_concurrency,
            },
        )

        pending_sheets: list[_PendingSkillSheet] = []
        for email_type, source_label, processed_label in targets:
            self._process_label(
                client=client,
                session_factory=session_factory,
                ingest_settings=ingest_settings,
                stats=stats,
                email_type=email_type,
                source_label=source_label,
                processed_label=processed_label,
                pending_sheets=pending_sheets,
            )

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
                "pending_skill_sheets": len(pending_sheets),
            },
        )

        # スキルシートは要約・DB登録完了後に処理（取込本体の壁時計から分離）
        if pending_sheets:
            sheet_started = time.perf_counter()
            self._ingest_pending_skill_sheets(
                session_factory=session_factory,
                client=client,
                pending_sheets=pending_sheets,
            )
            log_event(
                self.logger,
                logging.INFO,
                event="gmail_ingest.skill_sheets_finished",
                message="Deferred skill sheet ingest finished",
                operation="スキルシート保存",
                method_name="run",
                job_id=self.job_id,
                function_id=self.function_id,
                duration_ms=int((time.perf_counter() - sheet_started) * 1000),
                extra={"count": len(pending_sheets)},
            )

        return stats

    def _process_label(
        self,
        *,
        client: GmailClient,
        session_factory,
        ingest_settings: IngestSettings,
        stats: IngestBatchStats,
        email_type: str,
        source_label: str,
        processed_label: str,
        pending_sheets: list[_PendingSkillSheet],
    ) -> None:
        try:
            message_ids = client.list_message_ids_with_label(source_label)
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
            stats.failed += 1
            return

        processed_labels = [
            ingest_settings.processed_talent_label,
            ingest_settings.processed_project_label,
        ]

        # Phase 1: Gmail fetch（軽度並列）
        fetch_results = map_parallel(
            message_ids,
            lambda message_id: self._fetch_one(client, message_id),
            concurrency=self.ai_concurrency,
        )
        fetched: list[_FetchedMail] = []
        for message_id, message, fetch_error in fetch_results:
            stats.scanned += 1
            if fetch_error is not None:
                stats.failed += 1
                if isinstance(fetch_error, GmailConfigError):
                    self._log_message_failed(message_id, fetch_error, "Gmail本文取得", "fetch_message")
                else:
                    log_error_event(
                        self.logger,
                        event="gmail_ingest.message_failed",
                        error_code="ERR-0030",
                        detail=str(fetch_error),
                        operation="Gmail本文取得",
                        method_name="fetch_message",
                        job_id=self.job_id,
                        function_id=self.function_id,
                        module_name="BAT-002.gmail_ingest",
                        gmail_message_id=message_id,
                    )
                continue
            assert message is not None
            if client.has_any_label(message.label_ids, processed_labels):
                stats.skipped += 1
                continue

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

        # Phase 2: AI 要約のみ軽度並列
        extracted = map_parallel(
            fetched,
            lambda item: self._extract_one(item, email_type=email_type),
            concurrency=self.ai_concurrency,
        )

        # Phase 3: DB 保存・ラベル移動は直列（入力順を維持）。スキルシートは run 後段。
        for item in extracted:
            self._persist_one(
                client=client,
                session_factory=session_factory,
                stats=stats,
                email_type=email_type,
                source_label=source_label,
                processed_label=processed_label,
                item=item,
                pending_sheets=pending_sheets,
            )

    def _fetch_one(
        self,
        client: GmailClient,
        message_id: str,
    ) -> tuple[str, GmailMessage | None, BaseException | None]:
        try:
            return message_id, client.fetch_message(message_id), None
        except BaseException as exc:  # noqa: BLE001
            return message_id, None, exc

    def _extract_one(self, item: _FetchedMail, *, email_type: str) -> _ExtractedMail:
        try:
            extraction = extract_email_fields(
                email_type,  # type: ignore[arg-type]
                item.message.subject,
                item.body,
                self.cfg,  # type: ignore[arg-type]
                from_header=item.message.from_header or item.message.from_address,
            )
            return _ExtractedMail(fetched=item, extraction=extraction)
        except BaseException as exc:  # noqa: BLE001 — ワーカー内で捕捉し呼び出し側で集計
            return _ExtractedMail(fetched=item, extraction=None, error=exc)

    def _persist_one(
        self,
        *,
        client: GmailClient,
        session_factory,
        stats: IngestBatchStats,
        email_type: str,
        source_label: str,
        processed_label: str,
        item: _ExtractedMail,
        pending_sheets: list[_PendingSkillSheet],
    ) -> None:
        message = item.fetched.message
        message_id = item.fetched.message_id
        body = item.fetched.body
        proposal_cc = item.fetched.proposal_cc

        if item.error is not None:
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
            return

        extraction = item.extraction
        if extraction is None or not extraction.data:
            stats.failed += 1
            with session_factory() as session:
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
                session.commit()
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
            return

        entity_status = "inactive" if extraction.needs_review and email_type == "talent" else (
            "closed" if extraction.needs_review and email_type == "project" else (
                "active" if email_type == "talent" else "open"
            )
        )
        # needs_review でもレコードは登録し、emails は needs_review / summarized
        email_status = "needs_review" if extraction.needs_review else "summarized"

        try:
            with session_factory() as session:
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
                        contact_email=extract_email_address(
                            message.from_header or message.from_address
                        )
                        or message.from_address,
                        from_header=message.from_header,
                        talent_id=entity_id,
                    )
                    talent_row = session.get(Talent, entity_id)
                    if talent_row is not None:
                        pending_sheets.append(
                            _PendingSkillSheet(
                                talent_id=entity_id,
                                gmail_message_id=message.message_id,
                                body_text=message.body_text,
                                body_html=message.body_html,
                            )
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
                        contact_email=extract_email_address(
                            message.from_header or message.from_address
                        )
                        or message.from_address,
                        from_header=message.from_header,
                        project_id=entity_id,
                    )

                # body_text は原文のまま残す（要約は talents/projects.summary 側）
                mark_email_status(
                    session,
                    gmail_message_id=message.message_id,
                    status=email_status,
                    label=processed_label,
                    body_text=body,
                    body_html=message.body_html or None,
                )
                session.commit()
        except Exception as exc:
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
            return

        try:
            client.relabel_message(
                message_id,
                add_label_names=[processed_label],
                remove_label_names=[source_label],
            )
        except GmailConfigError as exc:
            stats.failed += 1
            self._log_message_failed(message_id, exc, "Gmailラベル更新", "relabel_message")
            return

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
            event="gmail_ingest.message_fetched",
            message="Gmail message ingested",
            operation="メール取込",
            method_name="run",
            job_id=self.job_id,
            function_id=self.function_id,
            gmail_message_id=message_id,
            extra={
                "label_type": email_type,
                "source_label": source_label,
                "processed_label": processed_label,
                "provider": extraction.provider,
                "needs_review": extraction.needs_review,
                "entity_status": entity_status,
            },
        )

    def _ingest_pending_skill_sheets(
        self,
        *,
        session_factory,
        client: GmailClient,
        pending_sheets: list[_PendingSkillSheet],
    ) -> None:
        def _one(job: _PendingSkillSheet) -> None:
            with session_factory() as session:
                talent_row = session.get(Talent, job.talent_id)
                if talent_row is None:
                    return
                settings_map = load_all_settings(session)
                folder_id = str(settings_map.get("skill_sheet_drive_folder_id") or "").strip()
                try:
                    with session.begin_nested():
                        ingest_talent_skill_sheets(
                            session=session,
                            gmail=client,
                            talent=talent_row,
                            gmail_message_id=job.gmail_message_id,
                            body_text=job.body_text,
                            body_html=job.body_html,
                            root_folder_id=folder_id,
                            logger=self.logger,
                            job_id=self.job_id,
                        )
                    session.commit()
                except Exception as sheet_exc:  # noqa: BLE001
                    session.rollback()
                    log_error_event(
                        self.logger,
                        event="gmail_ingest.skill_sheet_failed",
                        error_code="ERR-0015",
                        detail=str(sheet_exc),
                        operation="スキルシート保存",
                        method_name="ingest_talent_skill_sheets",
                        job_id=self.job_id,
                        function_id=self.function_id,
                        module_name="BAT-002.gmail_ingest",
                        gmail_message_id=job.gmail_message_id,
                    )

        map_parallel(pending_sheets, _one, concurrency=1)

    def _log_message_failed(self, message_id: str, exc: GmailConfigError, operation: str, method_name: str) -> None:
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


def run_ingest_batch(cfg: Settings | None = None) -> IngestBatchStats:
    return GmailIngestBatch(cfg).run()
