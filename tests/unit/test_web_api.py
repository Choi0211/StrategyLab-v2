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

from gaon.knowledge.research_mission import add_candidate, extract_or_update_mission, next_candidate_sequence
from gaon.knowledge.strategy_candidate import new_candidate
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationSession
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.web_api import (
    GaonWebChatAdapter,
    dispatch_request,
    production_conversation_lifecycle_durable_state_release_check,
    production_gaon_research_status_api_release_check,
    production_gaon_storage_status_api_release_check,
    production_gaon_web_api_root_release_check,
    production_gaon_web_chat_api_release_check,
    run_server,
)

_MISSION_TEXT = "대한민국 장에 맞는 단타 매매 전략을 연구해줘. 승격 준비 후보 3개가 준비될 때까지 계속해줘."
_NOW = "2026-08-23T00:00:00Z"


def _seed_mission_with_one_candidate(adapter: GaonWebChatAdapter, session_ref: str):
    """Creates the session (a real chat turn, same as any real caller),
    then persists a real ResearchMission + StrategyCandidateRecord built
    through the same production functions used everywhere else in this
    codebase, into that session's metadata - exactly how
    LLMConversationBrain._remember_mission does it. Returns the candidate."""
    adapter.handle(message="가온 상태 알려줘 readonly", session_ref=session_ref, user_ref="u1", read_only=True, received_at=_NOW)
    mission = extract_or_update_mission(_MISSION_TEXT, existing=None, now=_NOW)
    candidate = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=_NOW)
    mission = add_candidate(mission, candidate, now=_NOW)
    session = adapter._repository.get_session(f"web:{session_ref}")
    metadata = dict(session.metadata)
    metadata["conversation_mvp"] = {"research_mission": mission.to_json()}
    adapter._repository.upsert_session(
        LLMConversationSession(session.session_id, session.user_ref, session.source, session.status, session.created_at, _NOW, metadata)
    )
    return candidate


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

    def test_root_is_read_only_service_discovery(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(adapter, method="GET", path="/", body=None)
        self.assertEqual(status, 200)
        self.assertEqual(payload["service"], "Gaon Web API")
        self.assertEqual(payload["health"], "/gaon/health")
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["approval_bypassed"])

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


class ResearchStatusEndpointsTests(unittest.TestCase):
    def test_mission_status_missing_session_ref_is_400(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(adapter, method="GET", path="/gaon/research/mission", body=None)
        self.assertEqual(status, 400)
        self.assertIn("error", payload)

    def test_mission_status_for_unknown_session_is_a_well_shaped_empty_response(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/mission?session_ref=nobody-home", body=None
        )
        self.assertEqual(status, 200)
        self.assertFalse(payload["exists"])

    def test_candidates_list_for_unknown_session_is_empty_not_an_error(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/candidates?session_ref=nobody-home", body=None
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["candidates"], [])

    def test_mission_and_candidates_reflect_real_persisted_state(self) -> None:
        adapter = _adapter()
        candidate = _seed_mission_with_one_candidate(adapter, "kr-status")

        mission_status, mission_payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/mission?session_ref=kr-status", body=None
        )
        self.assertEqual(mission_status, 200)
        self.assertTrue(mission_payload["exists"])
        self.assertEqual(mission_payload["progress_label"], "0/3")
        self.assertEqual(mission_payload["candidate_count"], 1)
        self.assertFalse(mission_payload["strategy_mutated"])
        self.assertFalse(mission_payload["order_executed"])
        self.assertFalse(mission_payload["champion_promoted"])
        self.assertFalse(mission_payload["approval_bypassed"])

        list_status, list_payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/candidates?session_ref=kr-status", body=None
        )
        self.assertEqual(list_status, 200)
        self.assertEqual(len(list_payload["candidates"]), 1)
        self.assertEqual(list_payload["candidates"][0]["candidate_id"], candidate.candidate_id)
        self.assertIn("validation_stage_status", list_payload["candidates"][0])
        self.assertIn("economic_viability", list_payload["candidates"][0])

    def test_candidate_detail_matches_list_entry_and_404s_for_unknown_id(self) -> None:
        adapter = _adapter()
        candidate = _seed_mission_with_one_candidate(adapter, "kr-detail")

        found_status, found_payload = dispatch_request(
            adapter, method="GET", path=f"/gaon/research/candidates/{candidate.candidate_id}?session_ref=kr-detail", body=None
        )
        self.assertEqual(found_status, 200)
        self.assertEqual(found_payload["candidate_id"], candidate.candidate_id)
        self.assertEqual(found_payload["strategy_family"], candidate.strategy_family)

        missing_status, missing_payload = dispatch_request(
            adapter, method="GET", path="/gaon/research/candidates/NOT-A-REAL-ID?session_ref=kr-detail", body=None
        )
        self.assertEqual(missing_status, 404)
        self.assertFalse(missing_payload["exists"])

    def test_candidate_detail_missing_session_ref_is_400(self) -> None:
        adapter = _adapter()
        status, _ = dispatch_request(adapter, method="GET", path="/gaon/research/candidates/KR-ST-001", body=None)
        self.assertEqual(status, 400)


class ResearchStatusApiReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes(self) -> None:
        payload = production_gaon_research_status_api_release_check()
        for key in (
            "empty_mission_status_ok",
            "empty_mission_not_exists",
            "empty_candidates_status_ok",
            "empty_candidates_list_is_empty",
            "missing_session_ref_is_400",
            "mission_status_ok",
            "mission_exists",
            "mission_progress_label_correct",
            "mission_candidate_count_correct",
            "candidates_status_ok",
            "candidates_list_has_one",
            "candidate_id_matches",
            "candidate_has_validation_stage_status",
            "detail_status_ok",
            "detail_candidate_id_matches",
            "detail_has_economic_viability",
            "missing_detail_is_404",
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
        first = production_gaon_research_status_api_release_check()
        second = production_gaon_research_status_api_release_check()
        self.assertEqual(first, second)


class ResearchStatusApiCliWiringTests(unittest.TestCase):
    """CLI wiring for production_gaon_research_status_api_release_check,
    following the exact existing gaon-production-*-release-check pattern."""

    def test_research_status_api_release_check_cli_passes(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from gaon.runtime.cli import main as cli_main

        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(["gaon-production-research-status-api-release-check"])
        self.assertEqual(exit_code, 0)
        printed = output.getvalue()
        self.assertIn("gaon-production-research-status-api-release-check: PASS", printed)
        self.assertIn("strategy_mutated=false", printed)
        self.assertIn("order_executed=false", printed)
        self.assertIn("champion_promoted=false", printed)
        self.assertIn("approval_bypassed=false", printed)
        self.assertIn("safety=pass", printed)


class StorageStatusApiReleaseCheckTests(unittest.TestCase):
    """GET /gaon/storage/status runs the real deploy/scripts/
    storage_lifecycle_manager.py --report as a subprocess and relays its
    JSON - proven against a temp directory, not the real /var/lib/
    strategylab, so this passes on any dev machine."""

    def test_release_check_passes(self) -> None:
        payload = production_gaon_storage_status_api_release_check()
        for key in (
            "report_status_ok",
            "report_has_tier_bytes",
            "report_has_disk_usage",
            "report_never_destructive",
            "missing_script_is_clean_error",
        ):
            self.assertTrue(payload[key], key)
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])
        self.assertEqual(payload["safety"], "pass")


