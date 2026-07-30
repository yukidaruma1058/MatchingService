"""返信キーワード判定のユニットテスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BATCH_ROOT = Path(__file__).resolve().parents[2]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.reply_judgment import (
    judge_reply_body,
    judge_reply_for_item,
    parse_keywords,
    parse_proposal_item_titles,
    resolve_item_index_for_title,
    split_reply_by_item_markers,
)


class ReplyJudgmentTests(unittest.TestCase):
    def test_parse_keywords(self) -> None:
        self.assertEqual(parse_keywords("a\nb\n"), ["a", "b"])
        self.assertEqual(parse_keywords("a, b"), ["a", "b"])

    def test_ng_priority(self) -> None:
        judgment = judge_reply_body(
            "前向きですが見送りとさせてください",
            ok_keywords=["前向き"],
            ng_keywords=["見送り"],
        )
        self.assertEqual(judgment, "ng")

    def test_ok(self) -> None:
        judgment = judge_reply_body(
            "よろしくお願いします",
            ok_keywords=["よろしくお願いします"],
            ng_keywords=["見送り"],
        )
        self.assertEqual(judgment, "ok")

    def test_unknown(self) -> None:
        judgment = judge_reply_body(
            "確認します",
            ok_keywords=["よろしくお願いします"],
            ng_keywords=["見送り"],
        )
        self.assertEqual(judgment, "unknown")

    def test_split_reply_by_item_markers(self) -> None:
        body = (
            "【1】飲料メーカー向け保守業務で進めさせてください。\n"
            "【2】インターネットバンキングシステム次期開発は辞退とさせてください。"
        )
        segments = split_reply_by_item_markers(body)
        self.assertIn(1, segments)
        self.assertIn(2, segments)
        self.assertIn("進めさせてください", segments[1])
        self.assertIn("辞退", segments[2])

    def test_per_item_judgment_mixed(self) -> None:
        body = (
            "【1】飲料メーカー向け保守業務で進めさせてください。\n"
            "【2】インターネットバンキングシステム次期開発は辞退とさせてください。"
        )
        self.assertEqual(
            judge_reply_for_item(body, item_index=1, ok_keywords=[], ng_keywords=[]),
            "ok",
        )
        self.assertEqual(
            judge_reply_for_item(body, item_index=2, ok_keywords=[], ng_keywords=[]),
            "ng",
        )

    def test_whole_body_ng_without_markers(self) -> None:
        body = "今回は辞退とさせてください。"
        self.assertEqual(
            judge_reply_for_item(body, item_index=1, ok_keywords=[], ng_keywords=[]),
            "ng",
        )

    def test_resolve_item_index_from_proposal_body(self) -> None:
        proposal = (
            "【1】飲料メーカー向け保守業務\n"
            "  必須スキル: Java\n\n"
            "【2】インターネットバンキングシステム次期開発\n"
            "  必須スキル: Java, AWS\n"
        )
        titles = parse_proposal_item_titles(proposal)
        self.assertEqual(titles[1], "飲料メーカー向け保守業務")
        self.assertEqual(
            resolve_item_index_for_title(proposal, "インターネットバンキングシステム次期開発"),
            2,
        )


if __name__ == "__main__":
    unittest.main()
