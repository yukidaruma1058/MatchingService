"""AI採点・ルール採点共用のハード制約判定テスト。"""

from __future__ import annotations

import unittest

from app.constraint_rules import evaluate_match_hard_constraints, hard_reject_label


class EvaluateMatchHardConstraintsTests(unittest.TestCase):
    def test_commerce_reject_for_ai_path(self) -> None:
        code, adjusted = evaluate_match_hard_constraints(
            own_company_name="株式会社Kanana",
            talent_company_name="A社",
            affiliation="正社員",
            commerce_flow=None,
            talent_is_foreign_national=False,
            project_foreign_nationality_ng=False,
            project_commerce_flow_limit="貴社まで",
        )
        self.assertEqual(adjusted, "一社先正社員")
        self.assertEqual(code, "commerce_flow")
        self.assertIn("商流", hard_reject_label(code) or "")

    def test_foreign_nationality_reject_for_ai_path(self) -> None:
        code, adjusted = evaluate_match_hard_constraints(
            own_company_name="株式会社Kanana",
            talent_company_name="株式会社Kanana",
            affiliation="正社員",
            commerce_flow=None,
            talent_is_foreign_national=True,
            project_foreign_nationality_ng=True,
            project_commerce_flow_limit="貴社まで",
        )
        self.assertEqual(adjusted, "プロパー")
        self.assertEqual(code, "foreign_nationality")
        self.assertIn("外国籍", hard_reject_label(code) or "")

    def test_passes_when_ok(self) -> None:
        code, adjusted = evaluate_match_hard_constraints(
            own_company_name="株式会社Kanana",
            talent_company_name="株式会社Kanana",
            affiliation="正社員",
            commerce_flow=None,
            talent_is_foreign_national=False,
            project_foreign_nationality_ng=True,
            project_commerce_flow_limit="貴社まで",
        )
        self.assertEqual(adjusted, "プロパー")
        self.assertIsNone(code)


if __name__ == "__main__":
    unittest.main()
