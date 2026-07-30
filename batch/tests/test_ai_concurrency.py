"""ai_concurrency ヘルパーのユニットテスト。"""

from __future__ import annotations

import time
import unittest

from app.ai_concurrency import map_parallel, resolve_ai_concurrency


class AiConcurrencyTests(unittest.TestCase):
    def test_resolve_clamps(self) -> None:
        self.assertEqual(resolve_ai_concurrency(0), 1)
        self.assertEqual(resolve_ai_concurrency(1), 1)
        self.assertEqual(resolve_ai_concurrency(3), 3)
        self.assertEqual(resolve_ai_concurrency(9), 4)
        self.assertEqual(resolve_ai_concurrency(None), 3)

    def test_map_parallel_preserves_order(self) -> None:
        def work(n: int) -> int:
            time.sleep(0.05 if n % 2 == 0 else 0.01)
            return n * 10

        got = map_parallel([1, 2, 3, 4], work, concurrency=3)
        self.assertEqual(got, [10, 20, 30, 40])

    def test_map_parallel_serial_when_one(self) -> None:
        calls: list[int] = []

        def work(n: int) -> int:
            calls.append(n)
            return n

        self.assertEqual(map_parallel([7], work, concurrency=3), [7])
        self.assertEqual(calls, [7])


if __name__ == "__main__":
    unittest.main()
