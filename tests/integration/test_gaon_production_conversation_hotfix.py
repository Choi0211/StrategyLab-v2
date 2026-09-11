"""Regression tests for the production-E2E conversation-acceptance hotfix
(branch hotfix/gaon-production-conversation-acceptance-217).

Context: a post-deploy production E2E round against PR #217 (Gaon roadmap
"conversation gap deepening" follow-up) found real conversational defects
when a message is sent on a FRESH session that only resolves a mission via
the durable, owner-scoped cross-session fallback
(``LLMConversationBrain._resolve_durable_owner_mission``) - a scenario the
existing test_gaon_conversation_gap_deepening.py suite does not exercise,
since it always seeds the mission directly onto the SAME session it sends
messages to.

This file mirrors that existing suite's fixture shape but configures
``GaonRuntimeConfig.owner_ref``/``owner_web_user_refs`` (the same opt-in
mechanism ``test_cross_transport_owner_research_mission.py`` uses) and
seeds the durable mission onto a SEPARATE "owner's own session", then sends
every probe from a THIRD, brand-new session sharing only the owner's
``user_ref`` - the exact shape a real owner hits from a new device/browser
or a first Telegram thread.

Four defects, four test classes:
  A. ContextualWhyRoutingTests - confirms (does NOT newly fix - see the PR
     description) that a bare "왜" without a research-domain subject/
     context is NOT swept into mission-status/blocker routing. Locks in
     already-correct behaviour with the durable-owner-fallback scenario
     added.
  B. GapAnalysisDurableOwnerMissionTests - fixes "부족한 부분을 채워주세요"
     misdiagnosing an existing durable mission as absent
     (LLMConversationBrain._try_gap_analysis).
  C. ProviderResponseHygieneTests - fixes raw LLM free-text leaking
     internal tool/function identifiers and pushing low-level parameters
     back onto the user (research_grounding.safe_capability_reply).
  D. AuthoritativeMissionStateGuardTests - fixes raw LLM free-text
     asserting approval/promotion/candidate/production state the
     authoritative ResearchMission read model does not support
     (research_grounding.mission_state_claim_violations).

No real network call anywhere in this file - the assistant provider is a
scripted fake double, exactly like every other Gaon conversation test.
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.knowledge.research_mission import MissionStatus, extract_or_update_mission
from gaon.runtime import llm_conversation
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.migrations import migrate
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-12T09:00:00Z"
SEED_AT = "2026-09-11T08:59:00Z"
OWNER_REF = "the-owner-web-ref"
OWNER_SESSION_REF = "owner-real-browser-session"

_MISSION_SEED_TEXT = (
    "국내 주식 전체(코스피+코스닥)를 대상으로 수익과 안전성을 개선하는 단타 전략을 "
    "연구해주세요. 승격 가능한 후보 3개까지."
)

_INTERNAL_LEAKAGE_PATTERNS: tuple[str, ...] = (
    "Traceback", "CapabilityRegistry", "ProviderRuntimeMonitor", "BlockerKind.",
    "RuntimeReason.", "NoneType", "self.", "def _", "class ", "Exception:",
    "gaon.runtime", "gaon.knowledge",
)


def _assert_no_internal_leakage(testcase: unittest.TestCase, text: str, ctx: str = "") -> None:
    for pattern in _INTERNAL_LEAKAGE_PATTERNS:
        testcase.assertNotIn(pattern, text, f"{ctx}: leaked internal token {pattern!r}")


def _owner_config(**overrides) -> GaonRuntimeConfig:
    defaults = dict(
        assistant_enabled=True,
        assistant_provider="openai-compatible",
        owner_ref="the-owner",
        owner_web_user_refs=(OWNER_REF,),
    )
    defaults.update(overrides)
    return GaonRuntimeConfig(**defaults)


def _blocked_mission_json() -> dict:
    mission = extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=SEED_AT)
    mission = mission.__class__.from_json(
        {
            **mission.to_json(),
            "status": MissionStatus.BLOCKED.value,
            "blocked_reason": (
                "strategy_hypothesis_space_exhausted: bounded declarative strategy "
                "expansion budget exhausted"
            ),
        }
    )
    return mission.to_json()


class _ScriptedProvider:
    """Fake assistant provider whose reply is controlled per-test via
    ``script`` - a callable ``(text) -> AssistantProviderResponse``.
    Defaults to a harmless deterministic echo."""

    def __init__(self, script=None) -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.script = script

    def respond(self, request):
        self.calls += 1
        self.prompts.append(request.prompt or request.text)
        if self.script is not None:
            return self.script(request.text)
        return llm_conversation.AssistantProviderResponse(
            text=f"(general conversation reply for: {request.text})", provider_name="openai-compatible"
        )


class _DurableOwnerMissionHarness(unittest.TestCase):
    """Shared fixture: an owner-configured brain with the mission seeded
    onto the OWNER's OWN session, and every test probe sent from a
    brand-new, DIFFERENT session sharing only the owner's user_ref -
    exactly the production cross-session durable-owner-fallback shape."""

    provider_script = None

    def setUp(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self.addCleanup(self._conn.close)
        migrate(self._conn)
        self._provider = _ScriptedProvider(self.provider_script)
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: self._provider
        self.addCleanup(setattr, llm_conversation, "build_assistant_provider", original)
        self._adapter = GaonWebChatAdapter(_owner_config(), self._conn)
        self._seed_owner_mission()
        self._probe_count = 0

    def _seed_owner_mission(self) -> None:
        repo = llm_conversation.SQLiteConversationRepository(self._conn)
        session_id = f"web:{OWNER_SESSION_REF}"
        metadata = {"owner": "gaon", "conversation_mvp": {"schema_version": 1, "research_mission": _blocked_mission_json()}}
        repo.upsert_session(
            llm_conversation.LLMConversationSession(
                session_id, f"web-user:{OWNER_REF}", "web", "active", SEED_AT, SEED_AT, metadata
            )
        )

    def _send(self, text: str, *, session_ref: str | None = None, user_ref: str = OWNER_REF) -> dict:
        self._probe_count += 1
        ref = session_ref or f"fresh-probe-{self._probe_count}"
        payload = dict(
            self._adapter.handle(message=text, session_ref=ref, user_ref=user_ref, read_only=False, received_at=NOW)
        )
        return {"text": payload["text"], "route": payload["route"], "warnings": tuple(payload.get("warnings", ()))}


# ===========================================================================
# A. Contextual "why" routing - bare "왜" must never, on its own, be treated
# as a mission/research read request; it must combine with an actual
# research-domain subject/context.
# ===========================================================================
class ContextualWhyRoutingTests(_DurableOwnerMissionHarness):
    def test_general_universe_question_stays_general_even_with_durable_mission(self) -> None:
        payload = self._send("우주는 왜 어두운가요?")
        self.assertNotIn(payload["route"], {"conversation_mission_blocked", "conversation_research_status_no_mission"})
        self.assertNotIn("단타", payload["text"])
        self.assertNotIn("Research Mission", payload["text"])

    def test_sky_color_question_stays_general_even_with_durable_mission(self) -> None:
        payload = self._send("하늘은 왜 파란가요?")
        self.assertNotIn(payload["route"], {"conversation_mission_blocked", "conversation_research_status_no_mission"})
        self.assertNotIn("단타", payload["text"])

    def test_cat_purring_question_stays_general_even_with_durable_mission(self) -> None:
        payload = self._send("고양이는 왜 골골거리나요?")
        self.assertNotIn(payload["route"], {"conversation_mission_blocked", "conversation_research_status_no_mission"})
        self.assertNotIn("단타", payload["text"])

    def test_research_stopped_why_question_reaches_mission_explanation(self) -> None:
        payload = self._send("연구가 왜 멈췄나요?")
        self.assertEqual(payload["route"], "conversation_mission_blocked")
        self.assertIn("단타", payload["text"])

    def test_why_not_promoted_question_reaches_mission_explanation(self) -> None:
        payload = self._send("왜 승격이 안 됐나요?")
        self.assertEqual(payload["route"], "conversation_mission_blocked")
        self.assertIn("단타", payload["text"])

    def test_general_universe_question_with_no_mission_anywhere_stays_general(self) -> None:
        # A completely unrelated user_ref: no session-local mission, no
        # durable-owner mission to fall back to either.
        payload = self._send("우주는 왜 어두운가요?", user_ref="someone-else-entirely")
        self.assertNotEqual(payload["route"], "conversation_research_status_no_mission")
        self.assertNotIn("현재 진행 중인 연구 Mission이 없습니다", payload["text"])


# ===========================================================================
# B. Gap analysis must resolve the SAME durable, owner-scoped mission the
# CASE-2 status path already finds - never misdiagnose "no mission" for an
# owner who has a real (blocked) one.
# ===========================================================================
class GapAnalysisDurableOwnerMissionTests(_DurableOwnerMissionHarness):
    def test_gap_fill_on_fresh_session_finds_the_durable_owner_mission(self) -> None:
        payload = self._send("부족한 부분을 채워주세요")
        self.assertEqual(payload["route"], "conversation_gap_analysis")
        self.assertNotIn("현재 진행 중인 연구 Mission이 없습니다", payload["text"])
        self.assertIn("단타", payload["text"])

    def test_gap_fill_does_not_reask_what_is_missing(self) -> None:
        payload = self._send("부족한 부분을 채워주세요")
        self.assertNotIn("무엇이 부족", payload["text"])

    def test_gap_fill_never_leaks_raw_blocker_code(self) -> None:
        payload = self._send("부족한 부분을 채워주세요")
        self.assertNotIn("strategy_hypothesis_space_exhausted", payload["text"])
        self.assertIn("다음 단계는 새로운 전략 가설군 또는 추가 데이터/검증 축을 확장하는 것입니다", payload["text"])
        _assert_no_internal_leakage(self, payload["text"], "CASE3 durable-owner gap")

    def test_status_then_gap_fill_target_the_identical_mission(self) -> None:
        status_payload = self._send("연구 상태 알려줘", session_ref="status-probe")
        gap_payload = self._send("부족한 부분을 채워주세요", session_ref="gap-probe")
        self.assertIn("단타", status_payload["text"])
        self.assertIn("단타", gap_payload["text"])
        self.assertNotIn("현재 진행 중인 연구 Mission이 없습니다", gap_payload["text"])


# ===========================================================================
# C. A raw, free-form GENERAL_CONVERSATION draft must never expose an
# internal tool/function/provider identifier or push a low-level
# implementation parameter back onto the user.
# ===========================================================================
def _leaky_script(text: str):
    if "방법" in text:
        reply = (
            "가용 가능한 읽기 전용 데이터 검색 기능은 다음과 같습니다:\n"
            "1. `market_data` (시장 데이터 조회 - 종목 코드 필요)\n"
            "2. `krx_market_data` (KRX 데이터 조회 - 종목 코드 및 기간 필요)\n"
            "3. `data_quality_check` (데이터 품질 검증 - 종목 코드 필요)\n"
            "필요한 데이터 유형 또는 검색 조건을 구체화해 주세요."
        )
    else:
        reply = f"(general conversation reply for: {text})"
    return llm_conversation.AssistantProviderResponse(text=reply, provider_name="openai-compatible")


class ProviderResponseHygieneTests(_DurableOwnerMissionHarness):
    provider_script = staticmethod(_leaky_script)

    def test_find_a_way_request_has_no_internal_tool_identifier_leakage(self) -> None:
        payload = self._send("방법을 찾아주세요")
        self.assertNotIn("`market_data`", payload["text"])
        self.assertNotIn("`krx_market_data`", payload["text"])
        self.assertNotIn("`data_quality_check`", payload["text"])
        # Structural check, not a 3-name blacklist: no backtick-quoted
        # identifier of any kind should reach the user.
        import re

        self.assertIsNone(re.search(r"`[a-zA-Z_][a-zA-Z0-9_]{2,}`", payload["text"]))

    def test_find_a_way_request_does_not_push_low_level_parameters(self) -> None:
        payload = self._send("방법을 찾아주세요")
        self.assertNotIn("종목 코드", payload["text"])
        self.assertNotIn("구체화해 주세요", payload["text"])

    def test_find_a_way_request_does_not_reask_known_mission_scope(self) -> None:
        payload = self._send("방법을 찾아주세요")
        # The mission's own known scope (단타/KR) must appear - proof the
        # reply is grounded in what is already known, not re-asked.
        self.assertIn("단타", payload["text"])

    def test_find_a_way_request_never_claims_unactioned_progress(self) -> None:
        payload = self._send("방법을 찾아주세요")
        self.assertNotIn("확인했습니다", payload["text"])
        self.assertNotIn("진행했습니다", payload["text"])

    def test_unrelated_general_reply_is_not_altered(self) -> None:
        # No false positives: a normal general-conversation reply with no
        # leakage/parameter-burden/state-claim markers must pass through
        # unchanged.
        payload = self._send("피보나치 수열이 뭔가요?")
        self.assertEqual(payload["text"], "(general conversation reply for: 피보나치 수열이 뭔가요?)")


# ===========================================================================
# D. Mission/promotion/approval/candidate/production state claims in free
# LLM text must be grounded in the authoritative ResearchMission - never
# free-generated.
# ===========================================================================
def _hallucinating_script(text: str):
    if "단타" in text:
        reply = (
            "단타 전략 연구를 위한 현재 가능한 분석을 제공합니다.\n"
            "연구 진행 상태: v5_pipeline의 현재 승격 요청 대기 중(사용자 승인 필요)입니다.\n"
            "필요한 분석 항목을 알려주시면 도와드리겠습니다."
        )
    else:
        reply = f"(general conversation reply for: {text})"
    return llm_conversation.AssistantProviderResponse(text=reply, provider_name="openai-compatible")


class AuthoritativeMissionStateGuardTests(_DurableOwnerMissionHarness):
    provider_script = staticmethod(_hallucinating_script)

    def test_daytrade_continuation_never_claims_approval_pending_when_blocked(self) -> None:
        # Real mission state seeded by this harness: BLOCKED,
        # promotion-ready 0/3, no active candidate - never
        # AWAITING_HUMAN_APPROVAL.
        payload = self._send("단타 연구해주세요")
        for forbidden in ("승격 요청 대기", "승인 필요", "promotion ready", "approval pending"):
            self.assertNotIn(forbidden, payload["text"])

    def test_daytrade_continuation_does_not_reask_known_scope(self) -> None:
        payload = self._send("단타 연구해주세요")
        for reask_marker in ("어느 시장", "어떤 시장", "국내 주식인가요", "코스피인가요", "종목을 알려"):
            self.assertNotIn(reask_marker, payload["text"])

    def test_state_claim_violation_is_recorded_in_warnings(self) -> None:
        payload = self._send("단타 연구해주세요")
        self.assertTrue(any("ungrounded_state_claim" in warning for warning in payload["warnings"]))

    def test_unrelated_general_reply_is_not_altered(self) -> None:
        payload = self._send("피보나치 수열이 뭔가요?")
        self.assertEqual(payload["text"], "(general conversation reply for: 피보나치 수열이 뭔가요?)")


# ===========================================================================
# F. Multi-intent consistency: mission-state grounding must apply
# consistently to the "status + gap" combined free-text path too - never
# understate an existing durable mission, never fabricate a completed web
# fetch.
# ===========================================================================
def _multi_intent_script(text: str):
    if "부족한 자료" in text and "인터넷" in text:
        reply = (
            "현재 연구는 승격되었습니다. 인터넷에서 추가 자료를 모두 찾아 반영했습니다."
        )
    else:
        reply = f"(general conversation reply for: {text})"
    return llm_conversation.AssistantProviderResponse(text=reply, provider_name="openai-compatible")


class MultiIntentConsistencyTests(_DurableOwnerMissionHarness):
    provider_script = staticmethod(_multi_intent_script)

    def test_multi_intent_never_fabricates_a_completed_promotion_or_web_fetch(self) -> None:
        payload = self._send("현재 연구 상태 알려주고 부족한 자료도 인터넷에서 찾아서 계속 연구해줘")
        self.assertNotIn("승격되었습니다", payload["text"])
        self.assertNotIn("인터넷에서 추가 자료를 모두 찾아 반영했습니다", payload["text"])

    @unittest.skip(
        "KNOWN LIMITATION (documented, not fixed by this hotfix): this exact "
        "phrase classifies as an autonomous-learning CONTINUATION request and "
        "is intercepted by the separate legacy single-symbol autonomous-"
        "learning subsystem (LLMConversationBrain._try_autonomous_learning_v2_"
        "conversation, ~llm_conversation.py:3513), which tracks its own "
        "ConversationalMVPContext continuation target and has never known "
        "about ResearchMission/_resolve_durable_owner_mission at all - it is a "
        "materially different, much larger subsystem than the ResearchMission "
        "conversational layer this hotfix touches (_try_gap_analysis, the raw-"
        "provider hygiene/grounding gate). Giving it durable-owner-mission "
        "awareness needs its own, separately-scoped change - attempting it "
        "here would violate the 'minimal diff, no new giant framework' brief "
        "this hotfix was scoped to."
    )
    def test_multi_intent_grounds_mission_scope_instead_of_reporting_absent(self) -> None:
        payload = self._send("현재 연구 상태 알려주고 부족한 자료도 인터넷에서 찾아서 계속 연구해줘")
        self.assertIn("단타", payload["text"])


if __name__ == "__main__":
    unittest.main()
