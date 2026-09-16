"""詳細画面の 1:n 未採点ルール採点とパイプライン文言の静的チェック。"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCREENS = _ROOT / "web" / "components" / "Screens.tsx"
_MAIN = _ROOT / "batch" / "app" / "main.py"


class DetailMatchScoreUiTests(unittest.TestCase):
    def test_talent_and_project_detail_use_force_false(self) -> None:
        text = _SCREENS.read_text(encoding="utf-8")
        self.assertIn("runMatchScoreBatch({\n    force: false,", text)
        self.assertIn("talentId: options.talentId", text)
        self.assertIn("projectId: options.projectId", text)
        self.assertIn("runUnscoredMatchAndMaybeAiJudge({ talentId: talent.id })", text)
        self.assertIn("runUnscoredMatchAndMaybeAiJudge({ projectId: project.id })", text)
        self.assertNotIn('{busy ? "処理中…" : "ルール採点を実行"}', text)
        self.assertNotIn("runMatchScoreBatch({ force: true, talentId: talent.id })", text)

    def test_pipeline_steps_are_ingest_cleanup_reply_sync_match(self) -> None:
        text = _MAIN.read_text(encoding="utf-8")
        self.assertIn('("ingest", "ingest", {"INGEST_SCOPE": "all"})', text)
        self.assertIn('("cleanup", "cleanup", {})', text)
        self.assertIn('("reply_sync", "reply_sync", {})', text)
        self.assertIn('("match", "match", {})', text)
        self.assertNotIn("ingest_talent", text)

    def test_dashboard_shows_high_score_matches_separate_from_funnel(self) -> None:
        text = _SCREENS.read_text(encoding="utf-8")
        self.assertIn("HighScoreMatchPanel", text)
        self.assertIn("dashboard_rule_score_min", text)
        self.assertIn("ファンネルの「提案可能」は従来どおり score &gt; 0", text)
        self.assertIn("score &gt; 0 の相手が1件以上ある件数", text)
        self.assertIn("未提案", text)
        self.assertIn("提案済み", text)
        self.assertIn("setDashboardHighScoreMatchProposed", text)
        self.assertIn("表示だけ「未提案」に戻し、提案メールは残します", text)


if __name__ == "__main__":
    unittest.main()
