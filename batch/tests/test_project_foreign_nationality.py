"""案件の外国籍抽出: 未記載は None（可・不問にしない）。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.constraint_rules import (  # noqa: E402
    extract_project_constraint_fields,
    parse_project_foreign_nationality_ng,
)


class ProjectForeignNationalityTests(unittest.TestCase):
    def test_parse_unknown_is_none(self) -> None:
        self.assertIsNone(parse_project_foreign_nationality_ng(None))
        self.assertIsNone(parse_project_foreign_nationality_ng(""))
        self.assertIsNone(parse_project_foreign_nationality_ng("特に記載なし"))

    def test_parse_explicit_ok_and_ng(self) -> None:
        self.assertTrue(parse_project_foreign_nationality_ng("外国籍不可"))
        self.assertTrue(parse_project_foreign_nationality_ng("不可"))
        self.assertFalse(parse_project_foreign_nationality_ng("外国籍可"))
        self.assertFalse(parse_project_foreign_nationality_ng("可"))

    def test_extract_without_mention_is_none(self) -> None:
        body = """
【案件名】：飲料メーカー向け保守
【作業内容】：保守対応
【必要スキル】：Java
"""
        foreign_ng, _ = extract_project_constraint_fields({}, body)
        self.assertIsNone(foreign_ng)

    def test_extract_bracket_ng(self) -> None:
        body = "【外国籍】：不可\n【商流】：一社先まで"
        fields = {"外国籍": "不可", "商流": "一社先まで"}
        foreign_ng, commerce = extract_project_constraint_fields(fields, body)
        self.assertTrue(foreign_ng)
        self.assertEqual(commerce, "一社先まで")

    def test_explicit_ok_not_overwritten_by_body(self) -> None:
        # False を or で潰さないこと
        fields = {"外国籍": "可"}
        body = "本文に日本人のみという言葉があるが項目が優先"
        foreign_ng, _ = extract_project_constraint_fields(fields, body)
        self.assertFalse(foreign_ng)


if __name__ == "__main__":
    unittest.main()
