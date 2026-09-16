"""Gemini generateContent ラッパーの単体テスト（外部 API なし）。"""

from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))

from app.gemini_llm import (  # noqa: E402
    DEFAULT_GEMINI_MODEL,
    call_gemini_json,
    classify_gemini_failure,
    redact_gemini_secrets,
    resolve_gemini_batch_parallel,
    resolve_gemini_batch_size,
    resolve_gemini_batch_wave_interval_seconds,
    resolve_gemini_input_tpm,
    resolve_gemini_model,
)


class GeminiLlmTests(unittest.TestCase):
    def test_resolve_model_default(self) -> None:
        self.assertEqual(resolve_gemini_model(""), DEFAULT_GEMINI_MODEL)
        self.assertEqual(resolve_gemini_model("gemini-2.5-flash"), "gemini-2.5-flash")

    def test_resolve_batch_size_clamped(self) -> None:
        self.assertEqual(resolve_gemini_batch_size(None), 20)
        self.assertEqual(resolve_gemini_batch_size(0), 1)
        self.assertEqual(resolve_gemini_batch_size(100), 50)

    def test_resolve_batch_parallel_and_interval_clamped(self) -> None:
        self.assertEqual(resolve_gemini_batch_parallel(None), 10)
        self.assertEqual(resolve_gemini_batch_parallel(0), 1)
        self.assertEqual(resolve_gemini_batch_parallel(40), 15)
        self.assertEqual(resolve_gemini_batch_wave_interval_seconds(None), 60)
        self.assertEqual(resolve_gemini_batch_wave_interval_seconds(-1), 0)
        self.assertEqual(resolve_gemini_batch_wave_interval_seconds(999), 180)
        self.assertEqual(resolve_gemini_input_tpm(None), 250_000)
        self.assertEqual(resolve_gemini_input_tpm(0), 1)
        self.assertEqual(resolve_gemini_input_tpm(99_999_999), 10_000_000)

    def test_call_gemini_skips_without_key(self) -> None:
        self.assertIsNone(
            call_gemini_json(api_key="", model=None, system="sys", user="user")
        )

    def test_redact_api_key_in_url(self) -> None:
        text = "https://example/?key=secret123&alt=json"
        self.assertIn("key=REDACTED", redact_gemini_secrets(text))
        self.assertNotIn("secret123", redact_gemini_secrets(text))

    def test_classify_key_permission_and_schema(self) -> None:
        self.assertEqual(
            classify_gemini_failure(http_status=403, google_status="PERMISSION_DENIED", message="API key"),
            "key_or_permission",
        )
        self.assertEqual(
            classify_gemini_failure(
                http_status=400,
                google_status="INVALID_ARGUMENT",
                message="Invalid JSON payload: responseSchema",
            ),
            "schema_or_request",
        )
        self.assertEqual(
            classify_gemini_failure(http_status=404, google_status="NOT_FOUND", message="model"),
            "model_not_found",
        )
        self.assertEqual(
            classify_gemini_failure(http_status=None, message="[Errno -2] Name or service not known"),
            "network",
        )
        self.assertEqual(
            classify_gemini_failure(http_status=200, finish_reason="SAFETY", block_reason="SAFETY"),
            "blocked",
        )

    def test_http_400_is_logged_with_failure_class(self) -> None:
        body = json.dumps(
            {
                "error": {
                    "code": 400,
                    "message": "Invalid JSON payload received. Unknown name responseSchema",
                    "status": "INVALID_ARGUMENT",
                }
            }
        )
        error = urllib.error.HTTPError(
            "https://generativelanguage.googleapis.com/v1beta/models/x:generateContent?key=SECRET",
            400,
            "Bad Request",
            hdrs=None,
            fp=io.BytesIO(body.encode("utf-8")),
        )
        with patch("app.gemini_llm.urllib.request.urlopen", side_effect=error):
            with patch("app.gemini_llm._log_gemini_failure") as logged:
                result = call_gemini_json(
                    api_key="SECRET",
                    model="gemini-2.5-flash",
                    system="sys",
                    user="user",
                    response_schema={"type": "OBJECT"},
                    purpose="extract_batch_talent",
                )
        self.assertIsNone(result)
        logged.assert_called_once()
        kwargs = logged.call_args.kwargs
        self.assertEqual(kwargs["failure_class"], "schema_or_request")
        self.assertEqual(kwargs["http_status"], 400)
        self.assertEqual(kwargs["google_status"], "INVALID_ARGUMENT")
        self.assertEqual(kwargs["purpose"], "extract_batch_talent")
        self.assertNotIn("SECRET", kwargs.get("body_excerpt", ""))
        self.assertNotIn("SECRET", kwargs.get("detail", ""))


if __name__ == "__main__":
    unittest.main()
