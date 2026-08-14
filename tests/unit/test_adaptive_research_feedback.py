from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_quant_partner import (
    ResearchBudget,
    _adaptive_validation_feedback_execution,
    _release_baseline_with_real_execution_inputs,
)


class AdaptiveResearchFeedbackTests(unittest.TestCase):
    def test_actual_validation_failures_create_real_retests(self) -> None:
        baseline = _release_baseline_with_real_execution_inputs()
        grade = {
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
        result = _adaptive_validation_feedback_execution(
            "Samsung adaptive validation retest",
            symbol="005930",
            baseline=baseline,
            production_grade=grade,
            budget=ResearchBudget(),
        )
        self.assertEqual(
            ["out_of_sample_fail", "walk_forward_fail", "cost_fragile"],
            result["failures_observed"],
        )
        rows = result["iterations"]
        self.assertEqual(3, len(rows))
        self.assertTrue(any(row["actual_execution"] for row in rows))
        executed = [row for row in rows if row["actual_execution"]]
        self.assertTrue(all(row["candidate_fingerprint"] for row in executed))
        self.assertTrue(all(row["experiment_id"] for row in executed))
        self.assertTrue(all(row["validation_result"] for row in executed))
        self.assertTrue(all(row["strategy_mutated"] is False for row in rows))
        self.assertTrue(all(row["order_executed"] is False for row in rows))

    def test_fixture_baseline_is_fail_closed(self) -> None:
        baseline = _release_baseline_with_real_execution_inputs()
        baseline["dataset"]["metadata"]["fixture_backed"] = True
        result = _adaptive_validation_feedback_execution(
            "fixture must be blocked",
            symbol="005930",
            baseline=baseline,
            production_grade={
                "out_of_sample": {"status": "fail_underperformed_baseline"}
            },
            budget=ResearchBudget(),
        )
        self.assertEqual("blocked_fixture_baseline", result["status"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["strategy_mutated"])
        self.assertFalse(result["order_executed"])


if __name__ == "__main__":
    unittest.main()
