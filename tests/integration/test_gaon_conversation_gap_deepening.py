"""Gaon roadmap #217 follow-up: conversation deepening / auto gap analysis /
research preferences / CASE 1-9 regressions.

Builds directly on PR #216 (runtime-truth core - see
``test_gaon_capability_runtime_truth.py``, whose fixture/harness shape this
file reuses) WITHOUT reimplementing it: the fake provider, mission seeding
and Web-transport harness below mirror that file exactly. This file adds
regression coverage for the twelve exact CASE 1-9 Korean utterances the
roadmap follow-up names, plus the new ``research_preferences`` and
``gap_analysis`` modules.

No real network call is made anywhere in this file - the assistant
provider is a fake / fixture double, exactly like every other Gaon
conversation test.
"""

from __future__ import annotations

import sqlite3
import unittest

from gaon.knowledge.research_mission import MissionStatus, extract_or_update_mission
from gaon.runtime import llm_conversation
from gaon.runtime.assistant_provider import ProviderUnavailableError
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.gaon_agent.gap_analysis import diagnose_gap, is_gap_fill_request
from gaon.runtime.gaon_agent.research_preferences import (
    ResearchPreferences,
    extract_research_preferences,
    mentions_research_preferences,
    reconcile_with_mission,
    render_research_preferences_summary,
)
from gaon.runtime.migrations import migrate
from gaon.runtime.web_api import GaonWebChatAdapter

NOW = "2026-09-11T09:00:00Z"
SEED_AT = "2026-09-11T08:59:00Z"

_MISSION_SEED_TEXT = (
    "국내 주식 전체(코스피+코스닥)를 대상으로 수익과 안전성을 개선하는 단타 전략을 "
    "연구해주세요. 승격 가능한 후보 3개까지."
)

_INTERNAL_LEAKAGE_PATTERNS: tuple[str, ...] = (
    "Traceback",
    "CapabilityRegistry",
    "ProviderRuntimeMonitor",
    "BlockerKind.",
    "RuntimeReason.",
    "NoneType",
    "self.",
    "def _",
    "class ",
    "Exception:",
    "gaon.runtime",
    "gaon.knowledge",
)


def _assert_no_internal_leakage(testcase: unittest.TestCase, text: str, ctx: str = "") -> None:
    for pattern in _INTERNAL_LEAKAGE_PATTERNS:
        testcase.assertNotIn(pattern, text, f"{ctx}: leaked internal token {pattern!r}")


def _mission(*, blocked: bool) -> dict:
    mission = extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=SEED_AT)
    if blocked:
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


class _Provider:
    """Same fake provider shape as PR #216's runtime-truth tests."""

    def __init__(self, *, mode: str = "unreachable") -> None:
        self.calls = 0
        self.prompts: list[str] = []
        self.mode = mode

    def respond(self, request):  # noqa: ANN001 - test double
        self.calls += 1
        self.prompts.append(request.prompt or request.text)
        if self.mode == "unreachable":
            raise ProviderUnavailableError("assistant provider request failed")
        return llm_conversation.AssistantProviderResponse(
            text="영하님, 우주가 어두운 이유는 별빛이 유한한 속도로 오고 우주가 팽창하고 있기 때문입니다.",
            provider_name="openai-compatible",
        )