class StorageStatusApiCliWiringTests(unittest.TestCase):
    """CLI wiring for production_gaon_storage_status_api_release_check,
    following the exact existing gaon-production-*-release-check pattern."""

    def test_storage_status_api_release_check_cli_passes(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from gaon.runtime.cli import main as cli_main

        output = StringIO()
        with redirect_stdout(output):
            exit_code = cli_main(["gaon-production-storage-status-api-release-check"])
        self.assertEqual(exit_code, 0)
        printed = output.getvalue()
        self.assertIn("gaon-production-storage-status-api-release-check: PASS", printed)


class WebApiRootReleaseCheckTests(unittest.TestCase):
    def test_root_release_check_passes(self) -> None:
        payload = production_gaon_web_api_root_release_check()
        self.assertEqual(payload["service"], "Gaon Web API")
        self.assertEqual(payload["safety"], "pass")

    def test_root_release_check_cli_passes(self) -> None:
        from gaon.runtime.cli import main as cli_main
        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = cli_main(["gaon-production-web-api-root-release-check"])

        printed = buffer.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("gaon-production-web-api-root-release-check: PASS", printed)
        self.assertIn("strategy_mutated=false", printed)
        self.assertIn("safety=pass", printed)


class ConversationLifecycleEndpointsTests(unittest.TestCase):
    """Hotfix #166: new/archive/delete/list/paginate for web conversations,
    kept strictly separate from ResearchMission/StrategyCandidate/
    Cognitive Core durable state (see gaon.runtime.conversation_lifecycle
    module docstring)."""

    def test_list_conversations_orders_most_recently_updated_first(self) -> None:
        adapter = _adapter()
        dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "안녕하세요", "session_ref": "a", "user_ref": "u1"})
        dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "안녕하세요", "session_ref": "b", "user_ref": "u1"})

        status, payload = dispatch_request(adapter, method="GET", path="/gaon/chat/conversations?user_ref=u1", body=None)

        self.assertEqual(status, 200)
        refs = [c["session_ref"] for c in payload["conversations"]]
        self.assertEqual(refs, ["b", "a"])
        self.assertEqual(payload["conversations"][0]["message_count"], 2)
        self.assertFalse(payload["strategy_mutated"])

    def test_list_conversations_requires_user_ref(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(adapter, method="GET", path="/gaon/chat/conversations", body=None)
        self.assertEqual(status, 400)

    def test_list_conversations_is_scoped_per_user(self) -> None:
        adapter = _adapter()
        dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "안녕하세요", "session_ref": "a", "user_ref": "u1"})
        dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "안녕하세요", "session_ref": "c", "user_ref": "u2"})

        status, payload = dispatch_request(adapter, method="GET", path="/gaon/chat/conversations?user_ref=u1", body=None)
        self.assertEqual([c["session_ref"] for c in payload["conversations"]], ["a"])

    def test_messages_pagination_returns_oldest_first_within_a_page_and_cursor_for_next(self) -> None:
        adapter = _adapter()
        for i in range(5):
            dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": f"메시지 {i}", "session_ref": "a", "user_ref": "u1"})
        # 5 turns -> 10 messages (user+assistant each)

        status, page1 = dispatch_request(adapter, method="GET", path="/gaon/chat/messages?session_ref=a&user_ref=u1&limit=4", body=None)
        self.assertEqual(status, 200)
        self.assertEqual(len(page1["messages"]), 4)
        self.assertTrue(page1["has_more"])
        created_ats = [m["created_at"] for m in page1["messages"]]
        self.assertEqual(created_ats, sorted(created_ats))

        status, page2 = dispatch_request(
            adapter, method="GET", path=f"/gaon/chat/messages?session_ref=a&user_ref=u1&limit=4&before={page1['next_before']}", body=None
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(page2["messages"]), 4)
        page1_ids = {m["message_id"] for m in page1["messages"]}
        page2_ids = {m["message_id"] for m in page2["messages"]}
        self.assertEqual(page1_ids & page2_ids, set())

    def test_messages_endpoint_for_unknown_conversation_is_404(self) -> None:
        adapter = _adapter()
        status, payload = dispatch_request(adapter, method="GET", path="/gaon/chat/messages?session_ref=nope&user_ref=u1", body=None)
        self.assertEqual(status, 404)

    def test_archive_and_unarchive_round_trip(self) -> None:
        adapter = _adapter()
        dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "안녕하세요", "session_ref": "a", "user_ref": "u1"})

        status, payload = dispatch_request(adapter, method="POST", path="/gaon/chat/conversations/archive", body={"session_ref": "a", "user_ref": "u1"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "archived")

        status, listed = dispatch_request(adapter, method="GET", path="/gaon/chat/conversations?user_ref=u1&include_archived=false", body=None)
        self.assertEqual(listed["conversations"], [])

        status, payload = dispatch_request(adapter, method="POST", path="/gaon/chat/conversations/unarchive", body={"session_ref": "a", "user_ref": "u1"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "active")
        status, listed = dispatch_request(adapter, method="GET", path="/gaon/chat/conversations?user_ref=u1&include_archived=false", body=None)
        self.assertEqual(len(listed["conversations"]), 1)

    def test_archive_by_a_different_user_is_rejected_as_not_found(self) -> None:
        adapter = _adapter()
        dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "안녕하세요", "session_ref": "a", "user_ref": "u1"})
        status, payload = dispatch_request(adapter, method="POST", path="/gaon/chat/conversations/archive", body={"session_ref": "a", "user_ref": "someone-else"})
        self.assertEqual(status, 404)

    def test_delete_requires_explicit_confirmation(self) -> None:
        adapter = _adapter()
        dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "안녕하세요", "session_ref": "a", "user_ref": "u1"})

        status, payload = dispatch_request(adapter, method="POST", path="/gaon/chat/conversations/delete", body={"session_ref": "a", "user_ref": "u1"})
        self.assertEqual(status, 400)
        status, payload = dispatch_request(adapter, method="POST", path="/gaon/chat/conversations/delete", body={"session_ref": "a", "user_ref": "u1", "confirm": False})
        self.assertEqual(status, 400)

        status, listed = dispatch_request(adapter, method="GET", path="/gaon/chat/messages?session_ref=a&user_ref=u1", body=None)
        self.assertEqual(len(listed["messages"]), 2, "unconfirmed delete attempts must not remove anything")

    def test_delete_removes_messages_but_preserves_research_mission_and_candidate(self) -> None:
        adapter = _adapter()
        candidate = _seed_mission_with_one_candidate(adapter, "a")
        mission_before = adapter.mission_for("a")
        self.assertIsNotNone(mission_before)

        status, payload = dispatch_request(adapter, method="POST", path="/gaon/chat/conversations/delete", body={"session_ref": "a", "user_ref": "u1", "confirm": True})

        self.assertEqual(status, 200)
        self.assertTrue(payload["research_mission_preserved"])
        self.assertGreater(payload["deleted_message_count"], 0)

        status, messages = dispatch_request(adapter, method="GET", path="/gaon/chat/messages?session_ref=a&user_ref=u1", body=None)
        self.assertEqual(messages["messages"], [])

        mission_after = adapter.mission_for("a")
        self.assertIsNotNone(mission_after)
        self.assertEqual(mission_after.mission_id, mission_before.mission_id)
        self.assertEqual(len(mission_after.candidates), 1)
        self.assertEqual(mission_after.candidates[0]["candidate_id"], candidate.candidate_id)

    def test_deleted_conversation_is_excluded_from_the_list_but_session_survives(self) -> None:
        adapter = _adapter()
        _seed_mission_with_one_candidate(adapter, "a")
        dispatch_request(adapter, method="POST", path="/gaon/chat/conversations/delete", body={"session_ref": "a", "user_ref": "u1", "confirm": True})

        status, listed = dispatch_request(adapter, method="GET", path="/gaon/chat/conversations?user_ref=u1", body=None)
        self.assertEqual(listed["conversations"], [])
        # the session row itself (and its mission state) still exists -
        # only its message-list visibility changed.
        self.assertIsNotNone(adapter.mission_for("a"))

    def test_delete_by_a_different_user_is_rejected_and_changes_nothing(self) -> None:
        adapter = _adapter()
        dispatch_request(adapter, method="POST", path="/gaon/chat", body={"message": "안녕하세요", "session_ref": "a", "user_ref": "u1"})

        status, payload = dispatch_request(adapter, method="POST", path="/gaon/chat/conversations/delete", body={"session_ref": "a", "user_ref": "someone-else", "confirm": True})
        self.assertEqual(status, 404)

        status, listed = dispatch_request(adapter, method="GET", path="/gaon/chat/messages?session_ref=a&user_ref=u1", body=None)
        self.assertEqual(len(listed["messages"]), 2)


class ConversationLifecycleDurableStateReleaseCheckTests(unittest.TestCase):
    def test_release_check_passes(self) -> None:
        payload = production_conversation_lifecycle_durable_state_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertTrue(payload["research_mission_preserved"])
        self.assertTrue(payload["user_cognitive_goal_preserved"])
        self.assertTrue(payload["sustainability_objective_preserved"])
        self.assertTrue(payload["no_repository_table_changed"])
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])

    def test_release_check_cli_passes(self) -> None:
        import contextlib
        import io

        from gaon.runtime.cli import main as cli_main

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = cli_main(["gaon-production-conversation-lifecycle-durable-state-release-check"])

        self.assertEqual(exit_code, 0)
        printed = buffer.getvalue()
        self.assertIn("gaon-production-conversation-lifecycle-durable-state-release-check: PASS", printed)
        self.assertIn("safety=pass", printed)


if __name__ == "__main__":
    unittest.main()
