from __future__ import annotations

import unittest

from gaon.research.live_trading_intelligence import LiveFeedback
from gaon.research.research_director import (
    ResearchDirector,
    ResearchDirectorAction,
    ResearchDirectorState,
    live_execution_fields_from_feedback,
    production_research_director_release_check,
)


def _state(**overrides: object) -> ResearchDirectorState:
    base = dict(
        evidence_strength="strong",
        hypothesis_conflict="supported",
        symbol_coverage_sufficient=True,
        period_sufficient=True,
        oos_completed=True,
        walk_forward_completed=True,
        regime_completed=True,
        cost_stress_completed=True,
        monte_carlo_completed=True,
        live_execution_available=False,
        live_execution_inspected=False,
        live_execution_failed_orders=0,
        candidate_rejected=False,
        steps_used=0,
        max_steps=10,
    )
    base.update(overrides)
    return ResearchDirectorState(**base)  # type: ignore[arg-type]


class ResearchDirectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.director = ResearchDirector()

    def test_rejects_unknown_evidence_strength(self) -> None:
        with self.assertRaises(ValueError):
            _state(evidence_strength="fabricated")

    def test_rejects_unknown_conflict_status(self) -> None:
        with self.assertRaises(ValueError):
            _state(hypothesis_conflict="made_up")

    def test_budget_exhaustion_wins_over_everything_else(self) -> None:
        decision = self.director.decide(_state(steps_used=10, evidence_strength="insufficient", candidate_rejected=True))
        self.assertEqual(decision.action, ResearchDirectorAction.HOLD)
        self.assertTrue(decision.terminal)
        self.assertEqual(decision.stop_reason, "research_budget_exhausted")

    def test_rejected_candidate_is_terminal(self) -> None:
        decision = self.director.decide(_state(candidate_rejected=True))
        self.assertEqual(decision.action, ResearchDirectorAction.REJECT_CANDIDATE)
        self.assertTrue(decision.terminal)

    def test_unresolved_conflict_triggers_counter_hypothesis(self) -> None:
        decision = self.director.decide(_state(hypothesis_conflict="unresolved_conflict"))
        self.assertEqual(decision.action, ResearchDirectorAction.TEST_COUNTER_HYPOTHESIS)
        self.assertIn("hypothesis_conflict", decision.evidence_refs)

    def test_weak_evidence_triggers_collection_before_validation_steps(self) -> None:
        decision = self.director.decide(_state(evidence_strength="insufficient", oos_completed=False))
        self.assertEqual(decision.action, ResearchDirectorAction.COLLECT_MORE_EVIDENCE)

    def test_validation_gap_order(self) -> None:
        cases = (
            ({"symbol_coverage_sufficient": False}, ResearchDirectorAction.EXPAND_SYMBOLS),
            ({"period_sufficient": False}, ResearchDirectorAction.EXPAND_PERIOD),
            ({"oos_completed": False}, ResearchDirectorAction.RUN_OOS),
            ({"walk_forward_completed": False}, ResearchDirectorAction.RUN_WALK_FORWARD),
            ({"regime_completed": False}, ResearchDirectorAction.TEST_REGIME),
            ({"cost_stress_completed": False}, ResearchDirectorAction.TEST_COSTS),
            ({"monte_carlo_completed": False}, ResearchDirectorAction.RUN_MONTE_CARLO),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                decision = self.director.decide(_state(**overrides))
                self.assertEqual(decision.action, expected)

    def test_available_uninspected_live_evidence_triggers_inspection(self) -> None:
        decision = self.director.decide(_state(live_execution_available=True, live_execution_inspected=False))
        self.assertEqual(decision.action, ResearchDirectorAction.INSPECT_LIVE_EXECUTION)

    def test_fully_validated_recommends_human_review_without_promoting(self) -> None:
        decision = self.director.decide(_state())
        self.assertEqual(decision.action, ResearchDirectorAction.REQUEST_HUMAN_PROMOTION_REVIEW)
        self.assertTrue(decision.terminal)
        payload = decision.to_json()
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["approval_bypassed"])

    def test_inspected_live_evidence_does_not_block_review(self) -> None:
        decision = self.director.decide(
            _state(live_execution_available=True, live_execution_inspected=True, live_execution_failed_orders=3)
        )
        self.assertEqual(decision.action, ResearchDirectorAction.REQUEST_HUMAN_PROMOTION_REVIEW)

    def test_every_decision_cites_evidence(self) -> None:
        for decision in (
            self.director.decide(_state(steps_used=10)),
            self.director.decide(_state(candidate_rejected=True)),
            self.director.decide(_state(hypothesis_conflict="unresolved_conflict")),
            self.director.decide(_state()),
        ):
            self.assertTrue(decision.evidence_refs)

    def test_live_execution_adapter_separates_failures_from_strategy_performance(self) -> None:
        feedback = LiveFeedback(
            market="KOSPI",
            completed_trade_count=5,
            win_rate=0.6,
            failed_order_count=2,
            unconfirmed_order_count=1,
            unmatched_sell_count=0,
            open_position_count=1,
            classifications=(),
            hypotheses=(),
        )
        fields = live_execution_fields_from_feedback(feedback.to_json())
        self.assertTrue(fields["live_execution_available"])
        self.assertEqual(fields["live_execution_failed_orders"], 3)
        # Strategy performance fields are intentionally not part of the
        # Director's execution-reliability signal.
        self.assertNotIn("completed_trade_count", fields)
        self.assertNotIn("win_rate", fields)
        decision = self.director.decide(_state(**fields, live_execution_inspected=False))
        self.assertEqual(decision.action, ResearchDirectorAction.INSPECT_LIVE_EXECUTION)

    def test_release_check_passes(self) -> None:
        payload = production_research_director_release_check()
        self.assertEqual(payload["safety"], "pass")
        self.assertFalse(payload["strategy_mutated"])
        self.assertFalse(payload["order_executed"])
        self.assertFalse(payload["champion_promoted"])


if __name__ == "__main__":
    unittest.main()
