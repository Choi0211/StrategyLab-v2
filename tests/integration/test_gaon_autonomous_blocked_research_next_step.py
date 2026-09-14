"""Regression tests for feature/gaon-autonomous-blocked-research-next-step.

Context: a durable market-wide KR/KOSPI+KOSDAQ/short_term_daytrade
ResearchMission structurally BLOCKED on ``strategy_hypothesis_space_
exhausted`` (the bounded declarative strategy-hypothesis grammar in
``gaon.knowledge.strategy_candidate`` is fully exhausted) used to have
every live-conversation continuation request ("단타 연구해주세요", "계속
연구해주세요", "부족한 부분을 채워주세요") dead-end at the same static,
always-identical blocked explanation - Gaon never tried the bounded
stagnation-recovery path the background autonomous-research tick already
runs for exactly this dead end (Hotfix #168/#169), and never reported a
diagnosis grounded in the mission's own real candidate history.

This suite exercises the fix through the real conversational stack (no
second/duplicate engine): ``LLMConversationBrain._try_mission_driven_
research_cycle`` and ``_try_gap_analysis`` (deterministic dispatch), and
``gaon.runtime.research_grounding.safe_capability_reply`` (the provider-
reply grounding gate a real LLM-routed turn goes through, mirroring the
original CASE D production repro for "단타 연구해주세요" against this exact
mission shape). Every assistant provider here is a scripted fake double or
the harness's harmless deterministic echo - no real network call.
"""

from __future__ import annotations

import sqlite3
import unittest
from dataclasses import replace

from gaon.knowledge.research_mission import (
    MissionStatus,
    add_candidate,
    extract_or_update_mission,
    get_active_candidate,
    next_candidate_sequence,
    record_blocked,
)
from gaon.knowledge.strategy_candidate import StrategyCandidateStatus, new_candidate
from gaon.runtime.assistant_provider import AssistantToolCall
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, LLMConversationSession, SQLiteConversationRepository
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.migrations import migrate

from test_gaon_production_conversation_hotfix import OWNER_REF, OWNER_SESSION_REF, SEED_AT as OWNER_SEED_AT, _DurableOwnerMissionHarness, _MISSION_SEED_TEXT
from test_gaon_mission_continuation_grounding_integrity_hotfix import (
    LATER,
    SEED_AT,
    _FixedTextProvider,
    _STRUCTURAL_REASON,
    _ToolThenTextProvider,
    _mission_blocked_with,
)

_SELECTED_SYMBOL_EXHAUSTED_REASON = "selected_symbol_universe_exhausted"
_RECOVERABLE_STAGNATION_REASON = "validation_cycle_exhausted_without_progress"

# The exact three trigger phrases named in the feature request, plus
# paraphrases of each - never the literal phrase repeated, a genuinely
# different wording of the same continuation/gap-fill intent.
_CONTINUATION_PHRASES = (
    "단타 연구해주세요",
    "단타 전략 계속 연구해줄래?",
    "계속 연구해주세요",
    "증거가 충분할 때까지 계속 연구해주세요",
)
_GAP_FILL_PHRASES = (
    "부족한 부분을 채워주세요",
    "부족한 부분 좀 채워줘",
)

_NEVER_ASK_USER_TO_CHOOSE_MARKERS = (
    "어떤 시장/전략 스타일로 연구를 시작할지",
    "알려주시면 바로 진행하겠습니다",
)


def _market_wide_mission_blocked_with(reason: str):
    return record_blocked(extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=OWNER_SEED_AT), reason=reason, now=OWNER_SEED_AT)


def _market_wide_mission_with_recoverable_candidate():
    mission = extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=OWNER_SEED_AT)
    stalled = new_candidate("breakout_standard", sequence=next_candidate_sequence(mission), now=OWNER_SEED_AT)
    stalled = replace(
        stalled, status=StrategyCandidateStatus.STAGNANT, rejected_reason=_RECOVERABLE_STAGNATION_REASON, cycles_without_progress=5
    )
    mission = add_candidate(mission, stalled, now=OWNER_SEED_AT)
    return record_blocked(mission, reason=_STRUCTURAL_REASON, now=OWNER_SEED_AT), stalled.candidate_id


class _SeededMissionHarness(_DurableOwnerMissionHarness):
    """Reuses the shared owner-mission harness, but seeds a caller-supplied
    mission JSON instead of the base class's fixed BLOCKED fixture."""

    mission_factory = staticmethod(lambda: _market_wide_mission_blocked_with(_STRUCTURAL_REASON))

    def _seed_owner_mission(self) -> None:
        repo = SQLiteConversationRepository(self._conn)
        session_id = f"web:{OWNER_SESSION_REF}"
        mission = self.mission_factory()
        metadata = {"owner": "gaon", "conversation_mvp": {"schema_version": 1, "research_mission": mission.to_json()}}
        repo.upsert_session(
            LLMConversationSession(session_id, f"web-user:{OWNER_REF}", "web", "active", OWNER_SEED_AT, OWNER_SEED_AT, metadata)
        )


