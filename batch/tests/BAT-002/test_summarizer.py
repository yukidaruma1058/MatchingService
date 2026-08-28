"""BAT-002 summarizer の単体テスト（AI 呼び出しなし）。"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_BAT002_ROOT = Path(__file__).resolve().parents[2] / "BAT-002"
if str(_BAT002_ROOT) not in sys.path:
    sys.path.insert(0, str(_BAT002_ROOT))

from summarizer import (  # noqa: E402
    _parse_json_object,
    _rule_extract_project,
    _rule_extract_talent,
    extract_email_fields,
)


SAMPLE_PROJECT_BODY = """
株式会社Kanana ご担当者様
いつもお世話になっております。
ーーーーーーー案件情報ーーーーーーー
【案件名】：飲料メーカー向け保守業務
【作業期間】：8月～長期（3年以上）
【作業場所】：お台場（※基本フルリモート、月1回程度打合せ有）
【作業形態】：基本フルリモート（月1回程度出社有）
【面談回数】：2回
【人数】：1名
【外国籍】：不可
【商　流】：一社先まで
【作業内容】：
・飲料メーカー向け基幹システムの保守対応
・障害調査と軽微な改修
【主な環境(言語・ツール)】：
・Java
・PostgreSQL
・Oracle
【必要スキル】：
・Javaでの実務経験5年以上
・PostgreSQLでの開発経験
"""

SAMPLE_ASTRO_TALENT_BODY = """
株式会社Kanana　様

お世話になっております。
アストロ中村でございます。

ーーーーーーーーーーーーーー
◆【Astro?人材】◆中上級PG◆・JAVA・Spring Boot・＠北綾瀬
---------------------------------------------------------------------
【名　前】ST　プロパー(コアパートナー所属)
【年　齢】25歳
【性　別】男性
【最寄駅】北綾瀬駅
【稼動日】8月～
【単　金】65～70万円　※★不可の場合、ご相談可

【スキル】実務経験：4.5年
　　　　　Java、Spring Boot

【備　考】詳細設計以降の工程を自走できます。
---------------------------------------------------------------------

以上、宜しくお願い致します。

＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝＝
株式会社アストロ　Astro Co.,Ltd.
担当：中村
"""


class SummarizerTests(unittest.TestCase):
    def test_parse_json_object_with_fence(self) -> None:
        payload = _parse_json_object('```json\n{"display_name":"山田","skills":["Java"]}\n```')
        self.assertEqual(payload, {"display_name": "山田", "skills": ["Java"]})

    def test_rule_extract_project_from_jp_template(self) -> None:
        data = _rule_extract_project(
            "【ML◎注力案件】Java/PostgreSQL　長期保守案件",
            SAMPLE_PROJECT_BODY,
        )
        self.assertEqual(data["title"], "飲料メーカー向け保守業務")
        self.assertIn("お台場", data["location"] or "")
        self.assertIn("フルリモート", data["work_style"] or "")
        self.assertTrue(any("Java" in s for s in data["required_skills"]))
        self.assertTrue(any("PostgreSQL" in s for s in data["required_skills"]))
        self.assertTrue(data["foreign_nationality_ng"])
        self.assertEqual(data["commerce_flow_limit"], "一社先まで")
        self.assertEqual(data["interview_count"], 2)
        self.assertEqual(data["headcount"], 1)
        self.assertIn("保守対応", data["summary"])
        self.assertNotIn("外国籍不可", data["summary"])
        self.assertNotIn("商流:", data["summary"])

    def test_rule_extract_talent_rate_with_spaced_key(self) -> None:
        body = """
【氏　名】：山田太郎
【所　属】：フリーランス
【稼　働】：即日
【単　金】：65～70万円　※★不可の場合、ご相談可
【スキル】：Java / Spring
"""
        data = _rule_extract_talent("人材ご紹介", body)
        self.assertEqual(data["display_name"], "山田太郎")
        self.assertEqual(data["affiliation"], "フリーランス")
        self.assertEqual(data["available_from"], "即日")
        self.assertEqual(data["desired_rate"], 65)
        self.assertIsNone(data["summary"])

    def test_rule_extract_astro_talent_template(self) -> None:
        data = _rule_extract_talent(
            "◆【Astro?人材】◆中上級PG◆・JAVA・Spring Boot・＠北綾瀬",
            SAMPLE_ASTRO_TALENT_BODY,
        )
        self.assertEqual(data["display_name"], "ST")
        self.assertEqual(data["affiliation"], "プロパー(コアパートナー所属)")
        self.assertEqual(data["available_from"], "8月～")
        self.assertEqual(data["desired_rate"], 65)
        self.assertEqual(data["nearest_station"], "北綾瀬駅")
        self.assertEqual(data["age"], 25)
        self.assertEqual(data["gender"], "男性")
        self.assertEqual(data["experience_years"], 4)
        self.assertEqual(data["source_company_name"], "株式会社アストロ")
        self.assertIn("自走", data["summary"] or "")
        self.assertTrue(any("Java" in s for s in data["skills"]))
        self.assertTrue(any("Spring Boot" in s for s in data["skills"]))
        self.assertFalse(any(s.startswith("実務経験") for s in data["skills"]))

    def test_heuristic_project_fills_fields(self) -> None:
        cfg = SimpleNamespace(
            cursor_api_key="",
            openai_api_key="",
            openai_model="gpt-4o-mini",
            anthropic_api_key="",
            anthropic_model="claude-haiku-4-5-20251001",
        )
        result = extract_email_fields(
            "project",
            "【ML◎注力案件】Java/PostgreSQL　長期保守案件",
            SAMPLE_PROJECT_BODY,
            cfg,  # type: ignore[arg-type]
        )
        self.assertEqual(result.provider, "heuristic")
        self.assertEqual(result.data["title"], "飲料メーカー向け保守業務")
        self.assertTrue(result.data["required_skills"])
        self.assertTrue(result.data["location"])

    def test_heuristic_astro_talent(self) -> None:
        cfg = SimpleNamespace(
            cursor_api_key="",
            openai_api_key="",
            openai_model="gpt-4o-mini",
            anthropic_api_key="",
            anthropic_model="claude-haiku-4-5-20251001",
        )
        result = extract_email_fields(
            "talent",
            "◆【Astro?人材】◆中上級PG◆・JAVA・Spring Boot・＠北綾瀬",
            SAMPLE_ASTRO_TALENT_BODY,
            cfg,  # type: ignore[arg-type]
            from_header="株式会社アストロ <sales@astro.example>",
        )
        self.assertEqual(result.provider, "heuristic")
        self.assertEqual(result.data["display_name"], "ST")
        self.assertEqual(result.data["affiliation"], "プロパー(コアパートナー所属)")
        self.assertEqual(result.data["available_from"], "8月～")
        self.assertEqual(result.data["source_company_name"], "株式会社アストロ")


if __name__ == "__main__":
    unittest.main()
