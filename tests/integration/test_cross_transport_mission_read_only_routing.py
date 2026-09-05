"""Regression tests for fix/cross-transport-mission-read-routing.

Production symptom (confirmed against production, read-only, before this
branch): owner config loaded correctly (PR #181's owner_ref/owner_telegram_
chat_ids/owner_web_user_refs), the Web request's identity was correct
(stored user_ref matched the configured owner_web_user_refs entry exactly),
and the Telegram owning session's authoritative ResearchMission existed in
the database (KR / market_wide / short_term_daytrade, 16 real candidates,
active_candidate_id=KR-ST-016) - yet a fresh, correctly-configured-owner Web
session's explicit mission-status question ("단타 연구는 잘되고 있나요?")
was answered via route=provider_tool_call / tool_calls=["research_operation_
status"] (a generic, mission-unaware status tool reading a completely
different data model - research_quality/strategy_config/rollback audit rows,
never ResearchMission/StrategyCandidateRecord) instead of PR #181's own new
durable-owner-mission-aware read path.

Root cause: the request carried read_only=True (GaonWebChatAdapter.handle
appends a literal " readonly" suffix to the message text for any Web call
with read_only=True - e.g. a diagnostic parity-check script calling POST
/gaon/chat directly, which is exactly what a session_ref like
"production-owner-parity-check" suggests happened in production).
_is_conversational_mvp_source (from hotfix/conversation-layer-safe-web-
parity, predating PR #181) unconditionally excludes ANY Web message ending
in that marker from the entire conversational-MVP pipeline - including
_resolve_durable_owner_mission, is_research_progress_status_question, and
is_mission_candidate_read_request, all added or reused by PR #181. That
exclusion was written to stop a BARE, non-research runtime ping ("가온
상태 알려줘" + the marker) from being misread as a mission question, but it
was never narrowed to admit a message that was ALREADY, on its own words, a
genuine mission-status/candidate-read question - so PR #181's new owner-
aware read capability could never activate for any Web caller using
read_only=True, regardless of whether the durable owner mission existed.

Why PR #181's own tests never caught this: every test in
test_cross_transport_owner_research_mission.py calls GaonWebChatAdapter.
handle(..., read_only=False, ...) - PR #181 added a new mission-aware READ
capability but never combined it with read_only=True; the older read_only-
probe carve-out's own tests, in turn, only ever used a bare non-research
ping ("가온 상태 알려줘"), never a real owner-configured durable-mission
question. Each feature's own tests passed; the interaction between them was
never exercised until now.

Fix: _is_conversational_mvp_source now checks the MARKER-STRIPPED
underlying text against the SAME two predicates (is_research_progress_
status_question / is_mission_candidate_read_request) _try_conversational_
mvp itself already uses further down to answer such a question
deterministically with zero research tool calls. A bare, non-research
runtime ping still satisfies neither once the marker is stripped (its own
explicit-read-only-marker branch inside is_mission_candidate_read_request
only ever fires when that marker text is STILL present, which it no longer
is here), so it keeps being excluded exactly as before - only a message
that was already, on its own words, an honestly-answerable mission read/
status question is newly admitted.
"""

from __future__ import annotations

import json
import unittest

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import add_candidate, extract_or_update_mission, next_candidate_sequence
from gaon.knowledge.strategy_candidate import ALL_STRATEGY_FAMILY_TEMPLATES, new_candidate
from gaon.runtime.assistant_provider import (
    AssistantProviderResponse,
    AssistantToolCall,
    ProviderCapabilities,
    ProviderHealth,
)
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationRequest, _is_conversational_mvp_source
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-05T00:00:00Z"
OWNER_CHAT_ID = "8767020479"
OWNER_WEB_REF = "binance-dashboard-operator"
OWNER_REF = "youngha-owner"


def _owner_config(**overrides) -> GaonRuntimeConfig:
    defaults = dict(
        telegram_allowed_chat_ids=(OWNER_CHAT_ID,),
        owner_ref=OWNER_REF,
        owner_telegram_chat_ids=(OWNER_CHAT_ID,),
        owner_web_user_refs=(OWNER_WEB_REF,),
        assistant_enabled=True,
        assistant_provider="deterministic",
    )
    defaults.update(overrides)
    return GaonRuntimeConfig(**defaults)


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"sent:{len(self.sent)}", message_id=str(len(self.sent)))


def _telegram_update(update_id: int, text: str, *, chat_id: str, user_id: str | None = None) -> dict:
    resolved_user_id = user_id if user_id is not None else f"{chat_id}9"
    return {
        "update_id": update_id,
        "message": {"message_id": update_id, "chat": {"id": int(chat_id)}, "from": {"id": int(resolved_user_id)}, "text": text},
    }


