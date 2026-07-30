"""人材提案おすすめポイントの解決・表示テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BATCH_ROOT = Path(__file__).resolve().parents[2]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.outreach_templates import (
    ProjectProposeLine,
    TalentProposeLine,
    format_project_items,
    format_talent_items,
)
from app.talent_recommendation import resolve_recommendation_points


class TalentRecommendationTests(unittest.TestCase):
    def test_format_project_includes_recommendation_points(self) -> None:
        text = format_project_items(
            [
                ProjectProposeLine(
                    title="案件A",
                    required_skills=["Java"],
                    rate_min=60,
                    rate_max=70,
                    work_style="リモート",
                    start_date="即日",
                    score=80,
                    recommendation_points="スキル適合が高く早期参画が期待できます。",
                )
            ]
        )
        self.assertIn("おすすめポイント", text)
        self.assertIn("早期参画", text)

    def test_format_omits_recommendation_when_missing(self) -> None:
        text = format_talent_items(
            [
                TalentProposeLine(
                    display_name="山田",
                    skills=["Java"],
                    desired_rate=60,
                    available_from="即日",
                    score=80,
                    recommendation_points=None,
                )
            ]
        )
        self.assertNotIn("おすすめポイント", text)

    def test_format_talent_includes_nationality_and_commerce_flow(self) -> None:
        text = format_talent_items(
            [
                TalentProposeLine(
                    display_name="山田",
                    skills=["Java"],
                    desired_rate=60,
                    available_from="即日",
                    score=80,
                    is_foreign_national=False,
                    commerce_flow="一社先",
                ),
                TalentProposeLine(
                    display_name="佐藤",
                    skills=["AWS"],
                    desired_rate=70,
                    available_from="来月",
                    score=70,
                    is_foreign_national=None,
                    commerce_flow=None,
                ),
            ]
        )
        self.assertIn("国籍: 日本国籍", text)
        self.assertIn("商流: 一社先", text)
        self.assertNotIn("国籍: 未記入", text)
        self.assertNotIn("商流: 未記入", text)
        # 佐藤分は国籍・商流が未設定のため行ごと省略
        sato_block = text.split("【2】佐藤", 1)[1]
        self.assertNotIn("国籍:", sato_block.split("\n\n", 1)[0])
        self.assertNotIn("商流:", sato_block.split("\n\n", 1)[0])

    def test_format_talent_shows_desired_rate_without_markup(self) -> None:
        text = format_talent_items(
            [
                TalentProposeLine(
                    display_name="山田",
                    skills=["Java"],
                    desired_rate=60,
                    available_from="即日",
                    score=80,
                )
            ],
        )
        self.assertIn("単価: 60万円", text)

    def test_format_project_applies_rate_markdown(self) -> None:
        text = format_project_items(
            [
                ProjectProposeLine(
                    title="案件A",
                    required_skills=["Java"],
                    rate_min=60,
                    rate_max=70,
                    work_style="リモート",
                    start_date="即日",
                    score=80,
                )
            ],
            rate_markdown_man_yen=5,
        )
        self.assertIn("単価帯: 55〜65万円", text)
        self.assertNotIn("60〜70万円", text)

    def test_format_project_includes_constraints_and_summary(self) -> None:
        text = format_project_items(
            [
                ProjectProposeLine(
                    title="案件A",
                    required_skills=["Java"],
                    rate_min=60,
                    rate_max=70,
                    work_style="リモート",
                    start_date="即日",
                    score=80,
                    foreign_nationality_ng=True,
                    commerce_flow_limit="一社先まで",
                    interview_count=2,
                    summary="基幹システムの保守・改修。",
                ),
                ProjectProposeLine(
                    title="案件B",
                    required_skills=["AWS"],
                    rate_min=50,
                    rate_max=60,
                    work_style=None,
                    start_date=None,
                    score=70,
                    foreign_nationality_ng=None,
                    commerce_flow_limit=None,
                    interview_count=None,
                    summary=None,
                ),
            ]
        )
        self.assertIn("外国籍: 不可", text)
        self.assertIn("商流制限: 一社先まで", text)
        self.assertIn("面談回数: 2回", text)
        self.assertIn("案件概要: 基幹システムの保守・改修。", text)
        b_block = text.split("【2】案件B", 1)[1]
        self.assertNotIn("外国籍:", b_block.split("\n\n", 1)[0])
        self.assertNotIn("商流制限:", b_block.split("\n\n", 1)[0])
        self.assertNotIn("面談回数:", b_block.split("\n\n", 1)[0])
        self.assertNotIn("案件概要:", b_block.split("\n\n", 1)[0])

    def test_format_includes_recommendation_points(self) -> None:
        text = format_talent_items(
            [
                TalentProposeLine(
                    display_name="山田",
                    skills=["Java"],
                    desired_rate=60,
                    available_from="即日",
                    score=80,
                    recommendation_points="Java案件での即戦力としてご提案できます。",
                )
            ]
        )
        self.assertIn("おすすめポイント", text)
        self.assertIn("即戦力", text)

    def test_resolve_only_stored(self) -> None:
        self.assertEqual(
            resolve_recommendation_points(
                stored="保存済みのおすすめ",
                display_name="佐藤",
                skills=["AWS"],
                reason="評価理由",
            ),
            "保存済みのおすすめ",
        )
        self.assertIsNone(
            resolve_recommendation_points(
                stored=None,
                display_name="鈴木",
                skills=["Java"],
                reason="必須スキルが一致しています。",
            )
        )


if __name__ == "__main__":
    unittest.main()
