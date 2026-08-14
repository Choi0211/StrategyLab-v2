from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_quant_partner import (
    _adaptive_research_dimensions,
    _adaptive_validation_metrics_snapshot,
)
from gaon.runtime.research_grounding import _adaptive_feedback_detail_lines


class AdaptiveResearchMetricsLineageTests(unittest.TestCase):
    def test_oos_snapshot_preserves_actual_metrics(self) -> None:
        result = _adaptive_validation_metrics_snapshot(
            "out_of_sample_fail",
            {
                "metrics_lineage": "actual_backtest",
                "candidate_test_metrics": {
                    "trade_count": 7,
                    "total_return": 0.12,
                    "mdd": 0.08,
                    "cagr": 0.09,
                    "profit_factor": 1.4,
                    "sharpe": 0.7,
                },
                "comparison": {"comparison_status": "pass"},
            },
        )
        self.assertEqual("actual_backtest", result["lineage"])
        self.assertEqual(7, result["trade_count"])
        self.assertEqual(0.12, result["total_return"])

    def test_walk_forward_snapshot_aggregates_candidate_trades(self) -> None:
        result = _adaptive_validation_metrics_snapshot(
            "walk_forward_fail",
            {
                "metrics_lineage": "actual_backtest",
                "fold_count": 2,
                "folds_passed": 1,
                "folds_failed": 1,
                "folds": [
                    {
                        "candidate_trades": 3,
                        "candidate_return": 0.1,
                        "candidate_mdd": 0.05,
                    },
                    {
                        "candidate_trades": 4,
                        "candidate_return": -0.02,
                        "candidate_mdd": 0.08,
                    },
                ],
            },
        )
        self.assertEqual(7, result["candidate_trade_count"])
        self.assertEqual([0.1, -0.02], result["candidate_returns"])

    def test_failure_types_have_distinct_research_dimensions(self) -> None:
        self.assertIn(
            "generalization",
            _adaptive_research_dimensions("out_of_sample_fail", []),
        )
        self.assertIn(
            "rule_complexity",
            _adaptive_research_dimensions("walk_forward_fail", []),
        )
        self.assertIn(
            "turnover",
            _adaptive_research_dimensions("cost_fragile", []),
        )

    def test_renderer_reads_nested_actual_primary_metrics(self) -> None:
        rendered = "\n".join(
            _adaptive_feedback_detail_lines(
                {
                    "status": "executed",
                    "executed": True,
                    "actual_retests": 1,
                    "iterations": [
                        {
                            "iteration": 1,
                            "observed_failure": "out_of_sample_fail",
                            "candidate_id": "candidate:test",
                            "candidate_fingerprint": "abc",
                            "changed_rules": ["breakout_lookback:30->40"],
                            "research_dimensions": ["generalization"],
                            "actual_execution": True,
                            "primary_backtest": {
                                "metrics": {
                                    "trade_count": 9,
                                    "total_return": 0.2,
                                    "mdd": 0.1,
                                }
                            },
                            "validation_metrics": {"trade_count": 3},
                            "validation_result": "pass",
                        }
                    ],
                }
            )
        )
        self.assertIn("primary_trade_count=9", rendered)
        self.assertIn("primary_total_return=0.2", rendered)
        self.assertIn("research_dimensions=generalization", rendered)


if __name__ == "__main__":
    unittest.main()
