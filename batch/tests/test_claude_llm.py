"""Claude Messages ラッパーの単体テスト（外部 API なし）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.claude_llm import (  # noqa: E402
    DEFAULT_ANTHROPIC_MODEL,
    _content_to_text,
    call_claude_messages,
    resolve_anthropic_model,
)


class ClaudeLlmTests(unittest.TestCase):
    def test_resolve_model_default(self) -> None:
        self.assertEqual(resolve_anthropic_model(""), DEFAULT_ANTHROPIC_MODEL)
        self.assertEqual(resolve_anthropic_model("  "), DEFAULT_ANTHROPIC_MODEL)
        self.assertEqual(resolve_anthropic_model("claude-sonnet-4-5"), "claude-sonnet-4-5")

    def test_content_to_text_from_blocks(self) -> None:
        block = SimpleNamespace(type="text", text='{"ok": true}')
        self.assertEqual(_content_to_text([block]), '{"ok": true}')

    def test_call_claude_skips_without_key(self) -> None:
        self.assertIsNone(
            call_claude_messages(
                api_key="",
                model=None,
                system="sys",
                user="user",
            )
        )

    def test_call_claude_messages_success(self) -> None:
        mock_response = SimpleNamespace(
            content=[SimpleNamespace(type="text", text='{"ai_score": 80}')]
        )
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_anthropic_cls = MagicMock(return_value=mock_client)
        mock_module = MagicMock()
        mock_module.Anthropic = mock_anthropic_cls

        with patch.dict(sys.modules, {"anthropic": mock_module}):
            text = call_claude_messages(
                api_key="sk-ant-test",
                model="claude-haiku-4-5-20251001",
                system="sys",
                user="user",
            )
        self.assertEqual(text, '{"ai_score": 80}')
        mock_client.messages.create.assert_called_once()
        kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "claude-haiku-4-5-20251001")
        self.assertEqual(kwargs["system"], "sys")


if __name__ == "__main__":
    unittest.main()
