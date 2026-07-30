"""AI判定ヘルパーのユニットテスト（依存なし）。"""

from __future__ import annotations

import unittest


def score_band_for(score: int) -> str:
    clamped = max(0, min(100, int(score)))
    if clamped >= 90:
        return "90-100"
    low = (clamped // 10) * 10
    if low == 0:
        return "0-9"
    return f"{low}-{low + 9}"


class AiJudgeHelperTests(unittest.TestCase):
    def test_score_band_zero(self) -> None:
        self.assertEqual(score_band_for(0), "0-9")

    def test_score_band_high(self) -> None:
        self.assertEqual(score_band_for(95), "90-100")


if __name__ == "__main__":
    unittest.main()
