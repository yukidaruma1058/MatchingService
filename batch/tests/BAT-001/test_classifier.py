"""BAT-001 classifier の単体テスト。

キーワード判定ロジック（要員のみ / 案件のみ / 両方 / なし）を検証する。
"""

import sys
import unittest
from pathlib import Path

_BAT001_ROOT = Path(__file__).resolve().parents[2] / "BAT-001"
if str(_BAT001_ROOT) not in sys.path:
    sys.path.insert(0, str(_BAT001_ROOT))

from classifier import classify_email, parse_keywords


class ClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.talent_keywords = parse_keywords("人材\n要員\nスキルシート")
        self.project_keywords = parse_keywords("案件\n募集\n開発")

    def test_talent_only(self) -> None:
        decision = classify_email(
            "【ご紹介】Javaエンジニア",
            "スキルシートを添付しました",
            talent_keywords=self.talent_keywords,
            project_keywords=self.project_keywords,
            talent_label="SES人材紹介",
            project_label="SES案件配信",
            unknown_label="SES要確認",
        )
        self.assertEqual(decision.email_type, "talent")
        self.assertEqual(decision.target_label, "SES人材紹介")

    def test_project_only(self) -> None:
        decision = classify_email(
            "【案件】React開発募集",
            "開発案件のご案内です",
            talent_keywords=self.talent_keywords,
            project_keywords=self.project_keywords,
            talent_label="SES人材紹介",
            project_label="SES案件配信",
            unknown_label="SES要確認",
        )
        self.assertEqual(decision.email_type, "project")
        self.assertEqual(decision.target_label, "SES案件配信")

    def test_both_keywords_are_unknown(self) -> None:
        decision = classify_email(
            "人材案件のご案内",
            "要員募集",
            talent_keywords=self.talent_keywords,
            project_keywords=self.project_keywords,
            talent_label="SES人材紹介",
            project_label="SES案件配信",
            unknown_label="SES要確認",
        )
        self.assertEqual(decision.email_type, "unknown")
        self.assertEqual(decision.target_label, "SES要確認")

    def test_subject_marker_overrides_label_keywords(self) -> None:
        """件名の【?人材】表記は、検索ワードがラベル名のみでも人材と判定する。"""
        decision = classify_email(
            "◆【Astro?人材】◆中上級PG◆・JAVA・Spring Boot・＠北綾瀬",
            "→貴社営業情報（案件・人材・他商材）も、ご紹介をお願いいたします。",
            talent_keywords=parse_keywords("人材紹介"),
            project_keywords=parse_keywords("案件紹介"),
            talent_label="人材紹介",
            project_label="案件紹介",
            unknown_label="判別不可",
        )
        self.assertEqual(decision.email_type, "talent")

    def test_short_project_keyword_does_not_match_pg_in_subject(self) -> None:
        decision = classify_email(
            "◆【Astro?人材】◆中上級PG◆・JAVA・Spring Boot・＠北綾瀬",
            "本文のみ",
            talent_keywords=parse_keywords("人材"),
            project_keywords=parse_keywords("PG\n案件"),
            talent_label="人材紹介",
            project_label="案件紹介",
            unknown_label="判別不可",
        )
        self.assertEqual(decision.email_type, "talent")

    def test_subject_priority_over_body_both_hits(self) -> None:
        """件名が人材のみなら、本文に案件キーワードがあっても人材と判定する。"""
        decision = classify_email(
            "◆【Astro?人材】◆中上級PG◆・JAVA・Spring Boot・＠北綾瀬",
            "→貴社営業情報（案件・人材・他商材）も、ご紹介をお願いいたします。",
            talent_keywords=self.talent_keywords,
            project_keywords=self.project_keywords,
            talent_label="SES人材紹介",
            project_label="SES案件配信",
            unknown_label="SES要確認",
        )
        self.assertEqual(decision.email_type, "talent")
        self.assertEqual(decision.target_label, "SES人材紹介")

    def test_subject_ambiguous_falls_back_to_body(self) -> None:
        decision = classify_email(
            "お知らせ",
            "【案件】React開発募集",
            talent_keywords=self.talent_keywords,
            project_keywords=self.project_keywords,
            talent_label="SES人材紹介",
            project_label="SES案件配信",
            unknown_label="SES要確認",
        )
        self.assertEqual(decision.email_type, "project")

    def test_no_keyword_is_unknown(self) -> None:
        decision = classify_email(
            "お世話になっております",
            "よろしくお願いします",
            talent_keywords=self.talent_keywords,
            project_keywords=self.project_keywords,
            talent_label="SES人材紹介",
            project_label="SES案件配信",
            unknown_label="SES要確認",
        )
        self.assertEqual(decision.email_type, "unknown")

    def test_parse_keywords_supports_pipe_separator(self) -> None:
        self.assertEqual(parse_keywords("人材|案件"), ["人材", "案件"])


if __name__ == "__main__":
    unittest.main()