class GaonConversationGapDeepeningTests(unittest.TestCase):
    """CASE 1-9, on the Web transport (mirrors ``GaonWebRuntimeTruthTests``)."""

    def setUp(self) -> None:
        self._conn = sqlite3.connect(":memory:")
        self.addCleanup(self._conn.close)
        migrate(self._conn)
        self._provider = _Provider()
        original = llm_conversation.build_assistant_provider
        llm_conversation.build_assistant_provider = lambda _config: self._provider
        self.addCleanup(setattr, llm_conversation, "build_assistant_provider", original)
        self._adapter = GaonWebChatAdapter(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self._conn,
        )
        self._mid = 0

    def _seed_mission(self, *, blocked: bool) -> None:
        repo = llm_conversation.SQLiteConversationRepository(self._conn)
        session_id = "web:case-tests"
        try:
            session = repo.get_session(session_id)
            metadata = dict(session.metadata)
            created_at = session.created_at
            user_ref = session.user_ref
        except KeyError:
            metadata = {"owner": "gaon"}
            created_at = SEED_AT
            user_ref = "seed-user"
        metadata["conversation_mvp"] = {"schema_version": 1, "research_mission": _mission(blocked=blocked)}
        repo.upsert_session(
            llm_conversation.LLMConversationSession(
                session_id, user_ref, "web", "active", created_at, SEED_AT, metadata
            )
        )

    def _send(self, text: str) -> dict:
        self._mid += 1
        payload = dict(
            self._adapter.handle(
                message=text,
                session_ref="case-tests",
                user_ref="u-case-tests",
                read_only=False,
                received_at=NOW,
            )
        )
        return {
            "text": payload["text"],
            "route": payload["route"],
            "tool_calls": tuple(payload.get("tool_calls", ())),
        }

    # ================================================================
    # CASE 1 - "우주는 왜 어두운가요?" must never be forced into
    # finance/research routing and must never be answered from a stale
    # mission blocker.
    # ================================================================
    def test_case1_general_knowledge_question_healthy_provider(self) -> None:
        self._provider.mode = "ok"
        self._seed_mission(blocked=True)
        payload = self._send("우주는 왜 어두운가요?")
        self.assertNotIn(payload["route"], {"conversation_gap_analysis", "conversation_research_preferences"})
        self.assertNotIn("단타", payload["text"])
        self.assertGreaterEqual(self._provider.calls, 1)
        _assert_no_internal_leakage(self, payload["text"], "CASE1 healthy")

    def test_case1_general_knowledge_question_offline_provider_is_honest(self) -> None:
        self._provider.mode = "unreachable"
        self._seed_mission(blocked=True)
        payload = self._send("우주는 왜 어두운가요?")
        self.assertEqual(payload["route"], "conversation_runtime_unavailable")
        self.assertNotIn("단타", payload["text"])
        self.assertIn("연결할 수 없", payload["text"])

    # ================================================================
    # CASE 2 - "연구 상태 알려줘" must answer from the durable mission read
    # model even while the LLM is offline.
    # ================================================================
    def test_case2_research_status_survives_llm_offline(self) -> None:
        self._provider.mode = "unreachable"
        self._seed_mission(blocked=False)
        payload = self._send("연구 상태 알려줘")
        self.assertNotEqual(payload["route"], "conversation_runtime_unavailable")
        self.assertIn("단타", payload["text"])
        self.assertEqual(payload["tool_calls"], ())

    # ================================================================
    # CASE 3 - "부족한 부분을 채워주세요" must never ask "무엇이 부족한가요"
    # back; it must self-diagnose from mission + blocker + capability truth.
    # ================================================================
    def test_case3_gap_fill_with_no_active_mission_asks_for_the_one_real_input_needed(self) -> None:
        payload = self._send("부족한 부분을 채워주세요")
        self.assertEqual(payload["route"], "conversation_gap_analysis")
        self.assertNotIn("무엇이 부족", payload["text"])
        self.assertIn("연구를 시작", payload["text"])

    def test_case3_gap_fill_with_blocked_mission_translates_blocker_into_a_need(self) -> None:
        self._seed_mission(blocked=True)
        payload = self._send("부족한 부분을 채워주세요")
        self.assertEqual(payload["route"], "conversation_gap_analysis")
        self.assertNotIn("무엇이 부족", payload["text"])
        self.assertNotIn("strategy_hypothesis_space_exhausted", payload["text"])
        self.assertIn("다음 단계는 새로운 전략 가설군 또는 추가 데이터/검증 축을 확장하는 것입니다", payload["text"])
        _assert_no_internal_leakage(self, payload["text"], "CASE3 blocked")

    # ================================================================
    # CASE 4 / 5 - a URL's capability-limitation reply must stay the
    # tracked subject; a bare "이건요?" follow-up must not jump to an
    # unrelated mission blocker.
    # ================================================================
    def test_case4_url_input_uses_the_honest_url_limitation_lane(self) -> None:
        self._seed_mission(blocked=True)
        payload = self._send("https://www.instagram.com/p/DcHnMH-kzA5/")
        self.assertEqual(payload["route"], "conversation_capability_limited_url")
        self.assertIn("링크를 직접 열어", payload["text"])
        self.assertNotIn("단타", payload["text"])

    def test_case5_bare_reference_after_url_keeps_the_url_subject(self) -> None:
        self._seed_mission(blocked=True)
        self._send("https://www.instagram.com/p/DcHnMH-kzA5/")
        payload = self._send("이건요?")
        self.assertEqual(payload["route"], "conversation_capability_limitation_subject_followup")
        self.assertIn("링크를 직접 열어", payload["text"])
        self.assertNotIn("단타", payload["text"])
        self.assertNotIn("strategy_hypothesis_space_exhausted", payload["text"])

    # ================================================================
    # CASE 6 - "방법을 찾아주세요" must not leak internal tool/class names
    # or demand low-level parameters from the user.
    # ================================================================
    def test_case6_find_a_way_request_has_no_internal_leakage(self) -> None:
        self._seed_mission(blocked=True)
        payload = self._send("방법을 찾아주세요")
        _assert_no_internal_leakage(self, payload["text"], "CASE6")
        self.assertNotIn("파라미터를 알려주세요", payload["text"])

    # ================================================================
    # CASE 7 - "스스로 찾아서 연구해주세요" must never claim progress that
    # did not actually happen; a BLOCKED mission is reported as blocked,
    # never as "완료했습니다" / "찾았습니다".
    # ================================================================
    def test_case7_autonomous_research_request_never_fabricates_progress_when_blocked(self) -> None:
        self._seed_mission(blocked=True)
        payload = self._send("스스로 찾아서 연구해주세요")
        self.assertNotIn("연구를 완료했습니다", payload["text"])
        self.assertNotIn("승격했습니다", payload["text"])
        _assert_no_internal_leakage(self, payload["text"], "CASE7")

    # ================================================================
    # CASE 8 - "찾았나요?" continues the same goal, it must not jump to an
    # unrelated topic and must not fabricate a "found it" claim with no
    # underlying evidence.
    # ================================================================
    def test_case8_did_you_find_it_stays_on_the_same_mission_context(self) -> None:
        self._seed_mission(blocked=True)
        self._send("스스로 찾아서 연구해주세요")
        payload = self._send("찾았나요?")
        self.assertNotIn("찾았습니다, 영하님. 정답은", payload["text"])
        _assert_no_internal_leakage(self, payload["text"], "CASE8")

    # ================================================================
    # CASE 9 - a durable KR/KOSPI+KOSDAQ/market-wide/단타 mission must
    # never be re-asked about market/symbol/KR scope on a plain "단타
    # 연구해주세요" continuation.
    # ================================================================
    def test_case9_daytrade_continuation_does_not_reask_known_scope(self) -> None:
        self._seed_mission(blocked=False)
        payload = self._send("단타 연구해주세요")
        for reask_marker in ("어느 시장", "어떤 시장", "국내 주식인가요", "코스피인가요", "종목을 알려"):
            self.assertNotIn(reask_marker, payload["text"])


