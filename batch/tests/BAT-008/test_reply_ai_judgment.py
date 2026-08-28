"""返信 AI 判定のユニットテスト（外部 API はモック）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

_BATCH_ROOT = Path(__file__).resolve().parents[2]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.reply_ai_judgment import ReplyJudgeItem, judge_replies_with_ai


class ReplyAiJudgmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = SimpleNamespace(
            cursor_api_key="cursor-key",
            openai_api_key="",
            openai_model="gpt-4o-mini",
            anthropic_api_key="",
            anthropic_model="claude-haiku-4-5-20251001",
        )
        self.items = [
            ReplyJudgeItem(proposal_id=uuid4(), title="案件A", item_index=1),
            ReplyJudgeItem(proposal_id=uuid4(), title="案件B", item_index=2),
        ]

    def test_ai_results_mapped_by_id(self) -> None:
        payload = {
            "results": [
                {"id": str(self.items[0].proposal_id), "judgment": "ok"},
                {"id": str(self.items[1].proposal_id), "judgment": "ng"},
            ]
        }
        with (
            patch("app.reply_ai_judgment._call_cursor", return_value=__import__("json").dumps(payload)),
            patch("app.reply_ai_judgment._call_openai", return_value=None),
            patch("app.reply_ai_judgment._call_claude", return_value=None),
        ):
            judged = judge_replies_with_ai(
                self.items,
                "【1】お願いします。【2】見送りです。",
                cfg=self.cfg,
                ok_keywords=[],
                ng_keywords=[],
            )
        self.assertEqual(judged[self.items[0].proposal_id], "ok")
        self.assertEqual(judged[self.items[1].proposal_id], "ng")

    def test_uses_claude_when_cursor_and_openai_unavailable(self) -> None:
        payload = {
            "results": [
                {"id": str(self.items[0].proposal_id), "judgment": "ok"},
                {"id": str(self.items[1].proposal_id), "judgment": "unknown"},
            ]
        }
        with (
            patch("app.reply_ai_judgment._call_cursor", return_value=None),
            patch("app.reply_ai_judgment._call_openai", return_value=None),
            patch(
                "app.reply_ai_judgment._call_claude",
                return_value=__import__("json").dumps(payload),
            ),
        ):
            judged = judge_replies_with_ai(
                self.items,
                "【1】前向きです。",
                cfg=self.cfg,
                ok_keywords=[],
                ng_keywords=[],
            )
        self.assertEqual(judged[self.items[0].proposal_id], "ok")
        self.assertEqual(judged[self.items[1].proposal_id], "unknown")

    def test_fallback_to_keywords_when_ai_unavailable(self) -> None:
        with (
            patch("app.reply_ai_judgment._call_cursor", return_value=None),
            patch("app.reply_ai_judgment._call_openai", return_value=None),
            patch("app.reply_ai_judgment._call_claude", return_value=None),
        ):
            judged = judge_replies_with_ai(
                self.items,
                "【1】よろしくお願いします。【2】見送りとさせてください。",
                cfg=self.cfg,
                ok_keywords=[],
                ng_keywords=[],
            )
        self.assertEqual(judged[self.items[0].proposal_id], "ok")
        self.assertEqual(judged[self.items[1].proposal_id], "ng")


if __name__ == "__main__":
    unittest.main()
