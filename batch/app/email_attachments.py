"""メール添付・サイズ上限の純粋ヘルパー（外部 API 非依存）。"""

from __future__ import annotations

from dataclasses import dataclass
from email.message import EmailMessage
import email.policy
from email.utils import formatdate, make_msgid


# Gmail 添付合計の目安上限（本文込みで余裕を見て 20MB）
MAX_ATTACHMENTS_BYTES = 20 * 1024 * 1024


@dataclass
class PreparedAttachment:
    filename: str
    content_type: str
    data: bytes
    display_name: str
    web_view_link: str | None = None


def apply_attachment_size_limit(
    prepared: list[PreparedAttachment],
) -> tuple[list[PreparedAttachment], list[str]]:
    """合計サイズが上限超なら添付なし・リンク行を返す。"""
    total = sum(len(p.data) for p in prepared)
    if total <= MAX_ATTACHMENTS_BYTES:
        return prepared, []
    link_lines: list[str] = ["", "■ スキルシート（容量のためリンクでご案内）"]
    for item in prepared:
        link = item.web_view_link or "(リンクなし)"
        link_lines.append(f"- {item.display_name}: {link}")
    return [], link_lines


def build_reply_email_message(
    *,
    from_addr: str,
    to_addr: str,
    subject_text: str,
    body_text: str,
    cc_list: list[str] | None = None,
    in_reply_to_message_id: str | None = None,
    references: str | None = None,
    attachments: list[dict] | None = None,
) -> EmailMessage:
    """send_reply 用の EmailMessage を構築する（テスト容易化）。"""
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"] = from_addr
    msg["To"] = to_addr
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    msg["Subject"] = subject_text
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@", 1)[-1])
    if in_reply_to_message_id:
        msg["In-Reply-To"] = in_reply_to_message_id
        msg["References"] = references or in_reply_to_message_id
    msg.set_content(body_text, charset="utf-8")

    for attachment in attachments or []:
        filename = str(attachment.get("filename") or "attachment.bin")
        content_type = str(attachment.get("content_type") or "application/octet-stream")
        raw_data = attachment.get("data") or b""
        if not isinstance(raw_data, (bytes, bytearray)):
            continue
        maintype, _, subtype = content_type.partition("/")
        if not subtype:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(
            bytes(raw_data),
            maintype=maintype,
            subtype=subtype,
            filename=filename,
        )
    return msg
