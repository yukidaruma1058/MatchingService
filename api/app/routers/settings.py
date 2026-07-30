"""設定 API（SCR-016）。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import load_settings, upsert_settings
from app.deps import get_db
from app.gmail_credentials import ensure_gmail_credentials_file
from app.gmail_oauth_urls import resolve_gmail_oauth_redirect_uri
from app.gmail_status import fetch_gmail_status
from app.schemas import SettingsResponse, SettingsUpdateRequest
from app.setting_keys import (
    DEFAULT_SETTINGS,
    GMAIL_SORT_SETTING_KEYS,
    SETTING_KEY_AI_ASSIST_ENABLED,
    SETTING_KEY_AI_JUDGEMENT_TOP_N,
    SETTING_KEY_OWN_COMPANY_NAME,
    SETTING_KEY_APPLY_FROM_ADDRESS,
    SETTING_KEY_GMAIL_OAUTH_CLIENT_ID,
    SETTING_KEY_GMAIL_OAUTH_CLIENT_SECRET,
    SETTING_KEY_GMAIL_OAUTH_PROJECT_ID,
    SETTING_KEY_INGEST_RETENTION_DAYS,
    SETTING_KEY_GMAIL_SORT_KEYWORDS_PROJECT,
    SETTING_KEY_GMAIL_SORT_KEYWORDS_TALENT,
    SETTING_KEY_GMAIL_SORT_LABEL_PROJECT,
    SETTING_KEY_GMAIL_SORT_LABEL_TALENT,
    SETTING_KEY_GMAIL_SORT_SOURCE_LABEL,
    SETTING_KEY_GMAIL_SORT_UNKNOWN_LABEL,
    SETTING_KEY_REPLY_KEYWORDS_NG,
    SETTING_KEY_REPLY_KEYWORDS_OK,
    SETTING_KEY_TEMPLATE_PROJECT_PROPOSE,
    SETTING_KEY_TEMPLATE_TALENT_PROPOSE,
    SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP,
    SETTING_KEY_SKILL_SHEET_DRIVE_FOLDER_ID,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _as_str(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=500, detail=f"{field_name} is invalid")
    return value.strip()


def _as_int(value: object, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _to_response(raw: dict, request: Request) -> SettingsResponse:
    retention = raw.get(SETTING_KEY_INGEST_RETENTION_DAYS, 0)
    try:
        retention_days = int(retention)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=500, detail="ingest_data_retention_days is invalid") from exc
    if retention_days < 0 or retention_days > 3650:
        raise HTTPException(status_code=500, detail="ingest_data_retention_days is out of range")

    redirect_uri = resolve_gmail_oauth_redirect_uri(request)
    gmail_status = fetch_gmail_status(raw, redirect_uri=redirect_uri)
    project_tpl = raw.get(SETTING_KEY_TEMPLATE_PROJECT_PROPOSE)
    talent_tpl = raw.get(SETTING_KEY_TEMPLATE_TALENT_PROPOSE)
    return SettingsResponse(
        ingest_data_retention_days=retention_days,
        gmail_sort_source_label=_as_str(raw.get(SETTING_KEY_GMAIL_SORT_SOURCE_LABEL), "gmail_sort_source_label"),
        gmail_sort_label_talent=_as_str(raw.get(SETTING_KEY_GMAIL_SORT_LABEL_TALENT), "gmail_sort_label_talent"),
        gmail_sort_label_project=_as_str(raw.get(SETTING_KEY_GMAIL_SORT_LABEL_PROJECT), "gmail_sort_label_project"),
        gmail_sort_unknown_label=_as_str(raw.get(SETTING_KEY_GMAIL_SORT_UNKNOWN_LABEL), "gmail_sort_unknown_label"),
        gmail_sort_keywords_talent=_as_str(
            raw.get(SETTING_KEY_GMAIL_SORT_KEYWORDS_TALENT),
            "gmail_sort_keywords_talent",
        ),
        gmail_sort_keywords_project=_as_str(
            raw.get(SETTING_KEY_GMAIL_SORT_KEYWORDS_PROJECT),
            "gmail_sort_keywords_project",
        ),
        ai_assist_enabled=bool(raw.get(SETTING_KEY_AI_ASSIST_ENABLED, False)),
        ai_judgement_top_n=_as_int(raw.get(SETTING_KEY_AI_JUDGEMENT_TOP_N), 5, minimum=1, maximum=20),
        own_company_name=str(raw.get(SETTING_KEY_OWN_COMPANY_NAME) or "").strip(),
        apply_from_address=str(raw.get(SETTING_KEY_APPLY_FROM_ADDRESS) or "").strip(),
        reply_keywords_ok=_as_str(raw.get(SETTING_KEY_REPLY_KEYWORDS_OK), "reply_keywords_ok"),
        reply_keywords_ng=_as_str(raw.get(SETTING_KEY_REPLY_KEYWORDS_NG), "reply_keywords_ng"),
        outreach_template_project_propose=(
            str(project_tpl).strip()
            if isinstance(project_tpl, str) and project_tpl.strip()
            else str(DEFAULT_SETTINGS[SETTING_KEY_TEMPLATE_PROJECT_PROPOSE])
        ),
        outreach_template_talent_propose=(
            str(talent_tpl).strip()
            if isinstance(talent_tpl, str) and talent_tpl.strip()
            else str(DEFAULT_SETTINGS[SETTING_KEY_TEMPLATE_TALENT_PROPOSE])
        ),
        talent_propose_rate_markup_man_yen=_as_int(
            raw.get(SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP),
            0,
            minimum=0,
            maximum=100,
        ),
        skill_sheet_drive_folder_id=str(raw.get(SETTING_KEY_SKILL_SHEET_DRIVE_FOLDER_ID) or "").strip(),
        gmail_connected_account=gmail_status.gmail_connected_account,
        gmail_auth_status=gmail_status.gmail_auth_status,
        gmail_last_checked_at=gmail_status.gmail_last_checked_at,
        gmail_error_code=gmail_status.gmail_error_code,
        gmail_setup_required=gmail_status.gmail_setup_required,
        gmail_setup_message=gmail_status.gmail_setup_message,
        gmail_oauth_client_configured=gmail_status.gmail_oauth_client_configured,
        gmail_oauth_client_id=gmail_status.gmail_oauth_client_id,
        gmail_oauth_redirect_uri=redirect_uri,
    )


@router.get("", response_model=SettingsResponse)
def get_settings(request: Request, session: Session = Depends(get_db)) -> SettingsResponse:
    """system_settings と Gmail 連携状態を取得する。"""
    return _to_response(load_settings(session), request)


@router.put("", response_model=SettingsResponse)
def update_settings(
    body: SettingsUpdateRequest,
    request: Request,
    session: Session = Depends(get_db),
) -> SettingsResponse:
    """system_settings を部分更新する。"""
    updates: dict[str, object] = {}
    oauth_updated = False

    if body.ingest_data_retention_days is not None:
        updates[SETTING_KEY_INGEST_RETENTION_DAYS] = body.ingest_data_retention_days
    if body.gmail_sort_source_label is not None:
        updates[SETTING_KEY_GMAIL_SORT_SOURCE_LABEL] = body.gmail_sort_source_label.strip()
    if body.gmail_sort_label_talent is not None:
        updates[SETTING_KEY_GMAIL_SORT_LABEL_TALENT] = body.gmail_sort_label_talent.strip()
    if body.gmail_sort_label_project is not None:
        updates[SETTING_KEY_GMAIL_SORT_LABEL_PROJECT] = body.gmail_sort_label_project.strip()
    if body.gmail_sort_unknown_label is not None:
        updates[SETTING_KEY_GMAIL_SORT_UNKNOWN_LABEL] = body.gmail_sort_unknown_label.strip()
    if body.gmail_sort_keywords_talent is not None:
        updates[SETTING_KEY_GMAIL_SORT_KEYWORDS_TALENT] = body.gmail_sort_keywords_talent.strip()
    if body.gmail_sort_keywords_project is not None:
        updates[SETTING_KEY_GMAIL_SORT_KEYWORDS_PROJECT] = body.gmail_sort_keywords_project.strip()
    if body.ai_assist_enabled is not None:
        updates[SETTING_KEY_AI_ASSIST_ENABLED] = body.ai_assist_enabled
    if body.ai_judgement_top_n is not None:
        updates[SETTING_KEY_AI_JUDGEMENT_TOP_N] = body.ai_judgement_top_n
    if body.own_company_name is not None:
        updates[SETTING_KEY_OWN_COMPANY_NAME] = body.own_company_name.strip()
    if body.apply_from_address is not None:
        addr = body.apply_from_address.strip()
        if addr and ("@" not in addr or "." not in addr.split("@")[-1]):
            raise HTTPException(status_code=400, detail="apply_from_address must be a valid email")
        updates[SETTING_KEY_APPLY_FROM_ADDRESS] = addr
    if body.reply_keywords_ok is not None:
        updates[SETTING_KEY_REPLY_KEYWORDS_OK] = body.reply_keywords_ok.strip()
    if body.reply_keywords_ng is not None:
        updates[SETTING_KEY_REPLY_KEYWORDS_NG] = body.reply_keywords_ng.strip()
    if body.outreach_template_project_propose is not None:
        updates[SETTING_KEY_TEMPLATE_PROJECT_PROPOSE] = body.outreach_template_project_propose
    if body.outreach_template_talent_propose is not None:
        updates[SETTING_KEY_TEMPLATE_TALENT_PROPOSE] = body.outreach_template_talent_propose
    if body.talent_propose_rate_markup_man_yen is not None:
        updates[SETTING_KEY_TALENT_PROPOSE_RATE_MARKUP] = body.talent_propose_rate_markup_man_yen
    if body.skill_sheet_drive_folder_id is not None:
        updates[SETTING_KEY_SKILL_SHEET_DRIVE_FOLDER_ID] = body.skill_sheet_drive_folder_id.strip()
    if body.gmail_oauth_client_id is not None:
        updates[SETTING_KEY_GMAIL_OAUTH_CLIENT_ID] = body.gmail_oauth_client_id.strip()
        oauth_updated = True
    if body.gmail_oauth_client_secret is not None:
        secret = body.gmail_oauth_client_secret.strip()
        if not secret:
            raise HTTPException(status_code=400, detail="gmail_oauth_client_secret must not be empty")
        updates[SETTING_KEY_GMAIL_OAUTH_CLIENT_SECRET] = secret
        oauth_updated = True
    if body.gmail_oauth_project_id is not None:
        updates[SETTING_KEY_GMAIL_OAUTH_PROJECT_ID] = body.gmail_oauth_project_id.strip() or "matching-service"
        oauth_updated = True

    if not updates:
        raise HTTPException(status_code=400, detail="No settings to update")

    for key in GMAIL_SORT_SETTING_KEYS:
        if key in updates and not str(updates[key]).strip():
            raise HTTPException(status_code=400, detail=f"{key} must not be empty")

    for key in (
        SETTING_KEY_REPLY_KEYWORDS_OK,
        SETTING_KEY_REPLY_KEYWORDS_NG,
        SETTING_KEY_TEMPLATE_PROJECT_PROPOSE,
        SETTING_KEY_TEMPLATE_TALENT_PROPOSE,
    ):
        if key in updates and not str(updates[key]).strip():
            raise HTTPException(status_code=400, detail=f"{key} must not be empty")

    if SETTING_KEY_GMAIL_OAUTH_CLIENT_ID in updates and not str(updates[SETTING_KEY_GMAIL_OAUTH_CLIENT_ID]).strip():
        raise HTTPException(status_code=400, detail="gmail_oauth_client_id must not be empty")

    merged = upsert_settings(session, updates)
    if oauth_updated:
        redirect_uri = resolve_gmail_oauth_redirect_uri(request)
        ensure_gmail_credentials_file(merged, force=True, redirect_uri=redirect_uri)
    return _to_response(merged, request)
