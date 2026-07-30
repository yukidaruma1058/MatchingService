"""スキルシートの Drive 保存名・添付名ヘルパー（DB / API 非依存）。"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_SHEETS_ID_RE = re.compile(
    r"https?://docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)
_SKILL_NAME_HINT_RE = re.compile(
    r"(スキル|skill|職務経歴|経歴|スキルシート)",
    re.IGNORECASE,
)
_ATTACHMENT_EXTS = {".xlsx", ".xls", ".xlsm", ".pdf"}


def sanitize_filename_part(raw: str | None, *, max_len: int = 80, fallback: str = "talent") -> str:
    text = (raw or "").strip()
    text = _UNSAFE_RE.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" ._")
    if not text:
        return fallback
    return text[:max_len]


def talent_short_id(talent_id: UUID | str) -> str:
    return str(talent_id).replace("-", "")[:8]


def drive_storage_filename(
    *,
    display_name: str | None,
    talent_id: UUID | str,
    source_hint: str | None,
    ext: str,
) -> str:
    """Drive 上の保存名: {表示名}_{shortId}_{手がかり}.{ext}"""
    name = sanitize_filename_part(display_name, fallback="talent")
    short = talent_short_id(talent_id)
    hint = sanitize_filename_part(source_hint, max_len=40, fallback="skill")
    extension = ext.lstrip(".").lower() or "bin"
    return f"{name}_{short}_{hint}.{extension}"


def attachment_source_hint(original_filename: str | None) -> str:
    stem = Path(original_filename or "").stem
    return sanitize_filename_part(stem, max_len=40, fallback="skill")


def spreadsheet_drive_filename(*, display_name: str | None, talent_id: UUID | str) -> str:
    return drive_storage_filename(
        display_name=display_name,
        talent_id=talent_id,
        source_hint="spreadsheet",
        ext="xlsx",
    )


def proposal_attachment_filename(*, display_name: str | None, ext: str, index: int = 1) -> str:
    """提案メール用: 【表示名】_スキルシート.{ext}（衝突時は _2 など）"""
    name = sanitize_filename_part(display_name, fallback="talent")
    extension = ext.lstrip(".").lower() or "bin"
    if index <= 1:
        return f"【{name}】_スキルシート.{extension}"
    return f"【{name}】_スキルシート_{index}.{extension}"


def company_folder_name(company_name: str | None) -> str:
    return sanitize_filename_part(company_name, max_len=80, fallback="未設定")


def extract_spreadsheet_ids(*texts: str | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in _SHEETS_ID_RE.finditer(text):
            file_id = match.group(1)
            if file_id not in seen:
                seen.add(file_id)
                found.append(file_id)
    return found


def is_skill_sheet_attachment(*, filename: str | None, mime_type: str | None) -> bool:
    name = (filename or "").strip()
    lower = name.lower()
    ext = Path(lower).suffix
    if ext in _ATTACHMENT_EXTS:
        return True
    mime = (mime_type or "").lower()
    if "pdf" in mime or "spreadsheet" in mime or "excel" in mime or "ms-excel" in mime:
        return True
    if name and _SKILL_NAME_HINT_RE.search(name):
        return True
    return False


def extension_from_filename_or_mime(filename: str | None, mime_type: str | None) -> str:
    ext = Path(filename or "").suffix.lstrip(".").lower()
    if ext:
        return ext
    mime = (mime_type or "").lower()
    if "pdf" in mime:
        return "pdf"
    if "spreadsheet" in mime or "excel" in mime:
        return "xlsx"
    return "bin"


def safe_original_filename(filename: str | None, *, ext: str) -> str:
    """Gmail 元名の危険文字だけ落とす（保存名生成のヒント用にも使える）。"""
    name = (filename or "").strip()
    name = name.replace("\\", "_").replace("/", "_")
    name = _UNSAFE_RE.sub("_", name).strip(" .")
    if not name:
        return f"attachment.{ext.lstrip('.')}"
    return name[:180]
