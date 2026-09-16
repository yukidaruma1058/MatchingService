"""AI判定の LLM 優先順（Gemini → Cursor → OpenAI → Claude）。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

_BATCH_ROOT = Path(__file__).resolve().parents[2]
_BAT004_ROOT = _BATCH_ROOT / "BAT-004"
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))


def _install_ai_judge_stubs() -> None:
    import types

    class _Session:  # pragma: no cover - import stub
        pass

    sqlalchemy = types.ModuleType("sqlalchemy")
    sqlalchemy.__path__ = []  # type: ignore[attr-defined]
    sqlalchemy.select = MagicMock()
    orm = types.ModuleType("sqlalchemy.orm")
    orm.Session = _Session
    dialects = types.ModuleType("sqlalchemy.dialects")
    dialects.__path__ = []  # type: ignore[attr-defined]
    postgres = types.ModuleType("sqlalchemy.dialects.postgresql")
    postgres.insert = MagicMock()
    sqlalchemy.orm = orm
    sqlalchemy.dialects = dialects
    dialects.postgresql = postgres
    sys.modules["sqlalchemy"] = sqlalchemy
    sys.modules["sqlalchemy.orm"] = orm
    sys.modules["sqlalchemy.dialects"] = dialects
    sys.modules["sqlalchemy.dialects.postgresql"] = postgres
    sys.modules.setdefault("pydantic_settings", MagicMock())
    sys.modules.setdefault("app.models", MagicMock())
    sys.modules.setdefault("app.db_bootstrap", MagicMock())
    sys.modules.setdefault("app.config", MagicMock())
    sys.modules.setdefault("app.email_db", MagicMock())
    sys.modules.setdefault("app.skill_sheet_experience", MagicMock())


def _load_ai_judge_module():
    path = _BAT004_ROOT / "ai_judge.py"
    spec = importlib.util.spec_from_file_location("bat004_ai_judge_gemini_test", path)
    assert spec and spec.loader
    try:
        import sqlalchemy  # noqa: F401
    except ModuleNotFoundError:
        _install_ai_judge_stubs()
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        gemini_api_key="g",
        gemini_model="gemini-2.5-flash",
        cursor_api_key="c",
        openai_api_key="o",
        openai_model="gpt-4o-mini",
        anthropic_api_key="a",
        anthropic_model="claude-haiku-4-5-20251001",
    )


def _talent() -> SimpleNamespace:
    return SimpleNamespace(
        display_name="山田",
        age=30,
        gender="男性",
        skills=["Java"],
        desired_rate=70,
        available_from="即日",
        work_style="リモート",
        nearest_station="東京",
        is_foreign_national=False,
        commerce_flow="プロパー",
        affiliation="正社員",
        summary="Java 経験",
    )


def _project() -> SimpleNamespace:
    return SimpleNamespace(
        title="保守案件",
        required_skills=["Java"],
        rate_min=60,
        rate_max=80,
        work_style="リモート",
        working_hours="10-19",
        location="東京",
        settlement_range="140-180",
        foreign_nationality_ng=False,
        commerce_flow_limit="一社先まで",
        summary="基幹保守",
    )


class AiJudgeGeminiPriorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ai_judge = _load_ai_judge_module()

    def test_gemini_is_called_first(self) -> None:
        payload = '{"ai_score": 77, "reason": "適合", "recommendation_points": "Java が整合"}'
        with patch.object(self.ai_judge, "_call_gemini", return_value=payload) as gemini:
            with patch.object(self.ai_judge, "_call_cursor") as cursor:
                with patch.object(self.ai_judge, "_call_openai") as openai:
                    with patch.object(self.ai_judge, "_call_claude") as claude:
                        score, reason, points = self.ai_judge._judge_with_llm(
                            _talent(), _project(), 60, _cfg()
                        )
        self.assertEqual(score, 77)
        self.assertEqual(reason, "適合")
        self.assertIn("Java", points)
        gemini.assert_called_once()
        cursor.assert_not_called()
        openai.assert_not_called()
        claude.assert_not_called()

    def test_falls_back_to_cursor_when_gemini_fails(self) -> None:
        payload = '{"ai_score": 66, "reason": "cursor", "recommendation_points": "早期参画"}'
        with patch.object(self.ai_judge, "_call_gemini", return_value=None):
            with patch.object(self.ai_judge, "_call_cursor", return_value=payload) as cursor:
                with patch.object(self.ai_judge, "_call_openai") as openai:
                    score, reason, _points = self.ai_judge._judge_with_llm(
                        _talent(), _project(), 60, _cfg()
                    )
        self.assertEqual(score, 66)
        self.assertEqual(reason, "cursor")
        cursor.assert_called_once()
        openai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
