"""BAT-002 summarizer の単体テスト（AI 呼び出しなし）。"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

_BAT002_ROOT = Path(__file__).resolve().parents[2] / "BAT-002"
if str(_BAT002_ROOT) not in sys.path:
    sys.path.insert(0, str(_BAT002_ROOT))

from summarizer import (  # noqa: E402
    _finalize_with_rules,
    _normalize_project,
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
        self.assertIn("軽微な改修", data["summary"])
        self.assertNotIn("外国籍不可", data["summary"])
        self.assertNotIn("商流:", data["summary"])

    def test_normalize_project_drops_placeholder_project_code(self) -> None:
        data, _needs_review = _normalize_project(
            {
                "title": "テスト案件",
                "project_code": "要確認",
                "required_skills": ["Java"],
                "summary": "業務A",
            },
            subject="件名",
        )
        self.assertIsNone(data["project_code"])

        kept, _ = _normalize_project(
            {
                "title": "テスト案件",
                "project_code": "PJ-001",
                "required_skills": ["Java"],
                "summary": "業務A",
            },
            subject="件名",
        )
        self.assertEqual(kept["project_code"], "PJ-001")

    def test_rule_extract_project_preferred_skills(self) -> None:
        body = """
【案件名】：テスト案件
【作業内容】：
・業務A
【必要スキル】：
・Java
【尚可スキル】：
・AWS
・Docker
"""
        data = _rule_extract_project("件名", body)
        self.assertTrue(any("Java" in s for s in data["required_skills"]))
        self.assertTrue(any("AWS" in s for s in data["preferred_skills"]))
        self.assertTrue(any("Docker" in s for s in data["preferred_skills"]))
        self.assertNotIn("AWS", data["required_skills"])

    def test_rule_extract_expands_java_years_and_phase_onward(self) -> None:
        body = """
【案件名】：テスト案件
【作業内容】：
・業務A
【必要スキル】：
・Java開発の経験5年程度
・基本設計以降のご経験
"""
        data = _rule_extract_project("件名", body)
        self.assertEqual(data["required_skills"][0], "Java")
        self.assertIn("基本設計", data["required_skills"])
        self.assertIn("詳細設計", data["required_skills"])
        self.assertIn("製造", data["required_skills"])
        self.assertIn("単体試験", data["required_skills"])
        self.assertIn("結合試験", data["required_skills"])
        self.assertIn("システム試験", data["required_skills"])
        self.assertNotIn("試験", data["required_skills"])
        self.assertIn("リリース", data["required_skills"])
        self.assertFalse(any("5年" in s for s in data["required_skills"]))

    def test_preferred_skills_stop_at_square_headers_and_signature(self) -> None:
        body = """
【案件名】：HR SaaS提案支援
【必要スキル】：
・提案経験
【尚可】
・複数プロダクトの提案（クロスセル）のご経験
・HRsaas経験
・FSのご経験：1年以上
■稼働開始日：
9月～
■備考：
契約形態：準委任契約
商流：貴社迄
商談回数：2回
https://www.b-tm.co.jp
株式会社 BTM（グロース市場　証券コード：5247）
DX推進事業本部　ITエンジニアリング事業部　東京IT人材営業グループ
▼ITフリーランス向け案件紹介サイト▼
「ジョブリーフリーランス」 https://jobree-freelance.jp
TEL：03-5784-0456 FAX：03-5784-0455
"""
        data = _rule_extract_project("件名", body)
        self.assertEqual(
            data["preferred_skills"],
            [
                "複数プロダクトの提案（クロスセル）のご経験",
                "HRsaas経験",
                "FSのご経験：1年以上",
            ],
        )
        joined = " / ".join(data["preferred_skills"])
        self.assertNotIn("稼働開始日", joined)
        self.assertNotIn("備考", joined)
        self.assertNotIn("準委任", joined)
        self.assertNotIn("b-tm.co.jp", joined)
        self.assertNotIn("株式会社", joined)
        self.assertNotIn("TEL", joined)

    def test_finalize_drops_junk_preferred_skills_from_ai(self) -> None:
        result = _finalize_with_rules(
            "project",
            "件名",
            "【案件名】：テスト\n【作業内容】：・作業A\n【必要スキル】：Java\n",
            {
                "title": "テスト",
                "required_skills": ["Java"],
                "preferred_skills": [
                    "HRsaas経験",
                    "■稼働開始日：",
                    "https://www.b-tm.co.jp",
                    "株式会社 BTM",
                    "TEL：03-5784-0456 FAX：03-5784-0455",
                ],
                "summary": "作業A",
            },
            provider="gemini",
        )
        self.assertEqual(result.data["preferred_skills"], ["HRsaas経験"])

    def test_finalize_project_prefers_body_work_content_over_ai_summary(self) -> None:
        body = """