# ===========================================================================
# A. Deterministic continuation dispatch - a structurally BLOCKED mission
# with no narrow-recovery-eligible candidate must answer with a concrete,
# evidence-grounded diagnosis instead of asking the user to choose a
# direction, for all three named trigger phrasings and their paraphrases.
# ===========================================================================
class StructuralBlockerAutonomousDiagnosisTests(_SeededMissionHarness):
    def test_continuation_phrasings_never_ask_the_user_to_choose_a_direction(self) -> None:
        for phrase in _CONTINUATION_PHRASES:
            with self.subTest(phrase=phrase):
                payload = self._send(phrase, session_ref=f"probe-{phrase}")
                for marker in _NEVER_ASK_USER_TO_CHOOSE_MARKERS:
                    self.assertNotIn(marker, payload["text"])
                self.assertNotIn("strategy_hypothesis_space_exhausted", payload["text"])
                self.assertIn("단타", payload["text"])

    def test_gap_fill_phrasings_never_ask_the_user_to_choose_a_direction(self) -> None:
        for phrase in _GAP_FILL_PHRASES:
            with self.subTest(phrase=phrase):
                payload = self._send(phrase, session_ref=f"probe-{phrase}")
                for marker in _NEVER_ASK_USER_TO_CHOOSE_MARKERS:
                    self.assertNotIn(marker, payload["text"])
                self.assertNotIn("무엇이 부족", payload["text"])
                self.assertNotIn("strategy_hypothesis_space_exhausted", payload["text"])

    def test_continuation_reaches_the_autonomous_direction_route(self) -> None:
        payload = self._send("계속 연구해주세요")
        self.assertEqual(payload["route"], "conversation_mission_blocked_autonomous_direction")
        self.assertIn("지금 안전하게 자동으로 실행할 수 있는 추가 조치는 없으며", payload["text"])

    def test_gap_fill_reaches_the_same_autonomous_direction_route_as_continuation(self) -> None:
        # Both phrasings must converge on the identical diagnosis for the
        # identical mission state - never two differently-worded answers.
        continuation_payload = self._send("계속 연구해주세요", session_ref="continuation-probe")
        gap_fill_payload = self._send("부족한 부분을 채워주세요", session_ref="gap-fill-probe")
        self.assertEqual(continuation_payload["route"], gap_fill_payload["route"])
        self.assertEqual(continuation_payload["text"], gap_fill_payload["text"])

    def test_never_claims_a_privileged_action_was_taken(self) -> None:
        payload = self._send("계속 연구해주세요")
        self.assertIn("전략 config 변경, 후보 승격, 주문 실행, 승인 우회는", payload["text"])
        self.assertIn("사람의 확인/승인이 필요한 부분만 남아 있습니다", payload["text"])


# ===========================================================================
# B. False positives - every OTHER blocked reason, and a non-blocked
# mission, must be completely unaffected by this feature.
# ===========================================================================
class StructuralBlockerScopeFalsePositiveTests(unittest.TestCase):
    def test_selected_symbol_universe_exhausted_is_unaffected(self) -> None:
        class Harness(_SeededMissionHarness):
            mission_factory = staticmethod(lambda: _market_wide_mission_blocked_with(_SELECTED_SYMBOL_EXHAUSTED_REASON))

            def runTest(self) -> None:
                pass

        harness = Harness()
        harness.setUp()
        payload = harness._send("계속 연구해주세요")
        self.assertEqual(payload["route"], "conversation_mission_blocked")
        self.assertIn("종목 범위 안에서는 더 확인할 새 종목이 남아 있지 않아", payload["text"])
        self.assertNotIn("지배적 원인", payload["text"])

    def test_transient_provider_blocker_is_unaffected(self) -> None:
        class Harness(_SeededMissionHarness):
            mission_factory = staticmethod(
                lambda: _market_wide_mission_blocked_with("provider_acquisition_blocker: symbol=005930,category=timeout")
            )

            def runTest(self) -> None:
                pass

        harness = Harness()
        harness.setUp()
        payload = harness._send("계속 연구해주세요")
        # A retryable/transient blocker is reactivated by
        # extract_or_update_mission before this feature's gate is ever
        # reached (unchanged pre-existing #219 policy) - it must never
        # surface the new structural diagnosis route.
        self.assertNotEqual(payload["route"], "conversation_mission_blocked_autonomous_direction")

    def test_single_symbol_request_never_creates_a_research_mission_at_all(self) -> None:
        # A single-symbol request is handled entirely by the separate
        # legacy single-symbol/autonomous-learning subsystem and never
        # creates a ResearchMission (see research_mission.extract_or_
        # update_mission) - confirming this here documents why this
        # feature (gated on an actual ResearchMission being BLOCKED) can
        # never fire for a plain single-symbol flow, preserving it by
        # construction rather than by a route-name assertion.
        mission = extract_or_update_mission("삼성전자 최근 분석해줘", existing=None, now=OWNER_SEED_AT)
        self.assertIsNone(mission)


