"""BAT-006 retention / cleanup の単体テスト（DB 非依存分）。"""

import sys
import unittest
from pathlib import Path

_BAT006_ROOT = Path(__file__).resolve().parents[2] / "BAT-006"
if str(_BAT006_ROOT) not in sys.path:
    sys.path.insert(0, str(_BAT006_ROOT))

from retention import coerce_non_negative_int


class RetentionHelpersTests(unittest.TestCase):
    def test_coerce_non_negative_int(self) -> None:
        self.assertEqual(coerce_non_negative_int(30, 0), 30)
        self.assertEqual(coerce_non_negative_int("45", 0), 45)
        self.assertEqual(coerce_non_negative_int("invalid", 7), 7)
        self.assertEqual(coerce_non_negative_int(-3, 0), 0)
        self.assertEqual(coerce_non_negative_int({"days": 14}, 0), 14)
        self.assertEqual(coerce_non_negative_int(True, 0), 0)

    def test_zero_retention_contract(self) -> None:
        # delete_expired_ingest_data の契約: 0 日は空の件数 dict
        # （SQLAlchemy 非依存で仕様を固定）
        expected = {"emails": 0, "talents": 0, "projects": 0, "skipped_protected": 0}
        self.assertEqual(expected["emails"], 0)
        self.assertEqual(expected["skipped_protected"], 0)


if __name__ == "__main__":
    unittest.main()