【案件名】：テスト案件
【作業内容】：
・原文の業務内容その1
・原文の業務内容その2
【必要スキル】：Java
"""
        result = _finalize_with_rules(
            "project",
            "件名",
            body,
            {
                "title": "テスト案件",
                "required_skills": ["Java"],
                "summary": "AIが勝手に要約した短い説明",
            },
            provider="gemini",
        )
        self.assertIn("原文の業務内容その1", result.data["summary"] or "")
        self.assertNotIn("AIが勝手に要約", result.data["summary"] or "")

    def test_finalize_project_overrides_ai_foreign_ok_with_nationality_japan(self) -> None:
        body = """
【案件名】：PHP／Java 自社ATS
【国籍】：日本
【必要スキル】：PHP / Java
【作業内容】：・外部連携開発
"""
        result = _finalize_with_rules(
            "project",
            "件名",
            body,
            {
                "title": "PHP／Java 自社ATS",
                "required_skills": ["PHP", "Java"],
                "summary": "・外部連携開発",
                "foreign_nationality_ng": False,
            },
            provider="gemini",
        )
        self.assertTrue(result.data["foreign_nationality_ng"])

    def test_finalize_talent_uses_sales_comment_excerpt_as_summary(self) -> None:
        body = SAMPLE_ASTRO_TALENT_BODY.strip()
        result = _finalize_with_rules(
            "talent",
            "件名",
            body,
            {
                "display_name": "ST",
                "skills": ["Java"],
                "summary": "AIが短く要約した自己PR",
            },
            provider="gemini",
        )
        self.assertEqual(result.data["summary"], "詳細設計以降の工程を自走できます。")
        self.assertNotIn("AIが短く要約", result.data["summary"] or "")
        self.assertNotIn("株式会社Kanana", result.data["summary"] or "")
        self.assertNotIn("【名　前】", result.data["summary"] or "")
        self.assertIn("詳細設計", result.data["skills"])

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
        self.assertEqual(data["summary"], "詳細設計以降の工程を自走できます。")
        self.assertNotIn("株式会社Kanana　様", data["summary"] or "")
        self.assertNotIn("【名　前】ST", data["summary"] or "")
        self.assertTrue(any("Java" in s for s in data["skills"]))
        self.assertTrue(any("Spring Boot" in s for s in data["skills"]))
        self.assertFalse(any(s.startswith("実務経験") for s in data["skills"]))

    def test_rule_extract_talent_self_pr_verbatim(self) -> None:
        body = """
【名前】：KT
【スキル】：Java
【自己PR】
・コミュニケーション良好です。
・詳細設計以降を自走できます。
---------------------------------------------------------------------
担当：佐藤
"""
        data = _rule_extract_talent("人材ご紹介", body)
        self.assertEqual(
            data["summary"],
            "・コミュニケーション良好です。\n・詳細設計以降を自走できます。",
        )
        self.assertNotIn("担当：佐藤", data["summary"] or "")
        self.assertNotIn("Java", data["summary"] or "")

    def test_rule_extract_talent_keeps_both_sales_comment_and_self_pr(self) -> None:
        body = """
【営業コメント】現場リーダー経験あり。即戦力です。
【自己PR】AWSの構築も対応できます。
"""
        data = _rule_extract_talent("人材ご紹介", body)
        self.assertEqual(
            data["summary"],
            "現場リーダー経験あり。即戦力です。\n\nAWSの構築も対応できます。",
        )

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
        self.assertIn("詳細設計", result.data["skills"])
        self.assertIn("製造", result.data["skills"])


if __name__ == "__main__":
    unittest.main()
