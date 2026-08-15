from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_quant_partner import (
    ResearchBudget,
    _adaptive_validation_feedback_execution,
    _release_baseline_with_real_execution_inputs,
)


def _grade() -> dict[str, object]:
    return {
        "out_of_sample": {
            "status": "fail_underperformed_baseline",
            "executed": True,
            "lineage": "actual_backtest",
        },
        "walk_forward": {
            "status": "fail",
            "executed": True,
            "lineage": "actual_backtest",
        },
        "transaction_cost_stress": {
            "status": "cost_fragile",
            "executed": True,
            "lineage": "actual_backtest",
        },
    }


class IntraRunAdaptiveResearchContinuationTests(unittest.TestCase):
    def test_failed_candidates_continue_within_same_request(self) -> None:
        result = _adaptive_validation_feedback_execution(
            "continue adaptive research within this request",
            symbol="005930",
            baseline=_release_baseline_with_real_execution_inputs(),
            production_grade=_grade(),
            budget=ResearchBudget(),
        )

        self.assertEqual(6, result["experiment_budget"])
        self.assertGreater(result["actual_retests"], 3)
        self.assertGreaterEqual(result["research_rounds"], 2)
        self.assertGreaterEqual(result["continuation_rounds"], 1)

        executed = [
            row for row in result["iterations"]
            if row.get("actual_execution") is True
        ]
        semantics = [
            row["candidate_semantic_fingerprint"]
            for row in executed
        ]
        self.assertEqual(len(semantics), len(set(semantics)))

        attempts: dict[str, set[int]] = {}
        for row in executed:
            attempts.setdefault(
                str(row["observed_failure"]),
                set(),
            ).add(int(row["failure_attempt"]))
        self.assertTrue(
            any(max(values) >= 2 for values in attempts.values()),
            attempts,
        )
        self.assertTrue(
            all(row["strategy_mutated"] is False for row in result["iterations"])
        )
        self.assertTrue(
            all(row["order_executed"] is False for row in result["iterations"])
        )

    def test_max_experiments_caps_same_request_continuation(self) -> None:
        result = _adaptive_validation_feedback_execution(
            "bounded adaptive continuation",
            symbol="005930",
            baseline=_release_baseline_with_real_execution_inputs(),
            production_grade=_grade(),
            budget=ResearchBudget(max_experiments=4),
        )

        self.assertLessEqual(result["actual_retests"], 4)
        self.assertEqual(4, result["experiment_budget"])
        self.assertEqual(
            result["actual_retests"],
            result["experiments_executed"],
        )
        self.assertTrue(result["budget_exhausted"])
        self.assertEqual(
            "adaptive_experiment_budget_exhausted",
            result["adaptive_stop_reason"],
        )
        self.assertTrue(result["unresolved_failures"])

    def test_first_round_preserves_failure_family_coverage(self) -> None:
        result = _adaptive_validation_feedback_execution(
            "fair round robin adaptive continuation",
            symbol="005930",
            baseline=_release_baseline_with_real_execution_inputs(),
            production_grade=_grade(),
            budget=ResearchBudget(max_experiments=4),
        )
        first_round = [
            row for row in result["iterations"]
            if row.get("intra_run_round") == 1
        ]
        self.assertEqual(
            [
                "out_of_sample_fail",
                "walk_forward_fail",
                "cost_fragile",
            ],
            [row["observed_failure"] for row in first_round],
        )


if __name__ == "__main__":
    unittest.main()
