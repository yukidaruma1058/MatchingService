"""ingest_dedup: 業務キー正規化。"""

from __future__ import annotations

import unittest

from app.ingest_dedup import normalize_business_key_part


class NormalizeBusinessKeyTests(unittest.TestCase):
    def test_trims_and_collapses_whitespace(self) -> None:
        self.assertEqual(normalize_business_key_part("  北  綾瀬駅  "), "北 綾瀬駅")

    def test_casefolds(self) -> None:
        self.assertEqual(normalize_business_key_part("ABC"), "abc")

    def test_none_and_blank_become_empty(self) -> None:
        self.assertEqual(normalize_business_key_part(None), "")
        self.assertEqual(normalize_business_key_part("   "), "")


if __name__ == "__main__":
    unittest.main()
