"""Gmail fetch_messages / relabel_messages のチャンクと payload テスト。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_BATCH_ROOT = Path(__file__).resolve().parents[1]
if str(_BATCH_ROOT) not in sys.path:
    sys.path.insert(0, str(_BATCH_ROOT))


def _install_gmail_stubs() -> None:
    if "httplib2" in sys.modules:
        return

    class HttpError(Exception):
        pass

    def _mod(name: str) -> MagicMock:
        module = MagicMock()
        sys.modules[name] = module
        return module

    _mod("httplib2")
    _mod("google")
    _mod("google.auth")
    _mod("google.auth.transport")
    _mod("google.auth.transport.requests")
    _mod("google.oauth2")
    _mod("google.oauth2.credentials")
    _mod("google_auth_httplib2")
    googleapiclient = _mod("googleapiclient")
    discovery = _mod("googleapiclient.discovery")
    googleapiclient.discovery = discovery
    errors = _mod("googleapiclient.errors")
    errors.HttpError = HttpError
    googleapiclient.errors = errors
    http = _mod("googleapiclient.http")
    googleapiclient.http = http


try:
    from app.gmail_client import GmailClient
except ModuleNotFoundError:
    _install_gmail_stubs()
    from app.gmail_client import GmailClient  # noqa: E402


class _FakeBatch:
    instances: list["_FakeBatch"] = []

    def __init__(self, callback=None, **_kwargs):
        self.callback = callback
        self.ids: list[str] = []
        _FakeBatch.instances.append(self)

    def add(self, _request, request_id=None):
        self.ids.append(str(request_id))

    def execute(self) -> None:
        for request_id in self.ids:
            self.callback(
                request_id,
                {
                    "id": request_id,
                    "threadId": "thread-1",
                    "labelIds": ["INBOX"],
                    "payload": {
                        "headers": [
                            {"name": "Subject", "value": f"subj-{request_id}"},
                            {"name": "From", "value": "a@example.com"},
                        ]
                    },
                },
                None,
            )


class GmailBatchClientTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeBatch.instances = []
        self.client = GmailClient("/tmp/credentials.json", "/tmp/token.json")
        self.client._service = MagicMock()
        self.client._label_name_to_id = {"src": "Lsrc", "dst": "Ldst"}

    def test_fetch_messages_chunks_and_keeps_order(self) -> None:
        ids = [f"m{i}" for i in range(120)]
        with patch("googleapiclient.http.BatchHttpRequest", _FakeBatch):
            results = self.client.fetch_messages(ids, chunk_size=50)

        self.assertEqual(len(_FakeBatch.instances), 3)
        self.assertEqual([len(batch.ids) for batch in _FakeBatch.instances], [50, 50, 20])
        self.assertEqual([row[0] for row in results], ids)
        self.assertTrue(all(row[1] is not None and row[2] is None for row in results))
        self.assertEqual(results[0][1].subject, "subj-m0")

    def test_fetch_messages_default_chunk_is_20(self) -> None:
        ids = [f"m{i}" for i in range(45)]
        with patch("googleapiclient.http.BatchHttpRequest", _FakeBatch):
            results = self.client.fetch_messages(ids)

        self.assertEqual(len(_FakeBatch.instances), 3)
        self.assertEqual([len(batch.ids) for batch in _FakeBatch.instances], [20, 20, 5])
        self.assertEqual([row[0] for row in results], ids)

    def test_relabel_messages_batch_modify_payload_and_chunks(self) -> None:
        captured: list[dict] = []

        def fake_execute(request):
            captured.append(request)
            return {}

        def batch_modify(*, userId, body):
            self.assertEqual(userId, "me")
            return body

        self.client._execute = fake_execute  # type: ignore[method-assign]
        self.client.ensure_label = lambda name: "Ldst" if name == "dst" else "Lsrc"  # type: ignore[method-assign]
        self.client._service.users.return_value.messages.return_value.batchModify.side_effect = batch_modify

        ids = [f"m{i}" for i in range(5)]
        self.client.relabel_messages(ids, add_label_names=["dst"], remove_label_names=["src"], chunk_size=2)

        self.assertEqual(len(captured), 3)
        self.assertEqual(captured[0]["ids"], ["m0", "m1"])
        self.assertEqual(captured[0]["addLabelIds"], ["Ldst"])
        self.assertEqual(captured[0]["removeLabelIds"], ["Lsrc"])
        self.assertEqual(captured[-1]["ids"], ["m4"])


if __name__ == "__main__":
    unittest.main()
