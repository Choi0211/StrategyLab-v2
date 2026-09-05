"""Patch 8.6 - candidate-level multi-symbol robustness aggregation acceptance test.

Real production defect this proves fixed: real VPS Telegram Production
Acceptance testing (after Patch 8.5 fixed the breadth->robustness
transition itself) showed that once a robustness cycle actually ran, its
response reported only a bare evaluation SYMBOL and generic adequacy
diagnostics - missing the active StrategyCandidate ID, strategy
fingerprint, per-stage OOS/walk-forward/cost-stress/regime status, and the
whole Research Mission footer entirely. At the code level, the root cause
(confirmed by direct reproduction, not guessed - see the Patch 8.6
completion report) was two-fold:

1. ``_try_candidate_robustness_cycle`` only ever deepened ONE evaluation
   symbol via the existing cross-turn ``steps_used`` budget - there was no
   mechanism at all to rotate to a DIFFERENT, not-yet-tried symbol from the
   candidate's own breadth-validated evidence pool, so a market-wide
   mission's robustness stage could never actually accumulate cross-symbol
   evidence under one strategy fingerprint.
2. A HOLD (or any other non-promoting, non-rejecting terminal Research
   Director decision, e.g. research_budget_exhausted) unconditionally
   cleared ``mission.pending_promotion_symbol`` while leaving the candidate
   "active" - the candidate stayed active but the NEXT turn silently lost
   ``robustness_continuation_precedence`` eligibility (it requires
   ``pending_promotion_symbol`` to be set), falling back to a fresh breadth
   cycle or, on a classifier collision, the legacy mission-unaware
   conversational path - reproducing the exact reported symptom.

This test proves, through the REAL production stack
(TelegramConversationAgent -> LLMConversationBrain -> default_tool_registry
-> multi_symbol_research / autonomous_learning_research), mocking only the
true external boundaries - same convention as
``tests/integration/test_candidate_breadth_to_robustness_transition.py``:

- the SAME candidate ID and strategy fingerprint survive breadth ->
  robustness -> a HOLD-triggered evidence-symbol rotation -> a further
  continuation
- the symbol is always reported as an EVIDENCE SAMPLE, never as the
  strategy's own identity
- per-stage validation status accumulates across cycles instead of being
  reset
- promotion-ready is decided only through the real, unchanged Director
  gate - never from one symbol's cycle alone
- a read-only status query performs zero new research tool calls
- execution stays bounded (exactly one tool call per continuation turn)
- restart/reload preserves all of the above

The Research Director's own terminal decision is forced to HOLD for
specific turns (via
``gaon.knowledge.telegram_autonomous_learning.decide_next_research_action``
- the same real bridge function production uses, never a second decision
path) purely to make the HOLD-triggered rotation deterministically
reachable without needing the real Director to organically reach HOLD on
this thin fixture (which - as
``production_candidate_breadth_to_robustness_transition_release_check``
already documents - may instead legitimately reject on the very first
cycle, a data-dependent, non-fabricated outcome this test does not need to
re-litigate).
"""

from __future__ import annotations

import unittest
from contextlib import ExitStack
from unittest.mock import patch

from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import parse_update_result
from gaon.knowledge.research_mission import (
    DEFAULT_KR_EXCHANGES,
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
    candidate_records,
    record_focus_symbol,
)
from gaon.knowledge.strategy_candidate import StrategyCandidateStatus
from gaon.knowledge.strategy_candidate import new_candidate, record_breadth_progress, record_robustness_progress
from gaon.research.research_director import ResearchDirectorAction, ResearchDirectorDecision
from gaon.runtime.llm_conversation import LLMConversationRequest
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

_TURN4_CONTINUE_ROBUSTNESS = (
    "후보 A를 현재 전략 후보로 유지하고 다음 강건성 검증 단계로 진행해주세요.\n"
    "동일한 strategy fingerprint를 유지한 채 OOS, walk-forward,\n"
    "거래비용 및 슬리피지 스트레스, 시장 국면별 검증을 계속해주세요.\n"
    "특정 종목에 맞춰 전략을 변경하지 마세요."
)

_HOLD_DECISION = ResearchDirectorDecision(ResearchDirectorAction.HOLD, "test-forced-hold", (), True, "test_forced_hold")

_RESEARCH_TOOL_NAMES = ("multi_symbol_research", "autonomous_learning_research", "autonomous_research_cycle")


class CandidateMultiSymbolRobustnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = RuntimeStateStore(":memory:")
        self.addCleanup(self.store.close)
        self.agent = TelegramConversationAgent(_config(), self.store._connection)
        self.runtime = TelegramRuntime(self.agent, allowed_chat_ids=("100",))
        self.client = _RecordingTelegramClient()

    def _send(self, update_id: int, text: str, *, force_hold: bool = False) -> str:
        baseline = _baseline(trades=45, run_id=f"turn{update_id}")
        received_at = f"2026-08-17T00:{update_id:02d}:00Z"
        with ExitStack() as stack:
            stack.enter_context(patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline))
            stack.enter_context(patch("gaon.knowledge.telegram_autonomous_learning._run_production_external_research", return_value={"state": "content_unavailable"}))
            stack.enter_context(patch("gaon.research.multi_symbol.build_market_data_provider_from_env", return_value=_DeterministicKRUniverseProvider()))
            if force_hold:
                stack.enter_context(patch("gaon.knowledge.telegram_autonomous_learning.decide_next_research_action", return_value=_HOLD_DECISION))
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

    def _research_tool_call_count(self) -> int:
        return sum(len(self._audits(name)) for name in _RESEARCH_TOOL_NAMES)

    def _seed_regime_blocked_candidate(self) -> None:
        now = "2026-08-21T00:00:00Z"
        candidate = new_candidate("breakout_volume_confirmed", sequence=3, now=now)
        candidate = record_breadth_progress(
            candidate,
            attempted=5,
            valid=5,
            trade_count=81,
            evidence_symbols=("286940", "005930", "000660", "005380", "035420"),
            excluded_symbols=(),
            provider_blocked=False,
            now=now,
        )
        candidate = record_robustness_progress(
            candidate,
            director_action="collect_more_evidence",
            terminal=False,
            validation_stage_status={
                "out_of_sample": "pass",
                "walk_forward": "partial",
                "regime_validation": "partial",
                "transaction_cost_stress": "cost_stable",
                "parameter_sensitivity": "stable",
                "multi_symbol_validation": "multi_symbol_partial",
                "monte_carlo": "not_run_insufficient_primary_sample",
            },
            symbol="286940",
            reference="action=CONTINUE_ROBUSTNESS|symbol=286940|stage=none|status=partial",
            now=now,
        )
        mission = ResearchMission(
            mission_id="research-mission:test-action-handoff",
            market="KR",
            universe_scope=MissionUniverseScope.MARKET_WIDE,
            symbols=(),
            exchanges=DEFAULT_KR_EXCHANGES,
            strategy_family="short_term_daytrade",
            improve_return=True,
            improve_safety=True,
            baseline_comparison="registered_strategy",
            target_promotion_ready_candidates=3,
            current_promotion_ready_candidates=0,
            promotion_ready_candidates=(),
            explored_symbols=(),
            status=MissionStatus.ACTIVE,
            blocked_reason=None,
            cycles_completed=1,
            created_at=now,
            updated_at=now,
            originating_request="release-check",
            candidates=(candidate.to_json(),),
            active_candidate_id=candidate.candidate_id,
        )
        mission = record_focus_symbol(mission, symbol="286940", now=now)
        seed = LLMConversationRequest("telegram:100", "telegram:100", "telegram", "seed", now, "seed:mission")
        self.agent._brain._remember_mission(seed, mission)

    def _action_payload(self, *, planned_action: str | None, planned_action_reason: str | None, symbol: str, resolve_planned_action: bool = True) -> dict[str, object]:
        status_by_action = {
            "RUN_REGIME": {"regime_validation": {"status": "pass", "executed": True}},
            "RUN_WALK_FORWARD": {"walk_forward": {"status": "pass", "executed": True}},
        }
        grade = {
            "multi_symbol_validation": {"status": "multi_symbol_partial", "executed": True},
            "out_of_sample": {"status": "pass", "executed": True},
            "walk_forward": {"status": "partial", "executed": True},
            "regime_validation": {"status": "partial", "executed": True},
            "transaction_cost_stress": {"status": "cost_stable", "executed": True},
            "parameter_sensitivity": {"status": "stable", "executed": True},
            "monte_carlo": {"status": "not_run_insufficient_primary_sample", "executed": False},
        }
        if resolve_planned_action:
            grade.update(status_by_action.get(str(planned_action), {}))
        return {
            "schema_version": 2,
            "tool": "autonomous_learning_research",
            "mode": "continue",
            "symbol": symbol,
            "request_text": "release-check",
            "autonomous_learning_v2": {
                "research_director_decision": {"action": "hold", "reason": "bounded continuation", "terminal": False},
                "research_director_steps_used": 1,
                "planned_action_execution": {
                    "planned_action": planned_action,
                    "planned_action_reason": planned_action_reason,
                    "dispatched": bool(planned_action),
                },
                "autonomous_quant_partner": {"production_grade_validation": grade},
                "promotion_candidate_context": {"candidate_id": "candidate:test", "candidate_fingerprint": "fp:test"},
            },
            "planned_action_execution": {
                "planned_action": planned_action,
                "planned_action_reason": planned_action_reason,
                "dispatched": bool(planned_action),
            },
            "strategy_mutated": False,
            "order_executed": False,
            "automatic_champion_promotion": False,
            "broker_order_called": False,
            "kis_order_called": False,
            "safety": "pass",
        }

    def _new_agent(self) -> TelegramConversationAgent:
        return TelegramConversationAgent(_config(), self.store._connection)

    def test_planned_run_regime_is_consumed_by_next_continuation(self) -> None:
        self._send(1, "안녕하세요 가온")
        self._seed_regime_blocked_candidate()

        def fake_learning(_connection, request_text, *, symbol="005930", mode="research", storage_root=None, steps_used=0, max_steps=8, planned_action=None, planned_action_reason=None, candidate_spec=None):
            return self._action_payload(planned_action=planned_action, planned_action_reason=planned_action_reason, symbol=symbol)

        with patch("gaon.runtime.llm_tools.telegram_autonomous_learning_payload", side_effect=fake_learning):
            turn2 = self._send(2, "연구를 계속해주세요")
            audits = self._audits("autonomous_learning_research")
            self.assertEqual(audits[-1].request["arguments"].get("planned_action"), "RUN_REGIME")
            self.assertIn("action_executed=RUN_REGIME", turn2)
            self.assertIn("action_progress=true", turn2)

            turn3 = self._send(3, "연구를 계속해주세요")
            audits = self._audits("autonomous_learning_research")
            self.assertEqual(audits[-1].request["arguments"].get("planned_action"), "RUN_WALK_FORWARD")
            self.assertNotIn("action_executed=RUN_REGIME", turn3)

    def test_planned_action_recomputes_across_persistence_boundary_when_stage_remains_partial(self) -> None:
        self._send(1, "안녕하세요 가온")
        self._seed_regime_blocked_candidate()
        self.agent = self._new_agent()
        reloaded_before = self.agent._brain._mission_for("telegram:100")
        self.assertIsNotNone(reloaded_before)
        before_candidate = candidate_records(reloaded_before)[0]
        self.assertEqual(before_candidate.validation_stage_status.get("regime_validation"), "partial")

        def fake_learning(_connection, request_text, *, symbol="005930", mode="research", storage_root=None, steps_used=0, max_steps=8, planned_action=None, planned_action_reason=None, candidate_spec=None):
            return self._action_payload(
                planned_action=planned_action,
                planned_action_reason=planned_action_reason,
                symbol=symbol,
                resolve_planned_action=False,
            )

        with patch("gaon.runtime.llm_tools.telegram_autonomous_learning_payload", side_effect=fake_learning):
            turn2 = self._send(2, "연구를 계속해주세요")
            audits = self._audits("autonomous_learning_research")
            self.assertEqual(audits[-1].request["arguments"].get("planned_action"), "RUN_REGIME")
            self.assertIn("action_executed=RUN_REGIME", turn2)
            self.assertIn("action_progress=false", turn2)
            self.assertIn("next_action=RUN_WALK_FORWARD", turn2)

            self.agent = self._new_agent()
            turn3 = self._send(3, "연구를 계속해주세요")
            audits = self._audits("autonomous_learning_research")
            self.assertEqual(audits[-1].request["arguments"].get("planned_action"), "RUN_WALK_FORWARD")
            self.assertIn("action_executed=RUN_WALK_FORWARD", turn3)
            self.assertNotEqual(turn2, turn3)


    def _establish_ready_candidate(self):
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
        return mission, candidate

    # -----------------------------------------------------------------
    # Spec item 8 - the mandatory 5-turn production E2E regression.
    # -----------------------------------------------------------------
    def test_five_turn_market_wide_mission_reaches_and_continues_robustness(self) -> None:
        mission1, candidate1 = self._establish_ready_candidate()
        symbol_turn4 = mission1.pending_promotion_symbol

        turn4 = self._send(4, _TURN4_CONTINUE_ROBUSTNESS, force_hold=True)
        self.assertIn(f"[전략 후보 {candidate1.candidate_id}]", turn4)
        self.assertIn("역할=evidence sample", turn4)
        self.assertIn("[강건성 상태]", turn4)
        self.assertIn("[Research Mission]", turn4)
        self.assertNotIn("전략을 다시 연구했습니다", turn4)
        for symbol, _exchange in _MISSION_TEST_UNIVERSE:
            self.assertNotIn(f"{symbol} 전략을", turn4)

        mission4 = self._mission()
        candidate4 = candidate_records(mission4)[0]
        self.assertEqual(candidate4.candidate_id, candidate1.candidate_id)
        self.assertEqual(candidate4.strategy_fingerprint, candidate1.strategy_fingerprint)
        self.assertTrue(candidate4.validation_stage_status, "real per-stage status must be recorded, never left empty")
        # A HOLD terminal decision must rotate to a DIFFERENT evidence
        # symbol from the candidate's own breadth-validated pool - never
        # silently clear robustness-continuation eligibility.
        self.assertIsNotNone(mission4.pending_promotion_symbol)
        self.assertNotEqual(mission4.pending_promotion_symbol, symbol_turn4)
        self.assertIn(mission4.pending_promotion_symbol, candidate4.evidence_symbols)

        turn5 = self._send(5, "계속 연구해주세요")
        mission5 = self._mission()
        candidate5 = candidate_records(mission5)[0]
        self.assertEqual(candidate5.candidate_id, candidate1.candidate_id)
        self.assertEqual(candidate5.strategy_fingerprint, candidate1.strategy_fingerprint)
        # Previously recorded stage status survives the next cycle.
        self.assertTrue(set(candidate4.validation_stage_status).issubset(set(candidate5.validation_stage_status)))
        # Candidate-level cumulative evidence never regresses.
        self.assertGreaterEqual(candidate5.valid_symbols, candidate1.valid_symbols)
        self.assertGreaterEqual(candidate5.trade_count, candidate1.trade_count)
        # Never falls back to a stale 005930 (or any other bare symbol) identity.
        for symbol, _exchange in _MISSION_TEST_UNIVERSE:
            self.assertNotIn(f"{symbol} 전략을 다시 연구했습니다", turn5)
        self.assertEqual(len(self._audits("autonomous_research_cycle")), 0)

        # Promotion-ready count only ever moves through the real gate.
        self.assertEqual(mission5.current_promotion_ready_candidates, mission1.current_promotion_ready_candidates)

        # Restart/reload preserves everything above.
        restarted = TelegramConversationAgent(_config(), self.store._connection)
        reloaded_mission = restarted._brain._mission_for("telegram:100")
        reloaded_candidate = candidate_records(reloaded_mission)[0]
        self.assertEqual(reloaded_candidate.candidate_id, candidate5.candidate_id)
        self.assertEqual(reloaded_candidate.strategy_fingerprint, candidate5.strategy_fingerprint)
        self.assertEqual(dict(reloaded_candidate.validation_stage_status), dict(candidate5.validation_stage_status))
        self.assertEqual(reloaded_mission.pending_promotion_symbol, mission5.pending_promotion_symbol)

    # -----------------------------------------------------------------
    # Spec item 9 - the 8 required direct probes.
    # -----------------------------------------------------------------
    def test_probe1_breadth_fingerprint_equals_robustness_evaluation_fingerprint(self) -> None:
        _mission, candidate = self._establish_ready_candidate()
        self._send(4, _TURN4_CONTINUE_ROBUSTNESS, force_hold=True)
        audits = self._audits("autonomous_learning_research")
        self.assertGreaterEqual(len(audits), 1)
        request_text = audits[-1].request["arguments"]["request_text"]
        symbol = audits[-1].request["arguments"]["symbol"]
        from gaon.research.krx_real_pipeline import UserStrategyParser

        validated_fingerprint = UserStrategyParser().parse(request_text, symbol=symbol).strategy_family_fingerprint
        self.assertEqual(validated_fingerprint, candidate.strategy_fingerprint)

    def test_probe2_hold_rotates_to_a_different_symbol_under_the_same_fingerprint(self) -> None:
        mission, candidate = self._establish_ready_candidate()
        symbol_a = mission.pending_promotion_symbol
        self._send(4, _TURN4_CONTINUE_ROBUSTNESS, force_hold=True)
        mission_after = self._mission()
        symbol_b = mission_after.pending_promotion_symbol
        self.assertIsNotNone(symbol_b)
        self.assertNotEqual(symbol_a, symbol_b)
        candidate_after = candidate_records(mission_after)[0]
        self.assertEqual(candidate_after.candidate_id, candidate.candidate_id)
        self.assertEqual(candidate_after.strategy_fingerprint, candidate.strategy_fingerprint)

    def test_probe3_validation_state_from_symbol_a_survives_the_symbol_b_cycle(self) -> None:
        self._establish_ready_candidate()
        self._send(4, _TURN4_CONTINUE_ROBUSTNESS, force_hold=True)
        candidate_after_a = candidate_records(self._mission())[0]
        self.assertTrue(candidate_after_a.validation_stage_status)

        self._send(5, "다음 검증 단계로 진행해주세요", force_hold=True)
        candidate_after_b = candidate_records(self._mission())[0]
        self.assertTrue(set(candidate_after_a.validation_stage_status).issubset(set(candidate_after_b.validation_stage_status)))
        for key, value in candidate_after_a.validation_stage_status.items():
            self.assertEqual(candidate_after_b.validation_stage_status.get(key), value)

    def test_probe4_a_single_cycle_never_promotes_without_the_real_director_gate(self) -> None:
        mission, _candidate = self._establish_ready_candidate()
        before = mission.current_promotion_ready_candidates
        self._send(4, _TURN4_CONTINUE_ROBUSTNESS, force_hold=True)
        mission_after = self._mission()
        self.assertEqual(mission_after.current_promotion_ready_candidates, before)
        self.assertNotEqual(candidate_records(mission_after)[0].status, StrategyCandidateStatus.PROMOTION_READY)

    def test_probe5_fingerprint_mismatch_evidence_is_never_merged(self) -> None:
        from gaon.knowledge.strategy_candidate import new_candidate, record_breadth_progress, record_robustness_progress

        now = "2026-08-17T00:00:00Z"
        candidate = new_candidate("breakout_standard", sequence=1, now=now)
        candidate = record_breadth_progress(
            candidate, attempted=10, valid=10, trade_count=10,
            evidence_symbols=("000660", "005380"), excluded_symbols=(), provider_blocked=False, now=now,
        )
        # This is exactly what gaon.runtime.llm_conversation._try_candidate_
        # robustness_cycle passes when _deep_validation_effective_fingerprint
        # does not match the candidate's own fingerprint for this cycle:
        # validation_stage_status and symbol are both withheld so the
        # unverifiable cycle is never counted as this candidate's evidence.
        mismatched = record_robustness_progress(
            candidate, director_action="collect_more_evidence", terminal=False, now=now,
            validation_stage_status=None, symbol=None,
        )
        self.assertEqual(mismatched.robustness_evidence_symbols, candidate.robustness_evidence_symbols)
        self.assertEqual(dict(mismatched.validation_stage_status), dict(candidate.validation_stage_status))
        self.assertEqual(mismatched.robustness_attempt_count, candidate.robustness_attempt_count)
        # The cycle still counts toward stagnation bookkeeping - a run of
        # unverifiable cycles must still be able to trigger rotation away
        # from this strategy, never loop forever.
        self.assertEqual(mismatched.cycles_completed, candidate.cycles_completed + 1)

    def test_probe6_restart_reload_preserves_rotated_evidence_state(self) -> None:
        self._establish_ready_candidate()
        self._send(4, _TURN4_CONTINUE_ROBUSTNESS, force_hold=True)
        mission_before = self._mission()
        candidate_before = candidate_records(mission_before)[0]

        restarted = TelegramConversationAgent(_config(), self.store._connection)
        reloaded_mission = restarted._brain._mission_for("telegram:100")
        reloaded_candidate = candidate_records(reloaded_mission)[0]
        self.assertEqual(reloaded_candidate.robustness_evidence_symbols, candidate_before.robustness_evidence_symbols)
        self.assertEqual(dict(reloaded_candidate.validation_stage_status), dict(candidate_before.validation_stage_status))
        self.assertEqual(reloaded_mission.pending_promotion_symbol, mission_before.pending_promotion_symbol)

    def test_probe7_status_query_performs_no_research_tool_call(self) -> None:
        self._establish_ready_candidate()
        self._send(4, _TURN4_CONTINUE_ROBUSTNESS, force_hold=True)
        for offset, phrase in enumerate(("지금 뭐 연구하고 있어?", "현재 연구 상태 보여줘", "후보 상태 알려줘", "지금 어디까지 검증됐어?")):
            with self.subTest(phrase=phrase):
                before = self._research_tool_call_count()
                status_text = self._send(6 + offset, phrase)
                after = self._research_tool_call_count()
                self.assertEqual(before, after, phrase)
                self.assertIn("[Research Mission]", status_text, phrase)

    def test_probe8_continue_research_is_exactly_one_bounded_tool_call(self) -> None:
        self._establish_ready_candidate()
        self._send(4, _TURN4_CONTINUE_ROBUSTNESS, force_hold=True)
        before = self._research_tool_call_count()
        self._send(5, "계속 연구해주세요")
        after = self._research_tool_call_count()
        self.assertEqual(after - before, 1)


if __name__ == "__main__":
    unittest.main()