# ===========================================================================
# C. Execute-when-allowed - a narrow-recovery-eligible STAGNANT candidate
# must actually resume the existing bounded research cycle, never just
# report a diagnosis.
# ===========================================================================
class StructuralBlockerRecoveryExecutesRealCycleTests(_SeededMissionHarness):
    mission_factory = staticmethod(lambda: _market_wide_mission_with_recoverable_candidate()[0])

    def test_continuation_executes_a_real_bounded_research_cycle_not_a_diagnosis(self) -> None:
        payload = self._send("계속 연구해주세요")
        self.assertNotIn(payload["route"], {"conversation_mission_blocked", "conversation_mission_blocked_autonomous_direction"})
        self.assertNotIn("strategy_hypothesis_space_exhausted", payload["text"])

    def test_recovered_cycle_still_discloses_every_safety_guarantee(self) -> None:
        payload = self._send("계속 연구해주세요")
        self.assertIn("자동 주문 없음", payload["text"])
        self.assertIn("Champion 자동 승격 없음", payload["text"])
        self.assertIn("승인 없는 config 변경 없음", payload["text"])


# ===========================================================================
# D. Provider-path grounding gate - mirrors the original CASE D production
# repro exactly (session seeded directly, no owner-mission cross-session
# resolution needed to isolate this behaviour): a scripted provider reply
# that re-asks scope the mission already records must be replaced by the
# NEW evidence-grounded diagnosis, not the older generic canned sentence,
# whenever the mission is BLOCKED on this specific structural reason.
# ===========================================================================
class ProviderPathAutonomousDiagnosisTests(unittest.TestCase):
    SESSION_ID = "web:autonomous-direction-provider-path-session"

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

    def test_tool_call_reply_reasking_known_symbol_scope_gets_the_new_diagnosis(self) -> None:
        # Same production repro _ToolThenTextProvider shape the original
        # CASE D fix (test_gaon_mission_continuation_grounding_integrity_
        # hotfix.Case9SymbolReaskCoverageGapTests) proved gets replaced;
        # this proves it is now replaced with the NEW diagnosis, not the
        # old static "다음 단계는 새로운 전략 가설군..." canned sentence.
        provider = _ToolThenTextProvider(
            (AssistantToolCall("call-1", "runtime_status", {}),),
            "구체적인 종목 코드(예: 005930)와 연구 기간, 전략 목표를 알려주시면 도와드리겠습니다.",
        )
        response = self._brain(provider).respond(self._request("단타 연구해주세요"))
        self.assertEqual(response.route, "provider_tool_call")
        self.assertNotIn("종목 코드", response.text)
        self.assertNotIn("strategy_hypothesis_space_exhausted", response.text)
        self.assertIn("지금 안전하게 자동으로 실행할 수 있는 추가 조치는 없으며", response.text)
        for marker in _NEVER_ASK_USER_TO_CHOOSE_MARKERS:
            self.assertNotIn(marker, response.text)

    def test_raw_text_reply_reasking_direction_gets_the_new_diagnosis(self) -> None:
        provider = _FixedTextProvider("어떤 분야의 방법을 찾으시는지 알려주세요.")
        response = self._brain(provider).respond(self._request("방법을 찾아주세요"))
        self.assertEqual(response.route, "provider")
        self.assertIn("지금 안전하게 자동으로 실행할 수 있는 추가 조치는 없으며", response.text)

    def test_clean_reply_with_no_violation_still_passes_through_unchanged(self) -> None:
        # No false positive: this feature only ever replaces an ALREADY-
        # violating reply; a clean, unrelated raw-text reply must be
        # untouched even with the same BLOCKED mission in scope.
        provider = _FixedTextProvider("피보나치 수열은 앞의 두 수를 더해 다음 수를 만드는 수열입니다.")
        response = self._brain(provider).respond(self._request("피보나치 수열이 뭔가요?"))
        self.assertEqual(response.text, "피보나치 수열은 앞의 두 수를 더해 다음 수를 만드는 수열입니다.")


if __name__ == "__main__":
    unittest.main()
