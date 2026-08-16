from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from gaon.knowledge.research_director_bridge import (
    decide_next_research_action,
    execute_research_director_action,
    live_execution_fields_from_real_adapter,
    research_director_state_from_learning_payload,
)
from gaon.research.research_director import ResearchDirectorAction


def _grade(**overrides: object) -> dict[str, object]:
    base = {
        "out_of_sample": {"executed": False},
        "walk_forward": {"executed": False},
        "regime_validation": {"executed": False},
        "transaction_cost_stress": {"executed": False},
        "monte_carlo": {"executed": False},
        "multi_symbol_validation": {"executed": False},
    }
    base.update(overrides)
    return base


def _payload(
    *,
    evidence_strength: str = "strong",
    conflict_status: str = "supporting",
    sample_status: str = "sufficient",
    grade: dict[str, object] | None = None,
    stop_reason: str | None = None,
) -> dict[str, object]:
    return {
        "autonomous_learning_v2": {
            "autonomous_quant_partner": {
                "production_grade_validation": grade or _grade(),
                "stop_reason": stop_reason,
            },
            "autonomous_quant_partner_stop_reason": stop_reason,
            "multi_source_research": {
                "evidence_bundle": {
                    "evidence_strength": evidence_strength,
                    "conflict_status": conflict_status,
                }
            },
            "validation_sample_diagnostics": {"sample_sufficiency_status": sample_status},
        }
    }


class ResearchDirectorStateExtractionTests(unittest.TestCase):
    def test_extracts_evidence_strength_and_conflict_from_real_field_names(self) -> None:
        state = research_director_state_from_learning_payload(
            _payload(evidence_strength="exploratory", conflict_status="mixed")
        )
        self.assertEqual(state.evidence_strength, "exploratory")
        self.assertEqual(state.hypothesis_conflict, "unresolved_conflict")

    def test_contradicting_evidence_is_also_an_unresolved_conflict(self) -> None:
        state = research_director_state_from_learning_payload(_payload(conflict_status="contradicting"))
        self.assertEqual(state.hypothesis_conflict, "unresolved_conflict")

    def test_insufficient_evidence_stance_is_not_evaluated_not_a_fabricated_conflict(self) -> None:
        state = research_director_state_from_learning_payload(_payload(conflict_status="insufficient"))
        self.assertEqual(state.hypothesis_conflict, "not_evaluated")

    def test_unknown_evidence_strength_falls_back_to_insufficient_not_fabricated(self) -> None:
        state = research_director_state_from_learning_payload(_payload(evidence_strength="made_up"))
        self.assertEqual(state.evidence_strength, "insufficient")

    def test_reads_validation_stage_completion_from_production_grade_validation(self) -> None:
        state = research_director_state_from_learning_payload(
            _payload(
                grade=_grade(
                    out_of_sample={"executed": True},
                    walk_forward={"executed": True},
                    regime_validation={"executed": True},
                    transaction_cost_stress={"executed": True},
                    monte_carlo={"executed": True},
                    multi_symbol_validation={"executed": True},
                )
            )
        )
        self.assertTrue(state.oos_completed)
        self.assertTrue(state.walk_forward_completed)
        self.assertTrue(state.regime_completed)
        self.assertTrue(state.cost_stress_completed)
        self.assertTrue(state.monte_carlo_completed)
        self.assertTrue(state.symbol_coverage_sufficient)

    def test_sample_sufficiency_status_drives_period_sufficient(self) -> None:
        state = research_director_state_from_learning_payload(_payload(sample_status="insufficient_trades"))
        self.assertFalse(state.period_sufficient)

    def test_underlying_engine_stop_reason_does_not_override_directors_own_step_budget(self) -> None:
        # autonomous_quant_partner's own stop_reason is a different, existing
        # concept from the Director's conversation-turn budget - it must not
        # be conflated into steps_used. Only the caller-supplied steps_used
        # (sourced from the real continuation counter) controls that.
        state = research_director_state_from_learning_payload(
            _payload(stop_reason="research_budget_exhausted"), steps_used=1, max_steps=8
        )
        self.assertEqual(state.steps_used, 1)
        self.assertNotEqual(state.steps_used, state.max_steps)

    def test_live_execution_fields_pass_through(self) -> None:
        state = research_director_state_from_learning_payload(
            _payload(),
            live_execution_fields={
                "live_execution_available": True,
                "live_execution_inspected": True,
                "live_execution_failed_orders": 3,
            },
        )
        self.assertTrue(state.live_execution_available)
        self.assertTrue(state.live_execution_inspected)
        self.assertEqual(state.live_execution_failed_orders, 3)

    def test_accepts_inner_learning_dict_directly(self) -> None:
        full = _payload()
        inner = full["autonomous_learning_v2"]
        state_from_full = research_director_state_from_learning_payload(full)
        state_from_inner = research_director_state_from_learning_payload(inner)
        self.assertEqual(state_from_full, state_from_inner)