def _telegram_send(config: GaonRuntimeConfig, connection, text: str, *, chat_id: str = OWNER_CHAT_ID, update_id: int = 1) -> str:
    agent = TelegramConversationAgent(config, connection)
    runtime = TelegramRuntime(agent, allowed_chat_ids=(chat_id,))
    client = _FakeTelegramClient()
    process_update(parse_update_result(_telegram_update(update_id, text, chat_id=chat_id), received_at=NOW), runtime, client)
    return client.sent[-1][1]


def _seed_telegram_market_wide_daytrade_mission(config: GaonRuntimeConfig, connection, *, chat_id: str = OWNER_CHAT_ID, candidate_count: int = 16):
    """Seeds a real, already-persisted KR/market-wide/short_term_daytrade
    mission with real candidates - reproducing the exact confirmed
    production state (16 candidates, active candidate KR-ST-016)."""
    mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
    for index in range(candidate_count):
        template = ALL_STRATEGY_FAMILY_TEMPLATES[index % len(ALL_STRATEGY_FAMILY_TEMPLATES)]
        candidate = new_candidate(template.family, sequence=next_candidate_sequence(mission), now=NOW)
        mission = add_candidate(mission, candidate, now=NOW)
    agent = TelegramConversationAgent(config, connection)
    runtime = TelegramRuntime(agent, allowed_chat_ids=(chat_id,))
    client = _FakeTelegramClient()
    process_update(parse_update_result(_telegram_update(0, "안녕하세요", chat_id=chat_id), received_at=NOW), runtime, client)
    agent._brain._remember_mission(
        LLMConversationRequest(session_id=f"telegram:{chat_id}", user_ref=f"telegram-user:{chat_id}", source="telegram", text="x", received_at=NOW),
        mission,
    )
    return mission


class _GenericToolCallingFakeProvider:
    """Simulates a real LLM assistant provider that, given a turn with no
    conversational-MVP framing at all, picks a plausible generic READ_ONLY
    tool - exactly what production's own logs showed
    (tool_calls=["research_operation_status"]). Used to prove the ROUTING
    decision (never reaching this provider at all for a genuine mission
    question), not the provider's own intelligence, is what this fix
    changes. ``self.calls`` staying 0 is the strongest possible proof that
    the mission-aware, zero-tool-call path was used instead."""

    def __init__(self) -> None:
        self.calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake-llm", "fake-model", True, False, 2000)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake-llm", True, 5)

    def respond(self, request) -> AssistantProviderResponse:
        self.calls += 1
        if not request.tool_results:
            return AssistantProviderResponse(
                text="확인해보겠습니다.",
                route="provider_tool_call",
                provider_name="fake-llm",
                tool_calls=(AssistantToolCall("call-1", "research_operation_status", {}),),
            )
        return AssistantProviderResponse(
            text="현재 활성화된 연구 운영 결과가 없어 단타 연구의 진행 상황을 확인할 수 없습니다.",
            route="provider_tool_call",
            provider_name="fake-llm",
        )


def _web_send_with_fake_provider(config: GaonRuntimeConfig, connection, text: str, *, session_ref: str, user_ref: str, read_only: bool) -> tuple[dict, _GenericToolCallingFakeProvider]:
    adapter = GaonWebChatAdapter(config, connection)
    fake_provider = _GenericToolCallingFakeProvider()
    adapter._brain._assistant_provider = fake_provider
    result = adapter.handle(message=text, session_ref=session_ref, user_ref=user_ref, read_only=read_only, received_at=NOW)
    return result, fake_provider


