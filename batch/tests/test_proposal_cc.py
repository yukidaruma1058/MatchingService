"""proposal_cc 抽出ヘルパーの単体テスト。"""

from __future__ import annotations

import unittest
from pathlib import Path
import sys

_BATCH_ROOT = Path(__file__).resolve().parents[2]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.proposal_cc import (  # noqa: E402
    extract_cc_from_body,
    parse_address_list,
    resolve_proposal_cc,
)


class ProposalCcTests(unittest.TestCase):
    def test_parse_address_list_header(self) -> None:
        raw = "Tanaka <tanaka@example.com>, suzuki@example.com"
        self.assertEqual(
            parse_address_list(raw),
            ["tanaka@example.com", "suzuki@example.com"],
        )

    def test_extract_cc_from_body_inline(self) -> None:
        body = "お世話になっております。\nCCに a@x.com, b@y.com\n以上です。"
        self.assertEqual(extract_cc_from_body(body), ["a@x.com", "b@y.com"])

    def test_extract_cc_from_body_multiline(self) -> None:
        body = "【連絡】\nCC：\nc@z.com\nd@z.com\n\n【案件名】テスト"
        self.assertEqual(extract_cc_from_body(body), ["c@z.com", "d@z.com"])

    def test_resolve_header_only(self) -> None:
        result = resolve_proposal_cc(
            header_cc=["cc1@example.com", "from@example.com"],
            body_text="全員あてに返信をお願いします",
            exclude=["from@example.com"],
        )
        self.assertEqual(result, ["cc1@example.com"])

    def test_resolve_body_only(self) -> None:
        result = resolve_proposal_cc(
            header_cc=[],
            body_text="CCに body@example.com",
            exclude=["from@example.com"],
        )
        self.assertEqual(result, ["body@example.com"])

    def test_resolve_merge_and_dedupe(self) -> None:
        result = resolve_proposal_cc(
            header_cc=["shared@example.com", "hdr@example.com"],
            body_text="【CC】shared@example.com body@example.com",
            exclude=["to@example.com"],
        )
        self.assertEqual(result, ["shared@example.com", "hdr@example.com", "body@example.com"])


if __name__ == "__main__":
    unittest.main()
