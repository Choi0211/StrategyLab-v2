from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_quant_partner import (
    _adaptive_candidate_for_failure,
    _dynamic_hypothesis_candidate,
    _dynamic_hypothesis_driver,
    _hypothesis_branch_candidate,
    _select_unique_dynamic_hypothesis_candidate,
    _strategy_semantic_fingerprint,
)
from gaon.research.krx_real_pipeline import CanonicalStrategySpec, FieldProvenance, ProvenancedValue


def _v(value):
    return ProvenancedValue(value, FieldProvenance.DEFAULT)


def _baseline() -> CanonicalStrategySpec:
    return CanonicalStrategySpec(
        "canonical-strategy:dynamic-test",
        "005930",
        {"breakout_lookback": _v(30), "close_gt_ma20": _v(True)},
        {"protective_stop_pct": _v(-5.0)},
        {"volume_gte_ma20": _v(True)},
        "dynamic hypothesis test strategy",
        "2026-08-16T00:00:00Z",
    )


class DynamicHypothesisSpaceExpansionTests(unittest.TestCase):
    def test_oos_driver_uses_actual_return_and_drawdown_tradeoff(self) -> None:
        grade = {"out_of_sample": {"comparison": {"baseline_return": 1.90, "candidate_return": 1.70, "baseline_mdd": 0.16, "candidate_mdd": 0.08}}}
        driver = _dynamic_hypothesis_driver("out_of_sample_fail", grade, [])
        self.assertEqual("dynamic_return_recovery_after_drawdown_gain", driver["family"])
        self.assertLess(driver["return_delta"], 0)
        self.assertLess(driver["mdd_delta"], 0)
        self.assertEqual("actual_validation_metrics", driver["source"])

    def test_cost_driver_changes_family_from_observed_cost_elasticity(self) -> None:
        prior = [{"observed_failure": "cost_fragile", "actual_execution": True, "validation_metrics": {"scenarios": [{"name": "base", "net_return": 1.50}, {"name": "high", "net_return": 1.20}]}}]
        driver = _dynamic_hypothesis_driver("cost_fragile", {}, prior)
        self.assertEqual("dynamic_cost_elasticity_turnover_control", driver["family"])
        self.assertGreater(driver["degradation_ratio"], 0.03)

    def test_dynamic_candidate_is_distinct_from_static_space(self) -> None:
        base = _baseline()
        known = set()
        for variant in range(4):
            candidate, _ = _adaptive_candidate_for_failure(base, observed_failure="cost_fragile", iteration=1, variant=variant)
            known.add(_strategy_semantic_fingerprint(candidate))
        for branch in range(2):
            candidate, _, _ = _hypothesis_branch_candidate(base, observed_failure="cost_fragile", iteration=1, branch=branch)
            known.add(_strategy_semantic_fingerprint(candidate))
        driver = {"family": "dynamic_cost_elasticity_turnover_control", "mechanism": "reduce_turnover_from_observed_cost_return_elasticity", "degradation_ratio": 0.20}
        candidate, changes, semantic, skipped, family = _select_unique_dynamic_hypothesis_candidate(base, observed_failure="cost_fragile", iteration=1, known_semantic_fingerprints=known, driver=driver, max_variants=3)
        self.assertIsNotNone(candidate)
        self.assertIsNotNone(semantic)
        self.assertNotIn(semantic, known)
        self.assertEqual("dynamic_cost_elasticity_turnover_control", family)
        self.assertTrue(any("dynamic_hypothesis_family" in item for item in changes))
        self.assertLessEqual(len(skipped), 3)

    def test_dynamic_space_is_bounded_by_parameter_variant_budget(self) -> None:
        base = _baseline()
        driver = {"family": "dynamic_fold_consistency_rebalance", "mechanism": "reduce_fold_specific_parameter_dependence", "pass_ratio": 0.0}
        known = set()
        for variant in range(3):
            candidate, _, _ = _dynamic_hypothesis_candidate(base, observed_failure="walk_forward_fail", iteration=2, variant=variant, driver=driver)
            known.add(_strategy_semantic_fingerprint(candidate))
        candidate, changes, semantic, skipped, family = _select_unique_dynamic_hypothesis_candidate(base, observed_failure="walk_forward_fail", iteration=2, known_semantic_fingerprints=known, driver=driver, max_variants=3)
        self.assertIsNone(candidate)
        self.assertEqual([], changes)
        self.assertIsNone(semantic)
        self.assertEqual(3, len(skipped))
        self.assertEqual("dynamic_fold_consistency_rebalance", family)


if __name__ == "__main__":
    unittest.main()
