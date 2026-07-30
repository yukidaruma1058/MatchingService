"""Gmail API 連携クライアント（API 用）。

OAuth トークンの検証・プロフィール取得・ラベル付け替えに利用する。
バッチ側（batch/app/gmail_client.py）と同等の認証ロジックを持つ。
"""

from __future__ import annotations

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/drive",
]


class GmailConfigError(Exception):
    """Gmail 認証・API 呼び出しに関する設定/連携エラー。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


class GmailClient:
    """Gmail API への薄いラッパー。"""

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self._service = None
        self._label_name_to_id: dict[str, str] = {}

    def connect(self) -> None:
        """OAuth トークンで認証し、Gmail API サービスを初期化する。"""
        if not self.credentials_path.exists():
            raise GmailConfigError("ERR-0018", "Gmail credentials file not found")
        if not self.token_path.exists():
            raise GmailConfigError("ERR-0018", "Gmail token file not found")

        creds = Credentials.from_authorized_user_file(str(self.token_path), GMAIL_SCOPES)
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                self.token_path.write_text(creds.to_json())
            else:
                raise GmailConfigError("ERR-0019", "Gmail token is invalid or expired")

        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self._refresh_label_map()

    @property
    def service(self):
        if self._service is None:
            raise RuntimeError("Gmail client is not connected")
        return self._service

    def _refresh_label_map(self) -> None:
        response = self.service.users().labels().list(userId="me").execute()
        self._label_name_to_id = {
            label["name"]: label["id"]
            for label in response.get("labels", [])
            if label.get("type") == "user"
        }

    def label_id(self, label_name: str) -> str:
        label_id = self._label_name_to_id.get(label_name)
        if not label_id:
            raise GmailConfigError("ERR-0020", f"Gmail label not found: {label_name}")
        return label_id

    def require_labels(self, label_names: list[str]) -> None:
        missing = [name for name in label_names if name not in self._label_name_to_id]
        if missing:
            raise GmailConfigError("ERR-0020", f"Gmail label not found: {', '.join(missing)}")

    def count_messages_with_label(self, label_name: str, *, max_count: int = 500) -> tuple[int, bool]:
        """指定ラベルのメール件数を返す。

        Returns:
            (件数, 上限打ち切りか)。max_count に達したら打ち切り True。
        """
        label_id = self.label_id(label_name)
        count = 0
        page_token = None
        while True:
            try:
                response = (
                    self.service.users()
                    .messages()
                    .list(
                        userId="me",
                        labelIds=[label_id],
                        pageToken=page_token,
                        maxResults=min(100, max(1, max_count - count)),
                    )
                    .execute()
                )
            except HttpError as exc:
                raise GmailConfigError(
                    "ERR-0021", f"Failed to count Gmail messages for label: {label_name}"
                ) from exc

            batch = response.get("messages") or []
            count += len(batch)
            if count >= max_count:
                return max_count, True
            page_token = response.get("nextPageToken")
            if not page_token or not batch:
                break
        return count, False

    def relabel_message(
        self,
        message_id: str,
        *,
        add_label_names: list[str],
        remove_label_names: list[str],
    ) -> None:
        add_ids = [self.label_id(name) for name in add_label_names]
        remove_ids = [self.label_id(name) for name in remove_label_names]
        try:
            self.service.users().messages().modify(
                userId="me",
                id=message_id,
                body={"addLabelIds": add_ids, "removeLabelIds": remove_ids},
            ).execute()
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to modify Gmail labels: {message_id}") from exc

    def get_profile(self) -> dict:
        """連携中 Gmail アカウントのプロフィールを取得する。"""
        try:
            return self.service.users().getProfile(userId="me").execute()
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", "Failed to fetch Gmail profile") from exc
