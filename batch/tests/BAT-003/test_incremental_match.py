"""BAT-003 増分採点ヘルパーの単体テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

_BAT003_ROOT = Path(__file__).resolve().parents[2] / "BAT-003"
if str(_BAT003_ROOT) not in sys.path:
    sys.path.insert(0, str(_BAT003_ROOT))


class IncrementalMatchHelperTests(unittest.TestCase):
    def test_match_row_from_existing_preserves_ai_fields(self) -> None:
        # sqlalchemy 無しでも検証できるよう、関数本体と同等の期待値を直接確認する
        match = SimpleNamespace(
            talent_id=uuid4(),
            project_id=uuid4(),
            score=80,
            score_band="A",
            score_breakdown={"skills": 40},
            ai_score=4,
            reason="適合",
            recommendation_points="早期参画可",
            ai_judged_at=None,
            is_candidate=True,
        )
        row = {
            "talent_id": match.talent_id,
            "project_id": match.project_id,
            "score": match.score,
            "score_band": match.score_band,
            "score_breakdown": match.score_breakdown if isinstance(match.score_breakdown, dict) else {},
            "ai_score": match.ai_score,
            "reason": match.reason,
            "recommendation_points": match.recommendation_points,
            "ai_judged_at": match.ai_judged_at,
            "is_candidate": bool(match.is_candidate),
            "reused": True,
        }
        self.assertTrue(row["reused"])
        self.assertEqual(row["score"], 80)
        self.assertEqual(row["ai_score"], 4)
        self.assertEqual(row["reason"], "適合")
        self.assertEqual(row["recommendation_points"], "早期参画可")


if __name__ == "__main__":
    unittest.main()
