"""エラーコードと利用者向けメッセージの対応表。"""

from __future__ import annotations

ERROR_MESSAGES: dict[str, str] = {
    "ERR-0018": "Gmail が連携されていません。",
    "ERR-0019": "Gmail 認証の有効期限が切れています。再連携してください。",
    "ERR-0020": "Gmail ラベルが見つかりません。",
    "ERR-0021": "Gmail メールの取得に失敗しました。",
    "ERR-0022": "Gmail メールの送信に失敗しました。",
    "ERR-0028": "バッチ処理を開始できません。",
    "ERR-0029": "外部サービスへの接続がタイムアウトしました。",
    "ERR-0030": "システムエラーが発生しました。時間をおいて再度お試しください。",
}


def _format_label_names(raw: str) -> str:
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        return ""
    return "、".join(f"「{name}」" for name in names)


def _labels_from_detail(detail: str) -> str:
    text = (detail or "").strip()
    if not text:
        return ""
    for prefix in (
        "Gmail label not found:",
        "Failed to create Gmail label:",
        "Gmail ラベルが見つかりません:",
        "Gmail ラベルの作成に失敗しました:",
    ):
        if prefix in text:
            return _format_label_names(text.split(prefix, 1)[1])
    # すでに「xxx」形式ならそのまま使う
    if "「" in text and "」" in text:
        return text
    return _format_label_names(text)


def resolve_error_message(error_code: str, *, detail: str = "") -> str:
    """エラーコードに対応する利用者向けメッセージを返す。"""
    base = ERROR_MESSAGES.get(error_code, "エラーが発生しました。")
    if error_code == "ERR-0020":
        labels = _labels_from_detail(detail)
        if labels:
            return f"Gmail ラベルが見つかりません: {labels}"
    return base
