"""BAT-003 scorer / Routes ヘルパーの単体テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BAT003_ROOT = Path(__file__).resolve().parents[2] / "BAT-003"
_BATCH_ROOT = Path(__file__).resolve().parents[2]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))
if str(_BAT003_ROOT) not in sys.path:
    sys.path.insert(0, str(_BAT003_ROOT))

from google_routes import parse_duration_seconds, to_address_query  # noqa: E402
from scorer import (  # noqa: E402
    is_full_remote,
    prepare_project_skills,
    prepare_talent_skills,
    score_band_for,
    score_pair,
    score_pair_job,
    score_rate,
    score_skills,
)


class ScorerTests(unittest.TestCase):
    def test_skill_partial_match(self) -> None:
        points, hits = score_skills(["Java", "Spring Boot"], ["Java", "PostgreSQL"])
        self.assertEqual(points, 15)
        self.assertIn("java", hits)

    def test_skill_java_does_not_match_javascript(self) -> None:
        points, hits = score_skills(["JavaScript"], ["Java"])
        self.assertEqual(points, 0)
        self.assertEqual(hits, [])

    def test_skill_empty_required_neutral(self) -> None:
        points, _ = score_skills(["Java"], [])
        self.assertEqual(points, 15)

    def test_skill_empty_talent_zero(self) -> None:
        points, _ = score_skills([], ["Java"])
        self.assertEqual(points, 0)

    def test_skill_sentence_and_phase_onward(self) -> None:
        points, hits = score_skills(
            ["Java", "基本設計", "詳細設計"],
            ["Java開発の経験5年程度", "基本設計以降のご経験"],
            max_points=30,
        )
        self.assertIn("java", hits)
        self.assertIn("基本設計", hits)
        self.assertIn("詳細設計", hits)
        self.assertNotIn("製造", hits)
        self.assertEqual(points, 11)

    def test_preferred_skills_add_points(self) -> None:
        with_hit = score_pair(
            talent_skills=["Java", "AWS"],
            required_skills=["Java"],
            preferred_skills=["AWS"],
            desired_rate=65,
            rate_min=60,
            rate_max=70,
            available_from="8月～",
            start_date="8月～長期",
            talent_work_style="常駐可",
            project_work_style="週3日出社",
        )
        without_hit = score_pair(
            talent_skills=["Java"],
            required_skills=["Java"],
            preferred_skills=["AWS"],
            desired_rate=65,
            rate_min=60,
            rate_max=70,
            available_from="8月～",
            start_date="8月～長期",
            talent_work_style="常駐可",
            project_work_style="週3日出社",
        )
        self.assertEqual(with_hit.breakdown["skill_preferred"], 15)
        self.assertEqual(without_hit.breakdown["skill_preferred"], 0)
        self.assertGreater(with_hit.score, without_hit.score)

    def test_talent_summary_phases_count(self) -> None:
        result = score_pair(
            talent_skills=["Java"],
            required_skills=["詳細設計以降"],
            preferred_skills=[],
            talent_summary="詳細設計以降の工程を自走できます。",
            desired_rate=65,
            rate_min=60,
            rate_max=70,
            available_from="8月～",
            start_date="8月～長期",
            talent_work_style="常駐可",
            project_work_style="週3日出社",
        )
        self.assertEqual(result.breakdown["skill_required"], 30)
        self.assertIn("詳細設計", result.breakdown["skill_hits"])

    def test_rate_in_range(self) -> None:
        self.assertEqual(score_rate(65, 60, 70), 30)

    def test_rate_over(self) -> None:
        self.assertEqual(score_rate(73, 60, 70), 23)  # +1〜5
        self.assertEqual(score_rate(78, 60, 70), 15)  # +6〜10
        self.assertEqual(score_rate(82, 60, 70), 0)  # +11以上
        self.assertEqual(score_rate(None, 60, 70), 17)

    def test_score_band(self) -> None:
        self.assertEqual(score_band_for(95), "90-100")
        self.assertEqual(score_band_for(83), "80-89")
        self.assertEqual(score_band_for(5), "0-9")

    def test_score_pair_without_commute(self) -> None:
        result = score_pair(
            talent_skills=["Java", "Spring Boot"],
            required_skills=["Java", "PostgreSQL"],
            desired_rate=65,
            rate_min=60,
            rate_max=70,
            available_from="8月～",
            start_date="8月～長期",
            talent_work_style="常駐可",
            project_work_style="週3日出社",
        )
        self.assertNotIn("commute", result.breakdown)
        self.assertEqual(result.breakdown["skill"], 22)
        self.assertEqual(result.breakdown["rate"], 30)
        self.assertTrue(60 <= result.score <= 100)

    def test_prepared_skills_match_inline(self) -> None:
        prepared = prepare_talent_skills(["Java", "AWS"], None)
        inline = score_pair(
            talent_skills=["Java", "AWS"],
            required_skills=["Java"],
            preferred_skills=["AWS"],
            desired_rate=65,
            rate_min=60,
            rate_max=70,
            available_from="8月～",
            start_date="8月～長期",
            talent_work_style="常駐可",
            project_work_style="週3日出社",
        )
        via_job = score_pair_job(
            {
                "talent_id": "t1",
                "project_id": "p1",
                "talent_skills_prepared": prepared,
                "required_skills_prepared": prepare_project_skills(["Java"]),
                "preferred_skills_prepared": prepare_project_skills(["AWS"]),
                "desired_rate": 65,
                "rate_min": 60,
                "rate_max": 70,
                "available_from": "8月～",
                "start_date": "8月～長期",
                "talent_work_style": "常駐可",
                "project_work_style": "週3日出社",
            }
        )
        self.assertEqual(via_job["score"], inline.score)
        self.assertEqual(via_job["score_breakdown"]["skill_preferred"], 15)

    def test_full_remote_has_no_commute_points(self) -> None:
        self.assertTrue(is_full_remote("フルリモート"))
        result = score_pair(
            talent_skills=["Java"],
            required_skills=["Java"],
            desired_rate=70,
            rate_min=60,
            rate_max=80,
            available_from="即日",
            start_date="即日",
            talent_work_style="リモート可",
            project_work_style="フルリモート",
        )
        self.assertNotIn("commute", result.breakdown)

    def test_duration_parse(self) -> None:
        self.assertEqual(parse_duration_seconds("4200s"), 4200)
        self.assertIsNone(parse_duration_seconds("bad"))

    def test_address_query(self) -> None:
        self.assertIn("駅", to_address_query("北綾瀬", as_station=True))

    def test_hard_reject_foreign_nationality(self) -> None:
        result = score_pair(
            talent_skills=["Java"],
            required_skills=["Java"],
            desired_rate=65,
            rate_min=60,
            rate_max=70,
            available_from="8月～",
            start_date="8月～長期",
            talent_work_style="常駐可",
            project_work_style="週3日出社",
            project_foreign_nationality_ng=True,
            talent_is_foreign_national=True,
        )
        self.assertEqual(result.score, 0)
        self.assertEqual(result.breakdown["hard_reject"], "foreign_nationality")
        self.assertIn("外国籍", result.breakdown["hard_reject_label"])

    def test_commerce_flow_does_not_hard_reject(self) -> None:
        result = score_pair(
            talent_skills=["Java"],
            required_skills=["Java"],
            desired_rate=65,
            rate_min=60,
            rate_max=70,
            available_from="8月～",
            start_date="8月～長期",
            talent_work_style="常駐可",
            project_work_style="週3日出社",
            project_commerce_flow_limit="一社先まで",
            talent_commerce_flow="二社先",
        )
        self.assertGreater(result.score, 0)
        self.assertNotIn("hard_reject", result.breakdown)

    def test_hard_reject_skips_when_talent_nationality_unknown(self) -> None:
        result = score_pair(
            talent_skills=["Java"],
            required_skills=["Java"],
            desired_rate=65,
            rate_min=60,
            rate_max=70,
            available_from="8月～",
            start_date="8月～長期",
            talent_work_style="常駐可",
            project_work_style="週3日出社",
            project_foreign_nationality_ng=True,
            talent_is_foreign_national=None,
        )
        self.assertGreater(result.score, 0)
        self.assertNotIn("hard_reject", result.breakdown)


if __name__ == "__main__":
    unittest.main()