def _authoritative_mission_id(connection, session_id: str) -> str | None:
    row = connection.execute("SELECT metadata_json FROM conversation_sessions WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    metadata = json.loads(row[0])
    root = metadata.get("conversation_mvp")
    if not isinstance(root, dict):
        return None
    raw_mission = root.get("research_mission")
    if not isinstance(raw_mission, dict):
        return None
    return raw_mission.get("mission_id")


_MISSION_AWARE_READ_ROUTES = {
    "conversation_mission_status_read",
    "conversation_mission_candidate_read",
    "conversation_mission_no_active_candidate",
    "conversation_mission_blocked",
}


class ReadOnlyProbeExclusionUnitTests(unittest.TestCase):
    """Direct unit coverage of _is_conversational_mvp_source's narrowed
    read_only-probe exclusion - the exact function this fix changes."""

    def test_bare_non_research_ping_with_read_only_marker_stays_excluded(self) -> None:
        request = LLMConversationRequest(
            session_id="web:release-check", user_ref="web-user:release-check-user", source="web",
            text="가온 상태 알려줘 readonly", received_at=NOW, message_id="web:release-check:1",
        )
        self.assertFalse(_is_conversational_mvp_source(request))

    def test_genuine_mission_status_question_with_read_only_marker_is_admitted(self) -> None:
        request = LLMConversationRequest(
            session_id="web:x", user_ref=f"web-user:{OWNER_WEB_REF}", source="web",
            text="단타 연구는 잘되고 있나요? readonly", received_at=NOW, message_id="web:x:1",
        )
        self.assertTrue(_is_conversational_mvp_source(request))

    def test_genuine_mission_status_question_without_read_only_marker_unaffected(self) -> None:
        request = LLMConversationRequest(
            session_id="web:x", user_ref=f"web-user:{OWNER_WEB_REF}", source="web",
            text="단타 연구는 잘되고 있나요?", received_at=NOW, message_id="web:x:2",
        )
        self.assertTrue(_is_conversational_mvp_source(request))


class FreshWebOwnerReadOnlyMissionStatusReadTests(unittest.TestCase):
    """Requirement 1 + the exact production reproduction: a fresh,
    configured-owner Web session's read_only mission-status question must
    read the real durable owner mission, never fall through to a generic
    provider tool."""

    def test_fresh_web_owner_read_only_status_question_reads_durable_mission_not_generic_tool(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            result, fake_provider = _web_send_with_fake_provider(
                config, store._connection, "단타 연구는 잘되고 있나요?",
                session_ref="production-owner-parity-check", user_ref=OWNER_WEB_REF, read_only=True,
            )
            self.assertIn(result["route"], _MISSION_AWARE_READ_ROUTES)
            self.assertEqual(result["tool_calls"], [])
            self.assertNotIn("research_operation_status", result["tool_calls"])
            # Strongest proof: the generic assistant provider was never even
            # reached for this turn - the mission-aware deterministic read
            # path answered it directly.
            self.assertEqual(fake_provider.calls, 0)
            for candidate in mission.candidates:
                self.assertIn(candidate["candidate_id"], result["text"])
        finally:
            store.close()


class FreshTelegramOwnerSameQuestionTests(unittest.TestCase):
    """Requirement 2: the same question from Telegram reads the SAME
    authoritative mission (unaffected by this Web-only fix)."""

    def test_fresh_telegram_owner_reads_same_mission(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            reply = _telegram_send(config, store._connection, "단타 연구는 잘되고 있나요?", update_id=1)
            for candidate in mission.candidates:
                self.assertIn(candidate["candidate_id"], reply)
        finally:
            store.close()


class NonOwnerWebIsolationUnderReadOnlyTests(unittest.TestCase):
    """Requirement 5: a Web caller whose user_ref is NOT a configured owner
    must never see the owner's durable mission, even under read_only."""

    def test_non_owner_web_caller_does_not_see_owner_mission(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            adapter = GaonWebChatAdapter(config, store._connection)
            result = adapter.handle(
                message="단타 연구는 잘되고 있나요?", session_ref="some-other-caller",
                user_ref="not-the-configured-owner", read_only=True, received_at=NOW,
            )
            self.assertNotIn("KOSPI", result["text"])
            self.assertNotIn("KR-ST-016", result["text"])
        finally:
            store.close()


class MultipleCompatibleMissionsStillClarifyTests(unittest.TestCase):
    """Requirement 3: two distinct compatible durable missions for the
    owner must force clarification, never an arbitrary/latest pick - even
    under read_only."""

    def test_two_compatible_missions_clarify_instead_of_picking_latest(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config(owner_web_user_refs=(OWNER_WEB_REF,))
            _seed_telegram_market_wide_daytrade_mission(config, store._connection, chat_id=OWNER_CHAT_ID, candidate_count=2)
            # A second, DISTINCT compatible mission (same family/market)
            # durably owned by the SAME configured Web owner identity.
            second_mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략을 연구해주세요", existing=None, now=NOW)
            adapter = GaonWebChatAdapter(config, store._connection)
            adapter.handle(message="안녕하세요", session_ref="second-owner-session", user_ref=OWNER_WEB_REF, read_only=False, received_at=NOW)
            adapter._brain._remember_mission(
                LLMConversationRequest(session_id="web:second-owner-session", user_ref=f"web-user:{OWNER_WEB_REF}", source="web", text="x", received_at=NOW),
                second_mission,
            )
            result = adapter.handle(
                message="단타 연구는 잘되고 있나요?", session_ref="fresh-ambiguous-check",
                user_ref=OWNER_WEB_REF, read_only=True, received_at=NOW,
            )
            self.assertEqual(result["route"], "conversation_durable_mission_ambiguous")
            self.assertEqual(result["tool_calls"], [])
        finally:
            store.close()


class IncompatibleMissionNotSelectedTests(unittest.TestCase):
    """Requirement 4: an explicitly named, incompatible strategy family
    must never be answered from a different family's durable mission."""

    def test_incompatible_family_request_does_not_return_daytrade_mission(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            adapter = GaonWebChatAdapter(config, store._connection)
            result = adapter.handle(
                message="스윙 연구는 잘되고 있나요?", session_ref="incompatible-family-check",
                user_ref=OWNER_WEB_REF, read_only=True, received_at=NOW,
            )
            self.assertNotIn("KR-ST-016", result["text"])
            self.assertNotEqual(result["route"], "conversation_mission_candidate_read")
        finally:
            store.close()


class ReadDoesNotCopyMissionIntoWebSessionTests(unittest.TestCase):
    """Requirement 9: single-source-of-truth is preserved - a read-only
    status question must never fork a duplicate authoritative mission copy
    into the requesting Web session."""

    def test_web_session_gets_no_authoritative_mission_copy(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            result, _fake = _web_send_with_fake_provider(
                config, store._connection, "단타 연구는 잘되고 있나요?",
                session_ref="production-owner-parity-check", user_ref=OWNER_WEB_REF, read_only=True,
            )
            self.assertIn(result["route"], _MISSION_AWARE_READ_ROUTES)
            web_mission_id = _authoritative_mission_id(store._connection, "web:production-owner-parity-check")
            self.assertIsNone(web_mission_id, "read-only status read must never copy the mission into the Web session")
            telegram_mission_id = _authoritative_mission_id(store._connection, f"telegram:{OWNER_CHAT_ID}")
            self.assertEqual(telegram_mission_id, mission.mission_id)
        finally:
            store.close()


class OmittedSubjectExecutionStillFailsClosedTests(unittest.TestCase):
    """Requirement 7: an ambiguous, omitted-subject execution request
    ("그거 다시 연구해줘") in a fresh Web session must still fail closed -
    this fix must not widen execution permission even under read_only."""

    def test_omitted_subject_request_fails_closed_with_read_only(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            adapter = GaonWebChatAdapter(config, store._connection)
            result = adapter.handle(
                message="그거 다시 연구해줘", session_ref="fresh-omitted-subject-check",
                user_ref=OWNER_WEB_REF, read_only=True, received_at=NOW,
            )
            self.assertEqual(result["tool_calls"], [])
            self.assertFalse(result["strategy_mutated"])
            self.assertFalse(result["order_executed"])
            self.assertFalse(result["champion_promoted"])
            self.assertFalse(result["approval_bypassed"])
        finally:
            store.close()


class ExplicitContinuationExecutionGateUnaffectedTests(unittest.TestCase):
    """Requirement 8: the existing deterministic execution gate for an
    explicit continuation ("단타 연구 계속해줘") is unchanged by this fix -
    this PR must not broaden execution permission."""

    def test_explicit_continuation_still_executes_through_existing_gate(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            mission = _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            adapter = GaonWebChatAdapter(config, store._connection)
            result = adapter.handle(
                message="단타 연구 계속해줘", session_ref="explicit-continuation-check",
                user_ref=OWNER_WEB_REF, read_only=False, received_at=NOW,
            )
            self.assertEqual(result["tool_calls"], ["multi_symbol_research"])
            telegram_mission_id = _authoritative_mission_id(store._connection, f"telegram:{OWNER_CHAT_ID}")
            self.assertEqual(telegram_mission_id, mission.mission_id)
        finally:
            store.close()


class NoUnsafeSideEffectsOnReadTests(unittest.TestCase):
    """Explicit safety guard: a read-only mission-status question must
    never mutate strategy, execute an order, promote a Champion, or bypass
    approval."""

    def test_read_only_status_question_reports_no_unsafe_side_effects(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            config = _owner_config()
            _seed_telegram_market_wide_daytrade_mission(config, store._connection)
            result, _fake = _web_send_with_fake_provider(
                config, store._connection, "단타 연구는 잘되고 있나요?",
                session_ref="production-owner-parity-check", user_ref=OWNER_WEB_REF, read_only=True,
            )
            self.assertFalse(result["strategy_mutated"])
            self.assertFalse(result["order_executed"])
            self.assertFalse(result["champion_promoted"])
            self.assertFalse(result["approval_bypassed"])
            self.assertFalse(result["approval_required"])
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
