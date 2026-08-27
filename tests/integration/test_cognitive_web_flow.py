import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from pathlib import Path
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.web_api import build_server, GaonWebChatAdapter


class CognitiveWebFlowTests(unittest.TestCase):
    def test_busy_chat_does_not_block_health_or_execute_second_chat(self):
        from gaon.runtime import web_api
        entered, release = threading.Event(), threading.Event()
        real_dispatch = web_api.dispatch_request
        def delayed(adapter, **kwargs):
            if kwargs["method"] == "POST":
                entered.set()
                if not release.wait(5):
                    raise TimeoutError("test release missing")
            return real_dispatch(adapter, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            store = RuntimeStateStore(str(Path(directory) / "runtime.sqlite"))
            server = build_server(GaonRuntimeConfig(), store, host="127.0.0.1", port=0)
            serving = threading.Thread(target=server.serve_forever, daemon=True)
            serving.start()
            url = f"http://127.0.0.1:{server.server_port}"
            outcomes = []
            def chat():
                req = urllib.request.Request(url + "/gaon/chat", data=b'{"message":"hi","session_ref":"A"}',
                                             headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as response:
                    outcomes.append(response.status)
            first = threading.Thread(target=chat)
            try:
                with patch.object(web_api, "dispatch_request", side_effect=delayed):
                    first.start()
                    self.assertTrue(entered.wait(3))
                    with urllib.request.urlopen(url + "/gaon/health", timeout=2) as response:
                        self.assertEqual(response.status, 200)
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        chat()
                    self.assertEqual(caught.exception.code, 503)
                    caught.exception.close()
                    release.set()
                    first.join(5)
                    self.assertEqual(outcomes, [200])
            finally:
                release.set()
                if first.is_alive():
                    first.join(5)
                server.shutdown()
                serving.join(5)
                server.server_close()
                store.close()

    def test_thread_owned_connection_and_restart_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "runtime.sqlite")
            store = RuntimeStateStore(path)
            config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")
            server = build_server(config, store, host="127.0.0.1", port=0)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/gaon/chat",
                    data=json.dumps({"message": "같은 상태 설명을 반복하지 마", "session_ref": "A", "user_ref": "A"}).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as response:
                    self.assertEqual(json.load(response)["route"], "cognitive_feedback")
            finally:
                server.shutdown()
                worker.join(5)
                server.server_close()
                store.close()
            store = RuntimeStateStore(path)
            try:
                adapter = GaonWebChatAdapter(config, store._connection)
                self.assertEqual(adapter._brain._cognitive.retrieve(namespace="web-user:A", query="상태").preferences, ("avoid_repetitive_status",))
                self.assertEqual(adapter._brain._cognitive.retrieve(namespace="web-user:B", query="상태").preferences, ())
                self.assertEqual(len(adapter._repository.list_messages("web:A")), 2)
                from gaon.cognitive.models import CognitiveRecordType
                reflections = adapter._brain._cognitive.records.list(namespace="web-user:A", record_type=CognitiveRecordType.REFLECTION)
                user_ids = {m.message_id for m in adapter._repository.list_messages("web:A") if m.role == "user"}
                self.assertTrue(set(reflections[0].source_refs).issubset(user_ids))
                self.assertEqual(adapter._repository.list_messages("web:B"), ())
            finally:
                store.close()
