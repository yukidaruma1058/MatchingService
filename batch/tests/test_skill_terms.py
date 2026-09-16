"""スキル文の技術名切り出しと工程の以降展開。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.skill_terms import expand_skill_items, expand_skill_term, expand_skills_from_text


class SkillTermsTests(unittest.TestCase):
    def test_java_sentence_extracts_tech_name(self) -> None:
        self.assertEqual(expand_skill_term("Java開発の経験5年程度"), ["Java"])

    def test_basic_design_onward_expands_phases(self) -> None:
        self.assertEqual(
            expand_skill_term("基本設計以降のご経験"),
            ["基本設計", "詳細設計", "製造", "単体試験", "結合試験", "システム試験", "リリース"],
        )

    def test_detail_design_onward_excludes_basic_design(self) -> None:
        self.assertEqual(
            expand_skill_term("詳細設計以降"),
            ["詳細設計", "製造", "単体試験", "結合試験", "システム試験", "リリース"],
        )

    def test_plain_phase_stays_single(self) -> None:
        self.assertEqual(expand_skill_term("基本設計"), ["基本設計"])
        self.assertEqual(expand_skill_term("詳細設計"), ["詳細設計"])

    def test_unknown_sentence_kept(self) -> None:
        raw = "複数プロダクトの提案（クロスセル）のご経験"
        self.assertEqual(expand_skill_term(raw), [raw])

    def test_expand_items_dedupes_and_merges(self) -> None:
        self.assertEqual(
            expand_skill_items(["Java開発の経験5年程度", "基本設計以降のご経験", "Java"]),
            ["Java", "基本設計", "詳細設計", "製造", "単体試験", "結合試験", "システム試験", "リリース"],
        )

    def test_javascript_does_not_become_java(self) -> None:
        self.assertEqual(expand_skill_term("JavaScript"), ["JavaScript"])
        self.assertNotIn("Java", expand_skill_term("JavaScript経験3年"))

    def test_summary_detail_design_onward(self) -> None:
        self.assertEqual(
            expand_skills_from_text("詳細設計以降の工程を自走できます。"),
            ["詳細設計", "製造", "単体試験", "結合試験", "システム試験", "リリース"],
        )

    def test_integration_and_system_tests_stay_separate(self) -> None:
        self.assertEqual(expand_skill_term("結合試験"), ["結合試験"])
        self.assertEqual(expand_skill_term("システム試験"), ["システム試験"])
        self.assertEqual(expand_skill_term("結合テスト"), ["結合試験"])
        self.assertEqual(expand_skill_term("システムテスト"), ["システム試験"])
        self.assertEqual(expand_skill_term("総合試験"), ["システム試験"])
        self.assertEqual(
            expand_skill_term("結合試験以降"),
            ["結合試験", "システム試験", "リリース"],
        )
        self.assertNotIn("試験", expand_skill_term("結合試験"))
        self.assertNotIn("試験", expand_skill_term("システム試験"))


if __name__ == "__main__":
    unittest.main()
