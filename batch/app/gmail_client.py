"""Gmail API 連携クライアント（バッチ共通）。

OAuth 2.0 で認証し、メール一覧取得・本文取得・ラベル付け替えを行う。
BAT-001（振り分け）や将来の BAT-002（取込）・BAT-005（送信同期）から利用する。
"""

from __future__ import annotations

import base64
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# メールの読み取り・ラベル変更・送信・送信元エイリアス確認に必要なスコープ
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/drive",
]

# Gmail API HTTP のソケットタイムアウト（無限ハング防止）
GMAIL_HTTP_TIMEOUT_SECONDS = 60


class GmailConfigError(Exception):
    """Gmail 認証・ラベル・API 呼び出しに関する設定/連携エラー。

    error_code はエラーコード一覧（ERR-0018 など）と対応する。
    """

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message


@dataclass(frozen=True)
class GmailMessage:
    """Gmail API から取得したメールの正規化済みデータ。"""

    message_id: str
    thread_id: str | None
    label_ids: list[str]       # Gmail 内部のラベル ID 一覧
    subject: str
    from_address: str
    received_at: datetime
    body_text: str
    body_html: str
    from_header: str = ""  # From 生ヘッダー（表示名付き）
    to_addresses: tuple[str, ...] = ()
    cc_addresses: tuple[str, ...] = ()


