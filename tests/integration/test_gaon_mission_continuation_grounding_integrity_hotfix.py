"""Regression tests for the mission-continuation-grounding-integrity hotfix
(branch hotfix/gaon-mission-continuation-grounding-integrity).

Context: a post-#218 production re-verification (once the earlier owner-
mapping/request-contract defect was fixed) found two further real defects
against the live production mission (KR/KOSPI+KOSDAQ/short_term_daytrade,
BLOCKED on ``strategy_hypothesis_space_exhausted``):

  A. BLOCKED MISSION FALSE REACTIVATION
     (``gaon.knowledge.research_mission.extract_or_update_mission``) - a
     single continuation-shaped message ("...계속 연구해줘") silently
     flipped a mission BLOCKED on a STRUCTURAL, non-retryable reason
     straight to ACTIVE, leaving the stale ``blocked_reason`` behind (an
     inconsistent ACTIVE+exhausted-reason state). Fixed by
     ``is_retryable_mission_blocker`` - a small, deterministic,
     fail-closed policy gate on the existing (not newly-invented) blocked-
     reason taxonomy.

  B. PROVIDER/TOOL-CALL GROUNDING BYPASS
     (``gaon.runtime.research_grounding.ground_provider_user_reply`` /
     ``LLMConversationBrain._execute_provider_tool_calls``) - the #218
     raw-provider hygiene/state-claim gate only ran on the no-tool-call
     free-text branch; a provider reply that happened to invoke a tool
     returned straight past it, so it could still re-ask for scope
     (market/strategy/symbol) the durable mission already records, or
     assert an ungrounded promotion/approval state. Fixed by extracting
     ONE shared gate both branches now call, plus a new deterministic
     "known-context re-ask" detector
     (``research_grounding.requests_known_mission_context``).

  A narrower, related fix: the legacy ``_try_autonomous_research_
  conversation``/``_try_autonomous_learning_v2_conversation`` "no context
  at all" dead ends could tell the real owner "직전 연구나 전략 맥락이
  없습니다" while their real durable mission existed - see
  ``LLMConversationBrain._durable_mission_grounded_no_context_fallback``.

No real network call anywhere in this file - every assistant provider is a
scripted fake double.
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.knowledge.research_mission import (
    MissionStatus,
    extract_or_update_mission,
    is_retryable_mission_blocker,
)
from gaon.runtime.assistant_provider import (
    AssistantProviderResponse,
    AssistantToolCall,
    ProviderCapabilities,
    ProviderHealth,
)
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import (
    LLMConversationBrain,
    LLMConversationRequest,
    LLMConversationSession,
    SQLiteConversationRepository,
)
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.migrations import migrate

from test_gaon_production_conversation_hotfix import _DurableOwnerMissionHarness

SEED_AT = "2026-08-17T00:00:00Z"
LATER = "2026-08-18T00:00:00Z"
_MISSION_SEED_TEXT = (
    "국내 주식 전체(코스피+코스닥)를 대상으로 수익과 안전성을 개선하는 단타 전략을 "
    "연구해주세요. 승격 가능한 후보 3개까지."
)
_STRUCTURAL_REASON = "strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted"
_RETRYABLE_REASON = "provider_acquisition_blocker: symbol=005930,category=timeout"
_UNKNOWN_REASON = "some_future_classification_nobody_has_taxonomized_yet"


def _mission_blocked_with(reason: str):
    mission = extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=SEED_AT)
    return mission.__class__.from_json({**mission.to_json(), "status": MissionStatus.BLOCKED.value, "blocked_reason": reason})


# ===========================================================================
# A. BLOCKED mission false reactivation - extract_or_update_mission's
# continuation-driven BLOCKED -> ACTIVE transition must only ever fire for a
# known, deterministically-classified RETRYABLE blocker.
# ===========================================================================
class BlockedMissionReactivationPolicyTests(unittest.TestCase):
    def test_is_retryable_mission_blocker_matches_the_real_taxonomy(self) -> None:
        # The only two retryable/transient codes actually produced anywhere
        # in this codebase (every record_blocked call site).
        self.assertTrue(is_retryable_mission_blocker("provider_acquisition_blocker: x"))
        self.assertTrue(is_retryable_mission_blocker("data_acquisition"))
        # The two known STRUCTURAL codes must never be treated as retryable.
        self.assertFalse(is_retryable_mission_blocker("strategy_hypothesis_space_exhausted: x"))
        self.assertFalse(is_retryable_mission_blocker("selected_symbol_universe_exhausted"))
        # Fail-closed defaults.
        self.assertFalse(is_retryable_mission_blocker(None))
        self.assertFalse(is_retryable_mission_blocker(""))
        self.assertFalse(is_retryable_mission_blocker("some_unclassified_dynamic_code"))

    def test_structural_blocker_is_never_auto_reactivated_by_continuation(self) -> None:
        mission = _mission_blocked_with(_STRUCTURAL_REASON)
        updated = extract_or_update_mission("계속 연구해줘", existing=mission, now=LATER)
        self.assertIs(updated.status, MissionStatus.BLOCKED)
        self.assertEqual(updated.mission_id, mission.mission_id)
        self.assertEqual(updated.blocked_reason, _STRUCTURAL_REASON)

    def test_structural_blocker_is_never_auto_reactivated_by_market_wide_rescope(self) -> None:
        # kr_market_wide is the OTHER trigger condition in the same branch -
        # must be gated identically, not just the continuation path.
        mission = _mission_blocked_with(_STRUCTURAL_REASON)
        updated = extract_or_update_mission("코스피 전체로 다시 연구해줘", existing=mission, now=LATER)
        self.assertIs(updated.status, MissionStatus.BLOCKED)
        self.assertEqual(updated.blocked_reason, _STRUCTURAL_REASON)

    def test_unknown_blocker_fails_closed_and_stays_blocked(self) -> None:
        mission = _mission_blocked_with(_UNKNOWN_REASON)
        updated = extract_or_update_mission("계속 연구해줘", existing=mission, now=LATER)
        self.assertIs(updated.status, MissionStatus.BLOCKED)
        self.assertEqual(updated.blocked_reason, _UNKNOWN_REASON)

    def test_retryable_blocker_allows_reactivation_and_clears_stale_reason(self) -> None:
        mission = _mission_blocked_with(_RETRYABLE_REASON)
        updated = extract_or_update_mission("계속 연구해줘", existing=mission, now=LATER)
        self.assertIs(updated.status, MissionStatus.ACTIVE)
        self.assertIsNone(updated.blocked_reason)
        self.assertEqual(updated.mission_id, mission.mission_id)

    def test_active_mission_is_unaffected_by_the_policy(self) -> None:
        mission = extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=SEED_AT)
        self.assertIs(mission.status, MissionStatus.ACTIVE)
        updated = extract_or_update_mission("계속 연구해줘", existing=mission, now=LATER)
        self.assertIs(updated.status, MissionStatus.ACTIVE)
        self.assertIsNone(updated.blocked_reason)


# ===========================================================================
# B. Provider/tool-call grounding bypass - the SAME shared grounding gate
# must apply whether the provider returned raw free text or executed a tool
# call first.
# ===========================================================================
class _FixedTextProvider:
    """Always returns the same free text, no tool call."""

    def __init__(self, text: str) -> None:
        self._text = text

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake", "fake-fixed-text", False, False, 500)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake", True)

    def respond(self, request) -> AssistantProviderResponse:
        return AssistantProviderResponse(text=self._text, provider_name="fake", route="provider")


class _ToolThenTextProvider:
    """First call returns a scripted tool call; the second call (after
    tool_results are attached) returns ``final_text`` - mirrors the real
    two-round-trip shape ``_execute_provider_tool_calls`` drives."""

    def __init__(self, tool_calls: tuple[AssistantToolCall, ...], final_text: str) -> None:
        self._tool_calls = tool_calls
        self._final_text = final_text

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake", "fake-tool-then-text", False, False, 500)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake", True)

    def respond(self, request) -> AssistantProviderResponse:
        if request.tool_results:
            return AssistantProviderResponse(text=self._final_text, provider_name="fake", route="provider")
        return AssistantProviderResponse(text="", provider_name="fake", route="provider", tool_calls=self._tool_calls)


class ProviderReplySharedGroundingGateTests(unittest.TestCase):
    """Mission seeded directly on the request's own session - no cross-
    transport fallback needed to isolate the grounding-gate behaviour
    itself (that seam is already covered by the #218 hotfix suite and by
    the multi-intent tests below)."""

    SESSION_ID = "web:defect-b-grounding-session"

    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        migrate(self.connection)
        self.repository = SQLiteConversationRepository(self.connection)
        self.executor = SafeToolExecutor(default_tool_registry(self.connection), SQLiteToolAuditRepository(self.connection))
        self._seed_blocked_mission()

    def _seed_blocked_mission(self) -> None:
        mission = _mission_blocked_with(_STRUCTURAL_REASON)
        metadata = {"owner": "gaon", "conversation_mvp": {"schema_version": 1, "research_mission": mission.to_json()}}
        self.repository.upsert_session(
            LLMConversationSession(self.SESSION_ID, "web-user:owner", "web", "active", SEED_AT, SEED_AT, metadata)
        )

    def _brain(self, provider) -> LLMConversationBrain:
        return LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self.repository,
            tool_executor=self.executor,
            assistant_provider=provider,
        )

    def _request(self, text: str) -> LLMConversationRequest:
        return LLMConversationRequest(self.SESSION_ID, "web-user:owner", "web", text, LATER, f"message:{text}")

    def test_raw_provider_generic_reask_is_replaced_with_mission_grounded_reply(self) -> None:
        # production repro 1: "방법을 찾아주세요" -> route=provider ->
        # differently-worded generic re-ask the fixed 6-phrase marker list
        # never caught.
        provider = _FixedTextProvider("어떤 분야의 방법을 찾으시는지 알려주세요.")
        response = self._brain(provider).respond(self._request("방법을 찾아주세요"))
        self.assertEqual(response.route, "provider")
        self.assertNotIn("어떤 분야의 방법을 찾으시는지", response.text)
        self.assertIn("단타", response.text)

    def test_tool_call_reply_reasking_known_symbol_scope_is_replaced(self) -> None:
        # production repro 2 (CASE 9): "단타 연구해주세요" -> tool_calls=
        # ["market_data"] -> route=provider_tool_call -> re-asks for the
        # stock code the mission already has. Must not reach the user.
        provider = _ToolThenTextProvider(
            (AssistantToolCall("call-1", "runtime_status", {}),),
            "구체적인 종목 코드(예: 005930)와 연구 기간, 전략 목표를 알려주시면 도와드리겠습니다.",
        )
        response = self._brain(provider).respond(self._request("단타 연구해주세요"))
        self.assertEqual(response.route, "provider_tool_call")
        self.assertNotIn("종목 코드", response.text)
        self.assertIn("단타", response.text)

    def test_tool_call_reply_false_promotion_state_claim_is_replaced(self) -> None:
        # authoritative mission is BLOCKED, 0/3 promotion-ready, no active
        # candidate - a tool-call reply falsely claiming approval-pending
        # state must never reach the user.
        provider = _ToolThenTextProvider(
            (AssistantToolCall("call-1", "runtime_status", {}),),
            "승격 요청 대기 중이며 사용자 승인이 필요합니다.",
        )
        response = self._brain(provider).respond(self._request("단타 연구해주세요"))
        self.assertEqual(response.route, "provider_tool_call")
        self.assertNotIn("승격 요청 대기", response.text)
        self.assertNotIn("사용자 승인", response.text)
        self.assertIn("단타", response.text)

    def test_tool_call_reply_with_no_violation_passes_through_unchanged(self) -> None:
        # No false positives: a clean tool-call reply must not be altered.
        provider = _ToolThenTextProvider(
            (AssistantToolCall("call-1", "runtime_status", {}),),
            "런타임 상태를 확인했습니다, 영하님.",
        )
        response = self._brain(provider).respond(self._request("가온 상태 알려줘"))
        self.assertEqual(response.text, "런타임 상태를 확인했습니다, 영하님.")

    def test_raw_provider_reply_with_no_violation_passes_through_unchanged(self) -> None:
        provider = _FixedTextProvider("피보나치 수열은 앞의 두 수를 더해 다음 수를 만드는 수열입니다.")
        response = self._brain(provider).respond(self._request("피보나치 수열이 뭔가요?"))
        self.assertEqual(response.text, "피보나치 수열은 앞의 두 수를 더해 다음 수를 만드는 수열입니다.")


# ===========================================================================
# G. Multi-intent - durable mission recognition inside the legacy
# autonomous-learning "no context" dead end, combined with the Defect A
# reactivation-policy fix (both apply on the SAME real production phrase).
# ===========================================================================
class MultiIntentDurableMissionGroundingTests(_DurableOwnerMissionHarness):
    _PHRASE = "현재 연구 상태 알려주고 부족한 자료도 인터넷에서 찾아서 계속 연구해줘"

    def test_recognizes_durable_mission_and_never_claims_no_context(self) -> None:
        payload = self._send(self._PHRASE)
        self.assertNotIn("맥락이 없습니다", payload["text"])
        self.assertIn("단타", payload["text"])

    def test_structural_blocker_survives_the_multi_intent_continuation_phrase(self) -> None:
        self._send(self._PHRASE)
        status_payload = self._send("연구 상태 알려줘")
        self.assertEqual(status_payload["route"], "conversation_mission_blocked")

    def test_stays_honest_about_missing_internet_fetch_capability(self) -> None:
        payload = self._send(self._PHRASE)
        self.assertIn("인터넷", payload["text"])

    def test_never_fabricates_research_completion_or_promotion(self) -> None:
        payload = self._send(self._PHRASE)
        for phrase in ("검증을 완료", "승격했습니다", "승격되었습니다", "찾았습니다", "완료했습니다"):
            self.assertNotIn(phrase, payload["text"])


if __name__ == "__main__":
    unittest.main()
