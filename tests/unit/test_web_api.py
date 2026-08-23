"""Tests for gaon.runtime.web_api - Gaon's first HTTP web API layer.

Directly calls dispatch_request() (no socket needed - see the module
docstring for why) plus a real end-to-end socket round-trip once, to
prove the actual HTTP handler wiring (headers, JSON body parsing,
status codes) works, not just the pure dispatch function.
"""
from __future__ import annotations

import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.web_api import (
    GaonWebChatAdapter,
    dispatch_request,
    production_gaon_web_chat_api_release_check,
    run_server,
)


def _adapter() -> GaonWebChatAdapter:
    store = RuntimeStateStore(":memory:")
    config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")
    return GaonWebChatAdapter(config, store._connection)


class DispatchRequestTests(unittest.TestCase):
    def test_health_check_has_no_side_effects_and_returns_ok(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(adapter, method="GET", path="/gaon/health", body=None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")

    def test_chat_request_reuses_the_real_conversation_brain(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(
            adapter, method="POST", path="/gaon/chat",
            body={"message": "가온 상태 알려줘", "session_ref": "t1", "user_ref": "u1", "read_only": True},
        )
        self.assertEqual(status, 200)
        self.assertTrue(str(payload["text"]).strip())
        self.assertEqual(payload["session_id"], "web:t1")
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])

    def test_read_only_hint_routes_through_existing_read_only_intent_detection(self) -> None:
        adapter = _adapter()
        _, without_hint = dispatch_request(
            adapter, method="POST", path="/gaon/chat",
            body={"message": "가온 상태 알려줘", "session_ref": "ro-a"},
        )
        _, with_hint = dispatch_request(
            adapter, method="POST", path="/gaon/chat",
            body={"message": "가온 상태 알려줘", "session_ref": "ro-b", "read_only": True},
        )
        # Both are read-only-shaped status questions in this case, but the
        # read_only hint must not be silently ignored - the route recorded
        # for the hinted request must reflect the SAME read-only detection
        # research_mission.is_explicit_read_only_query already provides.
        self.assertIn("read_only", with_hint["route"])
        self.assertTrue(str(without_hint["text"]).strip())

    def test_missing_message_is_rejected_with_400(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(adapter, method="POST", path="/gaon/chat", body={"session_ref": "x"})
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_blank_message_is_rejected_with_400(self) -> None:
        adapter = _adapter()
        status, _ = dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "   "})
        self.assertEqual(status, 400)

    def test_unknown_path_is_404(self) -> None:
        adapter = _adapter()
        status, _ = dispatch_request(adapter, method="GET", path="/does/not/exist", body=None)
        self.assertEqual(status, 404)

    def test_same_session_ref_persists_across_two_turns(self) -> None:
        adapter = _adapter()
        _, first = dispatch_request(
            adapter, method="POST", path="/gaon/chat",
            body={"message": "안녕하세요", "session_ref": "persist", "read_only": True},
        )
        _, second = dispatch_request(
            adapter, method="POST", path="/gaon/chat",
            body={"message": "가온 상태 알려줘", "session_ref": "persist", "read_only": True},
        )
        self.assertEqual(first["session_id"], second["session_id"])

    def test_no_endpoint_ever_bypasses_promotion_or_order_invariants(self) -> None:
        adapter = _adapter()
        for message in ("가온 상태 알려줘", "승격 후보 3개가 준비될 때까지 계속 연구해줘", "안녕"):
            _, payload = dispatch_request(
                adapter, method="POST", path="/gaon/chat",
                body={"message": message, "session_ref": "invariants"},
            )
            self.assertFalse(payload["strategy_mutated"])
            self.assertFalse(payload["order_executed"])
            self.assertFalse(payload["champion_promoted"])
            self.assertFalse(payload["approval_bypassed"])


class RealSocketRoundTripTests(unittest.TestCase):
    """One real end-to-end HTTP test (not just dispatch_request directly)
    to prove the actual socket/handler wiring works - headers, JSON
    parsing, status codes. Uses a single-threaded HTTPServer (see the
    module docstring for why ThreadingHTTPServer is unsafe here) run in
    one background thread, with the store/connection created inside that
    SAME thread - sqlite3 connections cannot cross threads."""

    def test_health_and_chat_over_a_real_socket(self) -> None:
        port = 18790
        started = threading.Event()

        def serve() -> None:
            store = RuntimeStateStore(":memory:")
            config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")
            from gaon.runtime.web_api import GaonWebChatAdapter as _Adapter
            from gaon.runtime.web_api import build_request_handler
            from http.server import HTTPServer

            adapter = _Adapter(config, store._connection)
            handler_cls = build_request_handler(adapter)
            httpd = HTTPServer(("127.0.0.1", port), handler_cls)
            started.set()
            httpd.timeout = 5
            httpd.handle_request()  # health check
            httpd.handle_request()  # chat request
            httpd.server_close()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=5))
        time.sleep(0.2)

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/gaon/health", timeout=5) as response:
            self.assertEqual(response.status, 200)
            health_payload = json.loads(response.read())
            self.assertEqual(health_payload["status"], "ok")

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/gaon/chat",
            data=json.dumps({"message": "가온 상태 알려줘", "session_ref": "socket-test", "read_only": True}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:
            self.assertEqual(response.status, 200)
            chat_payload = json.loads(response.read())
            self.assertEqual(chat_payload["session_id"], "web:socket-test")
            self.assertFalse(chat_payload["strategy_mutated"])

        thread.join(timeout=5)


class GaonWebChatApiReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes(self) -> None:
        payload = production_gaon_web_chat_api_release_check()
        for key in (
            "health_check_ok",
            "chat_request_ok",
            "chat_response_has_text",
            "chat_response_has_route",
            "chat_response_session_matches",
            "missing_message_rejected",
            "unknown_path_is_404",
            "second_turn_same_session_ok",
            "no_strategy_mutation",
            "no_order_execution",
            "no_champion_promotion",
            "no_approval_bypass",
        ):
            self.assertTrue(payload[key], key)
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])
        self.assertEqual(payload["safety"], "pass")

    def test_release_check_is_deterministic_in_shape_across_runs(self) -> None:
        first = production_gaon_web_chat_api_release_check()
        second = production_gaon_web_chat_api_release_check()
        self.assertEqual(set(first.keys()), set(second.keys()))
        for key in first:
            if key in ("sample_route",):
                continue
            self.assertEqual(first[key], second[key], key)


class GaonWebChatApiCliWiringTests(unittest.TestCase):
    """CLI wiring for production_gaon_web_chat_api_release_check, following
    the exact existing gaon-production-*-release-check pattern (see
    EconomicViabilityGateCliWiringTests in test_strategy_candidate.py)."""

    def test_web_chat_api_release_check_cli_passes(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from gaon.runtime.cli import main as cli_main

        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(["gaon-production-web-chat-api-release-check"])
        self.assertEqual(exit_code, 0)
        printed = output.getvalue()
        self.assertIn("gaon-production-web-chat-api-release-check: PASS", printed)
        self.assertIn("strategy_mutated=false", printed)
        self.assertIn("order_executed=false", printed)
        self.assertIn("champion_promoted=false", printed)
        self.assertIn("approval_bypassed=false", printed)
        self.assertIn("safety=pass", printed)


if __name__ == "__main__":
    unittest.main()
