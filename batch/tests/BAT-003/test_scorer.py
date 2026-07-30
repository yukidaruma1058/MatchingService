"""BAT-003 scorer / Routes ヘルパーの単体テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BAT003_ROOT = Path(__file__).resolve().parents[2] / "BAT-003"
if str(_BAT003_ROOT) not in sys.path:
    sys.path.insert(0, str(_BAT003_ROOT))

from google_routes import parse_duration_seconds, to_address_query  # noqa: E402
from scorer import (  # noqa: E402
    is_full_remote,
    score_band_for,
    score_commute_minutes,
    score_pair,
    score_rate,
    score_skills,
)


class ScorerTests(unittest.TestCase):
    def test_skill_partial_match(self) -> None:
        points, hits = score_skills(["Java", "Spring Boot"], ["Java", "PostgreSQL"])
        self.assertEqual(points, 20)
        self.assertIn("java", hits)

    def test_skill_java_does_not_match_javascript(self) -> None:
        points, hits = score_skills(["JavaScript"], ["Java"])
        self.assertEqual(points, 0)
        self.assertEqual(hits, [])

    def test_skill_empty_required_neutral(self) -> None:
        points, _ = score_skills(["Java"], [])
        self.assertEqual(points, 20)

    def test_skill_empty_talent_zero(self) -> None:
        points, _ = score_skills([], ["Java"])
        self.assertEqual(points, 0)

    def test_rate_in_range(self) -> None:
        self.assertEqual(score_rate(65, 60, 70), 25)

    def test_rate_over(self) -> None:
        self.assertEqual(score_rate(73, 60, 70), 18)  # +1〜5
        self.assertEqual(score_rate(78, 60, 70), 10)  # +6〜10
        self.assertEqual(score_rate(82, 60, 70), 0)  # +11以上

    def test_commute_bands(self) -> None:
        self.assertEqual(score_commute_minutes(40), 10)
        self.assertEqual(score_commute_minutes(55), 8)
        self.assertEqual(score_commute_minutes(80), 5)
        self.assertEqual(score_commute_minutes(100), 2)
        self.assertEqual(score_commute_minutes(150), 0)
        self.assertEqual(score_commute_minutes(None), 5)
        self.assertEqual(score_commute_minutes(None, full_remote=True), 10)

    def test_score_band(self) -> None:
        self.assertEqual(score_band_for(95), "90-100")
        self.assertEqual(score_band_for(83), "80-89")
        self.assertEqual(score_band_for(5), "0-9")

    def test_pass1_commute_neutral(self) -> None:
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
            commute_resolved=False,
        )
        self.assertEqual(result.breakdown["commute"], 5)
        self.assertEqual(result.breakdown["skill"], 20)
        self.assertEqual(result.breakdown["rate"], 25)
        self.assertTrue(60 <= result.score <= 100)

    def test_full_remote_commute_full(self) -> None:
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
            commute_resolved=True,
        )
        self.assertEqual(result.breakdown["commute"], 10)

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
            commute_resolved=False,
            project_foreign_nationality_ng=True,
            talent_is_foreign_national=True,
        )
        self.assertEqual(result.score, 0)
        self.assertEqual(result.breakdown["hard_reject"], "foreign_nationality")
        self.assertIn("外国籍", result.breakdown["hard_reject_label"])

    def test_hard_reject_commerce_flow(self) -> None:
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
            commute_resolved=False,
            project_commerce_flow_limit="一社先まで",
            talent_commerce_flow="二社先",
        )
        self.assertEqual(result.score, 0)
        self.assertEqual(result.breakdown["hard_reject"], "commerce_flow")

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
            commute_resolved=False,
            project_foreign_nationality_ng=True,
            talent_is_foreign_national=None,
        )
        self.assertGreater(result.score, 0)
        self.assertNotIn("hard_reject", result.breakdown)


if __name__ == "__main__":
    unittest.main()