class DecideNextResearchActionTests(unittest.TestCase):
    def test_weak_evidence_recommends_collecting_more(self) -> None:
        decision = decide_next_research_action(_payload(evidence_strength="insufficient"))
        self.assertEqual(decision.action, ResearchDirectorAction.COLLECT_MORE_EVIDENCE)

    def test_fully_validated_strong_evidence_recommends_human_review(self) -> None:
        decision = decide_next_research_action(
            _payload(
                grade=_grade(
                    out_of_sample={"executed": True},
                    walk_forward={"executed": True},
                    regime_validation={"executed": True},
                    transaction_cost_stress={"executed": True},
                    monte_carlo={"executed": True},
                    multi_symbol_validation={"executed": True},
                )
            )
        )
        self.assertEqual(decision.action, ResearchDirectorAction.REQUEST_HUMAN_PROMOTION_REVIEW)
        payload = decision.to_json()
        self.assertFalse(payload["champion_promoted"])
        self.assertFalse(payload["approval_bypassed"])


class LiveExecutionAdapterTests(unittest.TestCase):
    def test_unavailable_adapter_reports_honest_not_available(self) -> None:
        with patch("gaon.research.live_trading_intelligence.production_feedback", return_value=None):
            fields = live_execution_fields_from_real_adapter()
        self.assertFalse(fields["live_execution_available"])
        self.assertEqual(fields["live_execution_failed_orders"], 0)


class ExecuteResearchDirectorActionTests(unittest.TestCase):
    def _connection(self) -> sqlite3.Connection:
        from gaon.runtime.migrations import migrate

        connection = sqlite3.connect(":memory:")
        self.addCleanup(connection.close)
        migrate(connection)
        return connection

    def test_terminal_actions_never_dispatch_further_research(self) -> None:
        from gaon.research.research_director import ResearchDirectorDecision

        for action in (
            ResearchDirectorAction.HOLD,
            ResearchDirectorAction.REJECT_CANDIDATE,
            ResearchDirectorAction.REQUEST_HUMAN_PROMOTION_REVIEW,
        ):
            with self.subTest(action=action):
                decision = ResearchDirectorDecision(action, "test", ("evidence_strength",), True, "test_stop")
                result = execute_research_director_action(
                    decision, connection=self._connection(), request_text="Samsung", symbol="005930"
                )
                self.assertIsNone(result["dispatched_tool"])
                self.assertTrue(result["terminal"])
                self.assertIsNone(result["result"])
                self.assertFalse(result["strategy_mutated"])
                self.assertFalse(result["order_executed"])
                self.assertFalse(result["champion_promoted"])

    def test_expand_symbols_dispatches_multi_symbol_research(self) -> None:
        from gaon.research.research_director import ResearchDirectorDecision

        decision = ResearchDirectorDecision(
            ResearchDirectorAction.EXPAND_SYMBOLS, "generalize", ("symbol_coverage_sufficient",), False, None
        )
        sentinel = {"tool": "multi_symbol_research", "symbols": ("005930", "000660")}
        with patch("gaon.research.multi_symbol.multi_symbol_research_payload", return_value=sentinel) as mocked:
            result = execute_research_director_action(
                decision,
                connection=self._connection(),
                request_text="Samsung generalize",
                symbol="005930",
                additional_symbols=("000660",),
            )
        mocked.assert_called_once()
        self.assertEqual(result["dispatched_tool"], "multi_symbol_research")
        self.assertEqual(result["result"], sentinel)
        self.assertFalse(result["terminal"])

    def test_inspect_live_execution_dispatches_read_only_live_adapter(self) -> None:
        from gaon.research.research_director import ResearchDirectorDecision

        decision = ResearchDirectorDecision(
            ResearchDirectorAction.INSPECT_LIVE_EXECUTION,
            "check live evidence",
            ("live_execution_available", "live_execution_inspected"),
            False,
            None,
        )
        with patch("gaon.research.live_trading_intelligence.production_feedback", return_value=None) as mocked:
            result = execute_research_director_action(
                decision, connection=self._connection(), request_text="Samsung", symbol="005930"
            )
        mocked.assert_called_once()
        self.assertEqual(result["dispatched_tool"], "live_trading_intelligence")
        self.assertIsNone(result["result"])

    def test_continuation_action_reinvokes_autonomous_learning_research_with_incremented_steps(self) -> None:
        from gaon.research.research_director import ResearchDirectorDecision

        decision = ResearchDirectorDecision(
            ResearchDirectorAction.COLLECT_MORE_EVIDENCE, "need more evidence", ("evidence_strength",), False, None
        )
        sentinel = {"tool": "autonomous_learning_research"}
        with patch(
            "gaon.knowledge.telegram_autonomous_learning.telegram_autonomous_learning_payload",
            return_value=sentinel,
        ) as mocked:
            result = execute_research_director_action(
                decision,
                connection=self._connection(),
                request_text="Samsung continue",
                symbol="005930",
                steps_used=2,
                max_steps=8,
            )
        mocked.assert_called_once()
        _, kwargs = mocked.call_args
        self.assertEqual(kwargs["steps_used"], 3)
        self.assertEqual(kwargs["max_steps"], 8)
        self.assertEqual(kwargs["mode"], "research")
        self.assertEqual(result["dispatched_tool"], "autonomous_learning_research")
        self.assertEqual(result["result"], sentinel)


if __name__ == "__main__":
    unittest.main()
