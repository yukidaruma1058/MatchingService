"""AI 採点プロンプトへのスキルシート経験反映のテスト。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


def _load_ai_judge_module():
    root = Path(__file__).resolve().parents[1]
    path = root / "BAT-004" / "ai_judge.py"
    spec = importlib.util.spec_from_file_location("bat004_ai_judge_prompt_test", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class AiJudgeSkillSheetPromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ai_judge = _load_ai_judge_module()

    def test_prompt_includes_experience_and_skill_instructions(self) -> None:
        talent = SimpleNamespace(
            display_name="T.山田",
            age=35,
            gender="男性",
            skills=["Java", "AWS"],
            desired_rate=600000,
            available_from="即日",
            work_style="リモート",
            nearest_station="渋谷",
            is_foreign_national=False,
            commerce_flow="1社先",
            affiliation="正社員",
            summary="バックエンド経験10年",
        )
        project = SimpleNamespace(
            title="基幹 API 開発",
            required_skills=["Java", "Spring"],
            rate_min=60,
            rate_max=80,
            work_style="リモート",
            working_hours="9-18",
            location="東京",
            settlement_range="140-180",
            foreign_nationality_ng=False,
            commerce_flow_limit="2社先まで",
            summary="既存 API のリプレイスと新規マイクロサービス開発",
        )
        experience = "2021-2023 金融系 Java/Spring で API 刷新"
        prompt = self.ai_judge._build_llm_judge_prompt(
            talent,
            project,
            72,
            commerce_flow_adjusted="1社先",
            skill_sheet_experience=experience,
        )
        self.assertIn(experience, prompt)
        self.assertIn("スキルシート経験（抜粋）", prompt)
        self.assertIn("必須スキルとスキルシート経験の評価", prompt)
        self.assertIn("業務内容", prompt)
        self.assertIn("既存 API", prompt)

    def test_prompt_without_experience_shows_placeholder(self) -> None:
        talent = SimpleNamespace(
            display_name="T",
            age=None,
            gender=None,
            skills=[],
            desired_rate=None,
            available_from=None,
            work_style=None,
            nearest_station=None,
            is_foreign_national=None,
            commerce_flow=None,
            affiliation=None,
            summary=None,
        )
        project = SimpleNamespace(
            title="P",
            required_skills=["Go"],
            rate_min=None,
            rate_max=None,
            work_style=None,
            working_hours=None,
            location=None,
            settlement_range=None,
            foreign_nationality_ng=None,
            commerce_flow_limit=None,
            summary="開発",
        )
        prompt = self.ai_judge._build_llm_judge_prompt(talent, project, 50, skill_sheet_experience=None)
        self.assertIn("なし（メール情報のみ）", prompt)


if __name__ == "__main__":
    unittest.main()
