"""BAT-002: 取込バッチ用の DB アクセス。"""

from __future__ import annotations

from app.company_contact_db import (
    extract_email_address,
    link_company_contact_for_ingest,
    resolve_ingest_contact_email,
)
from app.email_db import (
    already_ingested_gmail_ids,
    get_email_by_gmail_id,
    mark_email_status,
    mark_email_summarized,
    upsert_project_from_email,
    upsert_sorted_email,
    upsert_talent_from_email,
)

__all__ = [
    "already_ingested_gmail_ids",
    "extract_email_address",
    "get_email_by_gmail_id",
    "link_company_contact_for_ingest",
    "mark_email_status",
    "mark_email_summarized",
    "resolve_ingest_contact_email",
    "upsert_project_from_email",
    "upsert_sorted_email",
    "upsert_talent_from_email",
]
