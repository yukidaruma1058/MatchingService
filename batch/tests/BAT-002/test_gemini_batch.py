"""Gemini 20通バッチ抽出の単体テスト（API は mock）。"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

_TESTS_DIR = Path(__file__).resolve().parents[1]
_BATCH_ROOT = _TESTS_DIR.parent
_BAT002_ROOT = _BATCH_ROOT / "BAT-002"
for _path in (str(_BATCH_ROOT), str(_BAT002_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from summarizer import (  # noqa: E402
    EmailExtractRequest,
    ExtractionResult,
    _BATCH_ITEMS_SCHEMA,
    _GEMINI_BATCH_FIELD_SCHEMA_PROJECT,
    _GEMINI_BATCH_FIELD_SCHEMA_TALENT,
    _TALENT_ITEM_SCHEMA,
    _build_batch_emails_xml,
    _build_gemini_batch_user_prompt,
    _extract_batch_via_gemini,
    _should_wait_before_retry,
    extract_email_fields_batch,
)


def _cfg() -> SimpleNamespace:
    return SimpleNamespace(
        gemini_api_key="test-gemini",
        gemini_model="gemini-2.5-flash",
        gemini_batch_size=20,
        gemini_batch_parallel=10,
        gemini_batch_wave_interval_seconds=0,
        gemini_input_tpm=250000,
        ai_concurrency=3,
        cursor_api_key="",
        openai_api_key="",
        openai_model="gpt-4o-mini",
        anthropic_api_key="",
        anthropic_model="claude-haiku-4-5-20251001",
    )


def _result(name: str, *, provider: str = "gemini") -> ExtractionResult:
    return ExtractionResult(
        email_type="talent",
        data={"display_name": name, "skills": ["Java"], "summary": "s"},
        needs_review=False,
        provider=provider,
    )


class GeminiBatchExtractTests(unittest.TestCase):
    def test_batch_schema_includes_mail_id(self) -> None:
        self.assertEqual(_TALENT_ITEM_SCHEMA["properties"]["mail_id"]["type"], "STRING")
        self.assertIn("mail_id", _TALENT_ITEM_SCHEMA["required"])
        self.assertIn("items", _BATCH_ITEMS_SCHEMA["talent"]["properties"])
        self.assertNotIn("minItems", _BATCH_ITEMS_SCHEMA["talent"]["properties"]["items"])
        self.assertNotIn("maxItems", _BATCH_ITEMS_SCHEMA["talent"]["properties"]["items"])

    def test_batch_emails_xml_wraps_each_mail(self) -> None:
        requests = [
            EmailExtractRequest(
                item_id="gm-a",
                subject="件名A",
                body="本文A",
                from_header="a@example.com",
            ),
            EmailExtractRequest(item_id="gm-b", subject="件名B", body="本文B"),
        ]
        xml = _build_batch_emails_xml(requests)
        self.assertTrue(xml.startswith("<emails_list>"))
        self.assertTrue(xml.endswith("</emails_list>"))
        self.assertIn('<email id="gm-a">', xml)
        self.assertIn("<subject>件名A</subject>", xml)
        self.assertIn("<body>本文A</body>", xml)
        self.assertIn("<from>a@example.com</from>", xml)
        self.assertIn('<email id="gm-b">', xml)
        self.assertNotIn("### MAIL", xml)

    def test_gemini_batch_prompt_has_isolation_rules(self) -> None:
        requests = [
            EmailExtractRequest(item_id="gm-a", subject="件名A", body="本文A"),
            EmailExtractRequest(item_id="gm-b", subject="件名B", body="本文B"),
        ]
        talent_prompt = _build_gemini_batch_user_prompt("talent", requests)
        project_prompt = _build_gemini_batch_user_prompt("project", requests)

        for prompt in (talent_prompt, project_prompt):
            self.assertIn("あなたは優秀なSES営業アシスタントです。", prompt)
            self.assertIn("【最重要制約事項（厳守）】", prompt)
            self.assertIn("完全な相互独立性", prompt)
            self.assertIn('"mail_id"', prompt)
            self.assertIn("必ず「要確認」と出力", prompt)
            self.assertIn("ただし project_code（案件番号）だけは例外", prompt)
            self.assertIn("<emails_list>", prompt)
            self.assertIn('<email id="gm-a">', prompt)
            self.assertIn("2件", prompt)
            self.assertIn("次の mail_id をすべて返せ", prompt)
            self.assertIn("   - gm-a", prompt)
            self.assertIn("   - gm-b", prompt)
            self.assertIn("ちょうど 2 件", prompt)

        self.assertIn("display_name", talent_prompt)
        self.assertIn(_GEMINI_BATCH_FIELD_SCHEMA_TALENT.strip().splitlines()[0], talent_prompt)
        self.assertIn("title", project_prompt)
        self.assertIn(_GEMINI_BATCH_FIELD_SCHEMA_PROJECT.strip().splitlines()[0], project_prompt)
        self.assertIn("project_code (string|null)", project_prompt)
        self.assertIn("「要確認」は禁止", project_prompt)

    def test_missing_id_falls_back_to_single_extract(self) -> None:
        requests = [
            EmailExtractRequest(item_id=f"gm-{index}", subject="件名", body="本文")
            for index in range(1, 21)
        ]

        def fake_batch(_email_type, chunk, _cfg):
            hits = {}
            for item in chunk[:-1]:
                hits[item.item_id] = _result(item.item_id)
            return hits

        fallback = _result("fallback", provider="cursor")
        with patch("summarizer._extract_batch_via_gemini", side_effect=fake_batch):
            with patch("summarizer.extract_email_fields", return_value=fallback) as single:
                out = extract_email_fields_batch("talent", requests, _cfg())  # type: ignore[arg-type]

        self.assertEqual(len(out), 20)
        self.assertEqual(out["gm-20"].provider, "cursor")
        single.assert_called_once()

    def test_first_wave_sends_packs_in_parallel(self) -> None:
        requests = [
            EmailExtractRequest(item_id=f"gm-{index}", subject="件名", body="本文")
            for index in range(80)
        ]
        current = 0
        max_current = 0
        lock = threading.Lock()

        def fake_batch(_email_type, chunk, _cfg):
            nonlocal current, max_current
            with lock:
                current += 1
                max_current = max(max_current, current)
            time.sleep(0.05)
            with lock:
                current -= 1
            return {item.item_id: _result(item.item_id) for item in chunk}

        with patch("summarizer._extract_batch_via_gemini", side_effect=fake_batch) as batch:
            out = extract_email_fields_batch(
                "talent",
                requests,
                _cfg(),  # type: ignore[arg-type]
                batch_parallel=4,
                wave_interval_seconds=0,
            )

        self.assertEqual(len(out), 80)
        self.assertEqual(batch.call_count, 4)
        self.assertGreaterEqual(max_current, 2)

    def test_unsent_and_failed_packs_retry_serial_after_wait(self) -> None:
        requests = [
            EmailExtractRequest(item_id=f"gm-{index}", subject="件名", body="本文")
            for index in range(60)
        ]
        call_sizes: list[int] = []
        wave = {"n": 0}

        def fake_batch(_email_type, chunk, _cfg):
            call_sizes.append(len(chunk))
            wave["n"] += 1
            # 1波目の先頭パックだけ全部失敗させる
            if wave["n"] == 1:
                return {}
            return {item.item_id: _result(item.item_id) for item in chunk}

        with patch("summarizer._extract_batch_via_gemini", side_effect=fake_batch) as batch:
            with patch("summarizer.time.sleep") as slept:
                with patch("summarizer._log_gemini_batch") as logged:
                    cfg = _cfg()
                    cfg.gemini_batch_wave_interval_seconds = 60
                    cfg.gemini_input_tpm = 1
                    out = extract_email_fields_batch(
                        "talent",
                        requests,
                        cfg,  # type: ignore[arg-type]
                        batch_parallel=1,
                        wave_interval_seconds=60,
                    )

        self.assertEqual(len(out), 60)
        self.assertEqual(call_sizes[0], 20)
        self.assertGreaterEqual(len(call_sizes), 4)
        slept.assert_called()
        self.assertGreaterEqual(slept.call_args[0][0], 0)
        self.assertGreaterEqual(batch.call_count, 4)
        retry_calls = [c for c in logged.call_args_list if c.args and c.args[0] == "gmail_ingest.gemini_retry"]
        self.assertTrue(retry_calls)
        self.assertEqual(retry_calls[0].kwargs["missing_count"], 60)
        self.assertEqual(retry_calls[0].kwargs["retry_packs"], 3)
        self.assertTrue(retry_calls[0].kwargs["wait_before_retry"])
        done_calls = [c for c in logged.call_args_list if c.args and c.args[0] == "gmail_ingest.gemini_retry_done"]
        self.assertTrue(done_calls)
        self.assertEqual(done_calls[0].kwargs["recovered_count"], 60)
        self.assertEqual(done_calls[0].kwargs["still_missing_count"], 0)

    def test_all_hits_skip_wait_and_single_fallback(self) -> None:
        requests = [
            EmailExtractRequest(item_id=f"gm-{index}", subject="件名", body="本文")
            for index in range(20)
        ]

        def fake_batch(_email_type, chunk, _cfg):
            return {item.item_id: _result(item.item_id) for item in chunk}

        with patch("summarizer._extract_batch_via_gemini", side_effect=fake_batch):
            with patch("summarizer.extract_email_fields") as single:
                with patch("summarizer.time.sleep") as slept:
                    out = extract_email_fields_batch(
                        "talent",
                        requests,
                        _cfg(),  # type: ignore[arg-type]
                        wave_interval_seconds=60,
                    )

        self.assertEqual(len(out), 20)
        single.assert_not_called()
        slept.assert_not_called()

    def test_partial_miss_retries_immediately_when_tpm_fits(self) -> None:
        requests = [
            EmailExtractRequest(item_id=f"gm-{index}", subject="件名", body="本文")
            for index in range(20)
        ]
        wave = {"n": 0}

        def fake_batch(_email_type, chunk, _cfg):
            wave["n"] += 1
            if wave["n"] == 1:
                return {item.item_id: _result(item.item_id) for item in chunk[:-1]}
            return {item.item_id: _result(item.item_id) for item in chunk}

        with patch("summarizer._extract_batch_via_gemini", side_effect=fake_batch) as batch:
            with patch("summarizer.extract_email_fields") as single:
                with patch("summarizer.time.sleep") as slept:
                    with patch("summarizer._log_gemini_batch") as logged:
                        out = extract_email_fields_batch(
                            "talent",
                            requests,
                            _cfg(),  # type: ignore[arg-type]
                            wave_interval_seconds=60,
                        )

        self.assertEqual(len(out), 20)
        self.assertEqual(batch.call_count, 2)
        single.assert_not_called()
        slept.assert_not_called()
        retry_calls = [c for c in logged.call_args_list if c.args and c.args[0] == "gmail_ingest.gemini_retry"]
        self.assertTrue(retry_calls)
        self.assertEqual(retry_calls[0].kwargs["missing_count"], 1)
        self.assertFalse(retry_calls[0].kwargs["wait_before_retry"])

    def test_should_wait_before_retry_uses_tpm_budget(self) -> None:
        self.assertFalse(
            _should_wait_before_retry(
                used_tokens=80_000, retry_tokens=20_000, tpm_limit=250_000, interval_seconds=60
            )
        )
        self.assertTrue(
            _should_wait_before_retry(
                used_tokens=240_000, retry_tokens=20_000, tpm_limit=250_000, interval_seconds=60
            )
        )
        self.assertFalse(
            _should_wait_before_retry(
                used_tokens=240_000, retry_tokens=20_000, tpm_limit=250_000, interval_seconds=0
            )
        )

    def test_extract_batch_skips_unknown_and_missing_ids(self) -> None:
        requests = [
            EmailExtractRequest(item_id="gm-a", subject="a", body="a"),
            EmailExtractRequest(item_id="gm-b", subject="b", body="b"),
        ]
        payload = {
            "items": [
                {"mail_id": "gm-a", "display_name": "A", "skills": ["Java"], "summary": "sa"},
                {"mail_id": "ghost", "display_name": "ghost", "skills": ["Go"], "summary": "x"},
            ]
        }

        captured: dict = {}

        def fake_call(**kwargs):
            captured.update(kwargs)
            return json.dumps(payload)

        with patch("summarizer._load_gemini_llm", return_value=(fake_call, lambda *_a, **_k: 20)):
            with patch("summarizer._finalize_with_rules", return_value=_result("A")):
                hits = _extract_batch_via_gemini("talent", requests, _cfg())  # type: ignore[arg-type]

        self.assertEqual(set(hits), {"gm-a"})
        items_schema = captured["response_schema"]["properties"]["items"]
        self.assertNotIn("minItems", items_schema)
        self.assertNotIn("maxItems", items_schema)


if __name__ == "__main__":
    unittest.main()