class GmailClient:
    """Gmail API への薄いラッパー。ラベル名と ID の変換を内部で保持する。"""

    def __init__(self, credentials_path: str, token_path: str) -> None:
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self._service = None
        self._label_name_to_id: dict[str, str] = {}
        # httplib2 / googleapiclient はスレッドセーフではないため、並列 fetch 時は直列化する
        self._api_lock = threading.RLock()

    def connect(self) -> None:
        """OAuth トークンで認証し、Gmail API サービスを初期化する。

        トークン期限切れの場合はリフレッシュトークンで自動更新する。
        """
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

        http = httplib2.Http(timeout=GMAIL_HTTP_TIMEOUT_SECONDS)
        authed_http = AuthorizedHttp(creds, http=http)
        self._service = build("gmail", "v1", http=authed_http, cache_discovery=False)
        self._refresh_label_map()

    @property
    def service(self):
        if self._service is None:
            raise RuntimeError("Gmail client is not connected")
        return self._service

    def _execute(self, request: Any) -> Any:
        """API リクエストをロック付きで実行する（並列ハング・競合防止）。"""
        with self._api_lock:
            return request.execute()

    def _refresh_label_map(self) -> None:
        """ユーザー定義ラベルの「名前 → Gmail 内部 ID」マップを構築する。"""
        response = self._execute(self.service.users().labels().list(userId="me"))
        self._label_name_to_id = {
            label["name"]: label["id"]
            for label in response.get("labels", [])
            if label.get("type") == "user"
        }

    def label_id(self, label_name: str) -> str:
        """ラベル名から Gmail 内部 ID を取得する。存在しない場合は ERR-0020。"""
        label_id = self._label_name_to_id.get(label_name)
        if not label_id:
            raise GmailConfigError("ERR-0020", f"Gmail label not found: {label_name}")
        return label_id

    def require_labels(self, label_names: list[str]) -> None:
        """指定ラベルが Gmail にすべて存在することを検証する。未作成があれば ERR-0020。"""
        missing = [name for name in label_names if name not in self._label_name_to_id]
        if missing:
            raise GmailConfigError("ERR-0020", f"Gmail label not found: {', '.join(missing)}")

    def ensure_labels(self, label_names: list[str]) -> None:
        """指定ラベルが無ければ作成する。"""
        seen: set[str] = set()
        for name in label_names:
            text = (name or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            self.ensure_label(text)

    def list_message_ids_with_label(self, label_name: str, *, max_results: int = 100) -> list[str]:
        """指定ラベルが付いたメールの ID 一覧を取得する（ページング対応）。"""
        label_id = self.label_id(label_name)
        message_ids: list[str] = []
        page_token = None
        while True:
            try:
                response = self._execute(
                    self.service.users()
                    .messages()
                    .list(
                        userId="me",
                        labelIds=[label_id],
                        pageToken=page_token,
                        maxResults=min(max_results - len(message_ids), 100),
                    )
                )
            except HttpError as exc:
                raise GmailConfigError("ERR-0021", "Failed to list Gmail messages") from exc

            for item in response.get("messages", []):
                message_ids.append(item["id"])
                if len(message_ids) >= max_results:
                    return message_ids

            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return message_ids

    def fetch_message(self, message_id: str) -> GmailMessage:
        """メール 1 件のヘッダー・本文を取得し GmailMessage として返す。"""
        try:
            raw = self._execute(
                self.service.users().messages().get(userId="me", id=message_id, format="full")
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to fetch Gmail message: {message_id}") from exc

        payload = raw.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        body_text, body_html = _extract_bodies(payload)
        received_at = _parse_internal_date(raw.get("internalDate"))

        raw_from = headers.get("from", "unknown@unknown")
        from app.proposal_cc import parse_address_list

        return GmailMessage(
            message_id=message_id,
            thread_id=raw.get("threadId"),
            label_ids=raw.get("labelIds", []),
            subject=headers.get("subject", "(no subject)"),
            from_address=_extract_email_address(raw_from),
            from_header=raw_from.strip()[:255],
            received_at=received_at,
            body_text=body_text,
            body_html=body_html,
            to_addresses=tuple(parse_address_list(headers.get("to"))),
            cc_addresses=tuple(parse_address_list(headers.get("cc"))),
        )

    def relabel_message(
        self,
        message_id: str,
        *,
        add_label_names: list[str],
        remove_label_names: list[str],
    ) -> None:
        """メールのラベルを追加・削除する（BAT-001 の振り分けで使用）。

        追加側は未作成なら作成する。削除側は未作成ラベルは無視する。
        """
        add_ids = [self.ensure_label(name) for name in add_label_names if (name or "").strip()]
        remove_ids = [
            self._label_name_to_id[name]
            for name in remove_label_names
            if (name or "").strip() and name in self._label_name_to_id
        ]
        if not add_ids and not remove_ids:
            return
        try:
            self._execute(
                self.service.users().messages().modify(
                    userId="me",
                    id=message_id,
                    body={"addLabelIds": add_ids, "removeLabelIds": remove_ids},
                )
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to modify Gmail labels: {message_id}") from exc

    def has_any_label(self, label_ids: list[str], label_names: list[str]) -> bool:
        """メールが指定ラベルのいずれかを既に持っているか判定する（再振り分け防止）。"""
        wanted = {self.label_id(name) for name in label_names}
        return any(label_id in wanted for label_id in label_ids)

    def ensure_label(self, label_name: str) -> str:
        """ラベルが無ければ作成し、Gmail 内部 ID を返す。"""
        existing = self._label_name_to_id.get(label_name)
        if existing:
            return existing
        try:
            created = self._execute(
                self.service.users()
                .labels()
                .create(
                    userId="me",
                    body={
                        "name": label_name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                )
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0020", f"Failed to create Gmail label: {label_name}") from exc
        label_id = str(created["id"])
        self._label_name_to_id[label_name] = label_id
        return label_id

    def list_thread_message_ids(self, thread_id: str) -> list[str]:
        """スレッド内のメッセージ ID 一覧（古い順）。"""
        try:
            raw = self._execute(
                self.service.users().threads().get(userId="me", id=thread_id, format="minimal")
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to fetch Gmail thread: {thread_id}") from exc
        messages = raw.get("messages", []) or []
        return [str(item["id"]) for item in messages if item.get("id")]

    def get_header_map(self, message_id: str, header_names: list[str]) -> dict[str, str]:
        """指定ヘッダー名の値を小文字キーで返す。"""
        wanted = {name.lower() for name in header_names}
        try:
            raw = self._execute(
                self.service.users()
                .messages()
                .get(
                    userId="me",
                    id=message_id,
                    format="metadata",
                    metadataHeaders=list(header_names),
                )
            )
        except HttpError as exc:
            raise GmailConfigError("ERR-0021", f"Failed to fetch Gmail headers: {message_id}") from exc
        headers = {
            str(h["name"]).lower(): str(h["value"])
            for h in (raw.get("payload", {}) or {}).get("headers", [])
            if str(h.get("name", "")).lower() in wanted
        }
        return headers

    def get_rfc822_message_id(self, message_id: str) -> str | None:
        """Gmail message の Message-ID ヘッダーを取得する。"""
        value = self.get_header_map(message_id, ["Message-ID"]).get("message-id")
        return value.strip() if value else None

    def resolve_reply_recipient(self, message_id: str, *, fallback: str | None = None) -> str:
        """返信宛先を決める。Reply-To があれば優先し、なければ From。"""
        headers = self.get_header_map(message_id, ["Reply-To", "From"])
        candidates = []
        if headers.get("reply-to"):
            # 複数指定時は先頭を使う
            candidates.append(headers["reply-to"].split(",")[0].strip())
        if headers.get("from"):
            candidates.append(headers["from"].strip())
        if fallback:
            candidates.append(fallback.strip())
        for raw in candidates:
            addr = _extract_email_address(raw)
            if _is_valid_email(addr):
                return addr
        raise GmailConfigError(
            "ERR-0022",
            f"返信先メールアドレスを解決できませんでした: message_id={message_id}",
        )

    def get_authenticated_email(self) -> str | None:
        """連携中 Gmail アカウントのメールアドレス。"""
        try:
            profile = self._execute(self.service.users().getProfile(userId="me"))
        except HttpError:
            return None
        email = str(profile.get("emailAddress") or "").strip()
        return email or None

    def list_send_as_emails(self) -> list[str]:
        """連携アカウントから送信可能なアドレス一覧（プライマリ＋エイリアス）。"""
        emails: list[str] = []
        primary = self.get_authenticated_email()
        if primary:
            emails.append(primary)
        try:
            result = self._execute(self.service.users().settings().sendAs().list(userId="me"))
        except HttpError:
            return emails
        for item in result.get("sendAs", []) or []:
            addr = _extract_email_address(str(item.get("sendAsEmail") or ""))
            if _is_valid_email(addr) and addr.lower() not in {e.lower() for e in emails}:
                emails.append(addr)
        return emails

    def resolve_send_from_address(self, configured: str | None) -> str:
        """設定の応募メール送信元を検証し、送信に使うアドレスを返す。

        未設定時は連携 Gmail のプライマリアドレスを使う。
        """
        addr = _extract_email_address(configured or "")
        if not _is_valid_email(addr):
            primary = self.get_authenticated_email()
            if primary and _is_valid_email(primary):
                return primary
            raise GmailConfigError(
                "ERR-0022",
                "連携 Gmail の送信元アドレスを取得できませんでした。",
            )
        allowed = {e.lower() for e in self.list_send_as_emails()}
        if addr.lower() not in allowed:
            raise GmailConfigError(
                "ERR-0022",
                f"応募メール送信元（{addr}）は連携 Gmail から送信できません。"
                " Gmail の「名前で送信」に登録済みのアドレスを設定してください。",
            )
        return addr

    def send_reply(
        self,
        *,
        to_address: str,
        subject: str,
        body_text: str,
        thread_id: str,
        from_address: str | None = None,
        in_reply_to_message_id: str | None = None,
        references: str | None = None,
        cc_addresses: list[str] | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> str:
        """既存スレッドへ返信し、送信後の Gmail message id を返す。

        attachments: [{filename, content_type, data(bytes)}, ...]
        """
        import email.policy
        from email.message import EmailMessage
        from email.utils import formatdate, make_msgid

        to_addr = _extract_email_address(to_address)
        if not _is_valid_email(to_addr):
            raise GmailConfigError("ERR-0022", f"宛先メールアドレスが不正です: {to_address}")

        subject_text = subject.strip() if subject else "(no subject)"
        if not subject_text.lower().startswith("re:"):
            subject_text = f"Re: {subject_text}"

        from_addr = self.resolve_send_from_address(from_address)

        cc_list: list[str] = []
        seen_cc = {to_addr.lower(), from_addr.lower()}
        for raw in cc_addresses or []:
            addr = _extract_email_address(str(raw))
            if not _is_valid_email(addr):
                continue
            key = addr.lower()
            if key in seen_cc:
                continue
            seen_cc.add(key)
            cc_list.append(addr)

        from app.email_attachments import build_reply_email_message

        msg = build_reply_email_message(
            from_addr=from_addr,
            to_addr=to_addr,
            subject_text=subject_text,
            body_text=body_text,
            cc_list=cc_list,
            in_reply_to_message_id=in_reply_to_message_id,
            references=references,
            attachments=attachments,
        )

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        body: dict[str, Any] = {"raw": raw, "threadId": thread_id}
        try:
            sent = self._execute(self.service.users().messages().send(userId="me", body=body))
        except HttpError as exc:
            raise GmailConfigError("ERR-0022", f"Failed to send Gmail reply in thread: {thread_id}") from exc
        message_id = sent.get("id")
        if not message_id:
            raise GmailConfigError("ERR-0022", "Gmail send returned empty message id")

        # 送信結果の To を確認（Sent に残るが宛先不正、を早期検知）
        try:
            sent_headers = self.get_header_map(str(message_id), ["To"])
            sent_to = _extract_email_address(sent_headers.get("to", ""))
            if sent_to and sent_to.lower() != to_addr.lower():
                raise GmailConfigError(
                    "ERR-0022",
                    f"送信先が一致しませんでした: expected={to_addr}, actual={sent_to}",
                )
        except GmailConfigError:
            raise
        except Exception:
            pass
        return str(message_id)


def _extract_bodies(payload: dict[str, Any]) -> tuple[str, str]:
    """multipart メールを再帰的に走査し、text/plain と text/html 本文を抽出する。"""
    text_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict[str, Any]) -> None:
        mime_type = part.get("mimeType", "")
        body = part.get("body", {})
        data = body.get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            if mime_type == "text/plain":
                text_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)
        for child in part.get("parts", []):
            walk(child)

    walk(payload)
    return "\n".join(text_parts).strip(), "\n".join(html_parts).strip()


def _parse_internal_date(raw: str | None) -> datetime:
    """Gmail internalDate（ミリ秒 Unix 時刻）を datetime へ変換する。"""
    if not raw:
        return datetime.now(UTC)
    return datetime.fromtimestamp(int(raw) / 1000, tz=UTC)


def _extract_email_address(raw_from: str) -> str:
    """From / Reply-To ヘッダーからメールアドレス部分を取り出す。"""
    text = (raw_from or "").strip()
    if not text:
        return ""
    match = re.search(r"<([^>]+)>", text)
    if match:
        return match.group(1).strip()
    found = re.search(r"[\w.+\-]+@[\w.\-]+\.\w+", text)
    if found:
        return found.group(0).strip()
    return text


def _is_valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (value or "").strip()))
