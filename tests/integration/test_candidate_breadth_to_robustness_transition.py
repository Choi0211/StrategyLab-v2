"""Patch 8.5 - candidate breadth -> robustness transition acceptance test.

Real production defect this reproduces and proves fixed: after a market-
wide strategy candidate's breadth evaluation gathered sufficient cross-
symbol evidence (``ResearchMission.pending_promotion_symbol`` set), the
user explicitly asked to continue that SAME candidate's robustness
validation (OOS / walk-forward / transaction-cost stress / regime /
cross-symbol / parameter sensitivity / Monte Carlo) - and Gaon re-ran a
fresh, mission-unaware multi-symbol BREADTH cycle instead of ever reaching
``_try_candidate_robustness_cycle``.

Root cause (see the comment above ``robustness_continuation_precedence``
in ``gaon.runtime.llm_conversation._try_conversational_mvp``): the long,
detailed real user message happened to trip TWO unrelated false-positive
classifiers at once - it contains the literal substring "cross-symbol"
(matching the deterministic ``multi_symbol_research`` tool-routing
heuristic) and the bare substring "상태" inside "유지한 상태에서" ("while
KEEPING it [unchanged]", with no status-query meaning at all - matching
``ConversationalMVPIntent.STATUS_QUERY``, which is in the mission-hook's
exclusion list). Either collision alone was enough to make the mission-
routing-precedence hook skip entirely, falling through to a mission/
candidate-unaware code path.

This test proves, through the REAL production stack
(TelegramConversationAgent -> LLMConversationBrain -> default_tool_registry
-> multi_symbol_research / telegram_autonomous_learning_payload), mocking
only the true external boundaries - same convention as
``tests/integration/test_persistent_strategy_candidate_continuation.py``:

- turn 4 does not end in a plain breadth-only multi_symbol_research result
- the SAME candidate ID and strategy fingerprint survive across the
  transition
- the robustness/deep-validation path is actually invoked
  (autonomous_learning_research), not a repeated multi_symbol_research
  call and not the stale-context legacy single-symbol path
- execution stays bounded
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import MissionUniverseScope, candidate_records
from gaon.knowledge.strategy_candidate import StrategyCandidateStatus
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent

from test_strategy_centric_autonomous_research import (
    _DeterministicKRUniverseProvider,
    _MISSION_TEST_UNIVERSE,
    _RecordingTelegramClient,
    _baseline,
    _config,
    _update,
)

_TURN4_REAL_PRODUCTION_MESSAGE = (
    "후보 A를 현재 Research Mission의 전략 후보로 유지한 상태에서 다음 검증 단계로 진행해주세요.\n\n"
    "후보 A의 전략 규칙과 fingerprint는 변경하지 말고,\n"
    "특정 종목에 맞춰 파라미터를 조정하지 마세요.\n\n"
    "Out-of-Sample,\n"
    "Walk-Forward,\n"
    "거래비용 및 슬리피지 스트레스,\n"
    "시장 국면별 검증,\n"
    "cross-symbol,\n"
    "파라미터 민감도,\n"
    "가능하면 Monte Carlo 검증까지 진행해주세요."
)

_ROBUSTNESS_CONTINUATION_PHRASES: tuple[str, ...] = (
    "OOS 검증해주세요",
    "walk-forward 검증해주세요",
    "비용 스트레스 검증해주세요",
    "시장 국면별 검증해주세요",
    "강건성 검증 계속해주세요",
    "다음 검증 단계로 진행해주세요",
)


class CandidateBreadthToRobustnessTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    def _send(self, update_id: int, text: str) -> str:
        baseline = _baseline(trades=45, run_id=f"turn{update_id}")
        received_at = f"2026-08-17T00:{update_id:02d}:00Z"
        with patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline), patch(
            "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
            return_value={"state": "content_unavailable"},
        ), patch(
            "gaon.research.multi_symbol.build_market_data_provider_from_env",
            return_value=_DeterministicKRUniverseProvider(),
        ):
            result = process_update(
                parse_update_result(_update(update_id, update_id, text), received_at=received_at),
                self.runtime,
                self.client,
            )
        self.assertEqual(result.status, "sent", f"turn {update_id} failed: {result}")
        return self.client.sent[-1][1]

    def _mission(self):
        return self.agent._brain._mission_for("telegram:100")

    def _audits(self, tool_name: str):
        return self.store.tool_audit.list(tool_name=tool_name)

    def _establish_mission_with_ready_candidate(self):
        self._send(
            1,
            "대한민국 장에 맞는 단타 매매 전략을 연구해주세요. "
            "현재 등록되어있는 전략보다 수익면에서 안전성 면에서 뛰어나야합니다.",
        )
        self._send(2, "삼성전자말고 국내 주식 전체를 대상으로 연구해주세요")
        self._send(3, "증거가 충분할 때까지 다양한 방식으로 전략을 연구해주세요")
        mission = self._mission()
        self.assertEqual(mission.universe_scope, MissionUniverseScope.MARKET_WIDE)
        self.assertIsNotNone(mission.pending_promotion_symbol, "breadth cycle must have reached sufficient evidence")
        candidate = candidate_records(mission)[0]
        self.assertEqual(candidate.status, StrategyCandidateStatus.VALIDATING)
        return mission, candidate

    def test_real_production_message_transitions_to_robustness_not_repeated_breadth(self) -> None:
        mission_before, candidate_before = self._establish_mission_with_ready_candidate()
        breadth_calls_before = len(self._audits("multi_symbol_research"))

        turn4 = self._send(4, _TURN4_REAL_PRODUCTION_MESSAGE)

        # Turn 4 must NOT simply repeat the breadth-only multi_symbol_research
        # report - no new multi_symbol_research call, and the response is
        # NOT the plain "[다중종목 실제 연구]" breadth report shape.
        self.assertEqual(len(self._audits("multi_symbol_research")), breadth_calls_before)
        self.assertNotIn("[다중종목 실제 연구]", turn4)

        # The robustness/deep-validation path was actually invoked.
        self.assertGreaterEqual(len(self._audits("autonomous_learning_research")), 1)
        self.assertEqual(len(self._audits("autonomous_research_cycle")), 0)

        # The SAME candidate identity (ID and fingerprint) survived.
        mission_after = self._mission()
        candidate_after = candidate_records(mission_after)[0]
        self.assertEqual(candidate_after.candidate_id, candidate_before.candidate_id)
        self.assertEqual(candidate_after.strategy_fingerprint, candidate_before.strategy_fingerprint)
        self.assertEqual(candidate_after.status, StrategyCandidateStatus.ROBUSTNESS)
        self.assertEqual(mission_after.universe_scope, MissionUniverseScope.MARKET_WIDE)

        # Never fell back to a stale 005930 identity.
        for symbol, _exchange in _MISSION_TEST_UNIVERSE:
            self.assertNotIn(f"{symbol} 전략을 다시 연구했습니다", turn4)

    def test_each_robustness_continuation_phrase_reaches_the_robustness_path(self) -> None:
        for phrase in _ROBUSTNESS_CONTINUATION_PHRASES:
            with self.subTest(phrase=phrase):
                self.setUp()
                self._establish_mission_with_ready_candidate()
                before = len(self._audits("multi_symbol_research"))
                self._send(4, phrase)
                self.assertEqual(len(self._audits("multi_symbol_research")), before, phrase)
                self.assertGreaterEqual(len(self._audits("autonomous_learning_research")), 1, phrase)
                self.assertEqual(len(self._audits("autonomous_research_cycle")), 0, phrase)

    def test_candidate_fingerprint_continuity_breadth_equals_deep_validation(self) -> None:
        mission_before, candidate_before = self._establish_mission_with_ready_candidate()
        self._send(4, _TURN4_REAL_PRODUCTION_MESSAGE)
        audits = self._audits("autonomous_learning_research")
        self.assertGreaterEqual(len(audits), 1)
        request_text = audits[-1].request["arguments"]["request_text"]
        from gaon.research.krx_real_pipeline import UserStrategyParser

        symbol = audits[-1].request["arguments"]["symbol"]
        validated_fingerprint = UserStrategyParser().parse(request_text, symbol=symbol).strategy_family_fingerprint
        self.assertEqual(validated_fingerprint, candidate_before.strategy_fingerprint)

    def test_promotion_ready_only_increases_through_the_real_gate(self) -> None:
        mission_before, _candidate = self._establish_mission_with_ready_candidate()
        before_count = mission_before.current_promotion_ready_candidates
        self._send(4, _TURN4_REAL_PRODUCTION_MESSAGE)
        mission_after = self._mission()
        # A single non-terminal robustness cycle must never invent a
        # promotion - the count only moves through record_promotion_candidate,
        # which only ever fires on a real request_human_promotion_review
        # decision from the existing Research Director.
        self.assertGreaterEqual(mission_after.current_promotion_ready_candidates, before_count)
        if mission_after.current_promotion_ready_candidates > before_count:
            self.assertEqual(candidate_records(mission_after)[0].status, StrategyCandidateStatus.PROMOTION_READY)

    def test_restart_reload_preserves_robustness_progress(self) -> None:
        self._establish_mission_with_ready_candidate()
        self._send(4, _TURN4_REAL_PRODUCTION_MESSAGE)
        candidate_before = candidate_records(self._mission())[0]

        restarted_agent = TelegramConversationAgent(_config(), self.store._connection)
        reloaded_mission = restarted_agent._brain._mission_for("telegram:100")
        reloaded_candidate = candidate_records(reloaded_mission)[0]
        self.assertEqual(reloaded_candidate.candidate_id, candidate_before.candidate_id)
        self.assertEqual(reloaded_candidate.strategy_fingerprint, candidate_before.strategy_fingerprint)
        self.assertEqual(reloaded_candidate.status, candidate_before.status)
        self.assertEqual(dict(reloaded_candidate.validation_stage_status), dict(candidate_before.validation_stage_status))

    def test_bounded_execution_no_infinite_robustness_loop_in_one_turn(self) -> None:
        self._establish_mission_with_ready_candidate()
        before_multi = len(self._audits("multi_symbol_research"))
        before_single = len(self._audits("autonomous_learning_research"))
        self._send(4, "3개 나올 때까지 " + _TURN4_REAL_PRODUCTION_MESSAGE)
        after_multi = len(self._audits("multi_symbol_research"))
        after_single = len(self._audits("autonomous_learning_research"))
        self.assertLessEqual((after_multi - before_multi) + (after_single - before_single), 1)

    def test_status_query_shows_real_persisted_state_not_fabricated(self) -> None:
        self._establish_mission_with_ready_candidate()
        self._send(4, _TURN4_REAL_PRODUCTION_MESSAGE)
        status_text = self._send(5, "지금 뭐 연구하고 있어?")
        self.assertIn("[Research Mission]", status_text)
        self.assertIn("strategy fingerprint:", status_text)
        self.assertIn("promotion-ready candidates:", status_text)
        # Stages never actually run must be shown honestly, never as a
        # fabricated pass/fail.
        self.assertTrue(
            any(marker in status_text for marker in ("not_run", "unavailable", "insufficient_evidence"))
        )
        self.assertNotIn("PASS", status_text)


if __name__ == "__main__":
    unittest.main()