class ResearchPreferencesTests(unittest.TestCase):
    """Unit coverage for ``research_preferences`` - aspirational safety."""

    def test_extracts_all_required_fields(self) -> None:
        prefs = extract_research_preferences(
            "국내 주식 코스피+코스닥 단타 전략으로 1분,5분,15분,30분봉을 보면서 "
            "승률 70%, 하루 3~30% 수익률을 목표로 연구해주세요"
        )
        self.assertEqual(prefs.market_scope, "KR_KOSPI_KOSDAQ")
        self.assertEqual(prefs.trading_style, "short_term_intraday")
        self.assertEqual(prefs.timeframes, ("1m", "5m", "15m", "30m"))
        self.assertEqual(prefs.target_win_rate_pct, 70.0)
        self.assertEqual(prefs.aspirational_daily_return_range_pct, (3.0, 30.0))

    def test_plain_mission_creation_text_does_not_trigger_preferences(self) -> None:
        # Regression guard: this is the EXACT existing mission-creation
        # wording used across the #216 test suite - it must never be
        # hijacked into a preferences-reconciliation reply.
        self.assertFalse(mentions_research_preferences(_MISSION_SEED_TEXT))

    def test_summary_never_states_a_guarantee(self) -> None:
        prefs = ResearchPreferences(target_win_rate_pct=70.0, aspirational_daily_return_range_pct=(3.0, 30.0))
        summary = "\n".join(render_research_preferences_summary(prefs))
        # The negation ("보장이 아닌") is required, not forbidden - what must
        # never appear is an affirmative guarantee/promise claim.
        for forbidden in ("보장합니다", "보장된", "약속합니다", "확정된 수익", "guarantee", "promise"):
            self.assertNotIn(forbidden, summary)
        self.assertIn("보장이 아닌", summary)
        self.assertIn("연구 목표", summary)

    def test_reconcile_does_not_claim_persistence(self) -> None:
        text = reconcile_with_mission(None, ResearchPreferences(target_win_rate_pct=70.0))
        self.assertIn("저장되지는 않습니다", text)

    def test_reconcile_keeps_existing_mission_scope_authoritative(self) -> None:
        mission = extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=SEED_AT)
        prefs = ResearchPreferences(timeframes=("1m", "5m"))
        text = reconcile_with_mission(mission, prefs)
        self.assertIn(mission.mission_id, text)
        self.assertIn("새 Mission을 만들지 않고", text)


class GapAnalysisTests(unittest.TestCase):
    """Unit coverage for ``gap_analysis`` - blocker -> Need translation."""

    def test_is_gap_fill_request_requires_both_a_gap_noun_and_a_fill_verb(self) -> None:
        self.assertTrue(is_gap_fill_request("부족한 부분을 채워주세요"))
        self.assertFalse(is_gap_fill_request("표본이 부족합니다"))
        self.assertFalse(is_gap_fill_request("이 링크 좀 채워주실 수 있나요"))

    def test_diagnose_gap_with_no_mission_asks_for_the_one_real_input(self) -> None:
        result = diagnose_gap(None)
        self.assertEqual(result.mission_summary, "no_active_mission")
        self.assertEqual(len(result.needs), 1)
        self.assertTrue(result.needs[0].requires_user_input)

    def test_diagnose_gap_translates_the_exhausted_hypothesis_space_blocker(self) -> None:
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
        result = diagnose_gap(mission)
        self.assertNotIn("strategy_hypothesis_space_exhausted", result.text)
        self.assertIn("다음 단계는 새로운 전략 가설군 또는 추가 데이터/검증 축을 확장하는 것입니다", result.text)
        self.assertFalse(result.needs[0].requires_user_input)

    def test_diagnose_gap_active_mission_reports_no_gap(self) -> None:
        mission = extract_or_update_mission(_MISSION_SEED_TEXT, existing=None, now=SEED_AT)
        result = diagnose_gap(mission)
        self.assertEqual(result.mission_summary, "active_no_gap")
        self.assertEqual(result.needs, ())


if __name__ == "__main__":
    unittest.main()
