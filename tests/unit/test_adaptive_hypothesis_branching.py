from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_quant_partner import (
    _adaptive_candidate_for_failure,
    _hypothesis_branch_candidate,
    _select_unique_adaptive_candidate,
    _select_unique_hypothesis_branch_candidate,
    _strategy_semantic_fingerprint,
)
from gaon.research.krx_real_pipeline import (
    CanonicalStrategySpec,
    FieldProvenance,
    ProvenancedValue,
)


def _v(value):
    return ProvenancedValue(value, FieldProvenance.DEFAULT)


def _baseline() -> CanonicalStrategySpec:
    return CanonicalStrategySpec(
        "canonical-strategy:test",
        "005930",
        {
            "breakout_lookback": _v(30),
            "close_gt_ma20": _v(True),
        },
        {"protective_stop_pct": _v(-5.0)},
        {"volume_gte_ma20": _v(True)},
        "test strategy",
        "2026-08-15T00:00:00Z",
    )


class AdaptiveHypothesisBranchingTests(unittest.TestCase):
    def test_walk_forward_primary_exhaustion_branches_to_regime_persistence(self) -> None:
        base = _baseline()
        known = set()
        for variant in range(4):
            candidate, _ = _adaptive_candidate_for_failure(
                base,
                observed_failure="walk_forward_fail",
                iteration=1,
                variant=variant,
            )
            known.add(_strategy_semantic_fingerprint(candidate))

        primary, _, _, skipped = _select_unique_adaptive_candidate(
            base,
            observed_failure="walk_forward_fail",
            iteration=1,
            known_semantic_fingerprints=set(known),
        )
        self.assertIsNone(primary)
        self.assertEqual(4, len(skipped))

        branch, changes, semantic, branch_skipped, family = (
            _select_unique_hypothesis_branch_candidate(
                base,
                observed_failure="walk_forward_fail",
                iteration=1,
                known_semantic_fingerprints=set(known),
            )
        )
        self.assertIsNotNone(branch)
        self.assertEqual("regime_persistence", family)
        self.assertIsNotNone(semantic)
        self.assertEqual([], branch_skipped)
        self.assertTrue(any("channel_exit_lookback" in item for item in changes))

    def test_hypothesis_branch_is_semantically_distinct_from_primary_variants(self) -> None:
        base = _baseline()
        primary_semantics = {
            _strategy_semantic_fingerprint(
                _adaptive_candidate_for_failure(
                    base,
                    observed_failure="cost_fragile",
                    iteration=1,
                    variant=variant,
                )[0]
            )
            for variant in range(4)
        }
        branch, _, family = _hypothesis_branch_candidate(
            base,
            observed_failure="cost_fragile",
            iteration=1,
            branch=0,
        )
        self.assertEqual("trend_quality_selectivity", family)
        self.assertNotIn(_strategy_semantic_fingerprint(branch), primary_semantics)

    def test_hypothesis_branch_space_is_bounded(self) -> None:
        base = _baseline()
        known = set()
        for branch_index in range(2):
            candidate, _, _ = _hypothesis_branch_candidate(
                base,
                observed_failure="out_of_sample_fail",
                iteration=1,
                branch=branch_index,
            )
            known.add(_strategy_semantic_fingerprint(candidate))

        candidate, changes, semantic, skipped, family = (
            _select_unique_hypothesis_branch_candidate(
                base,
                observed_failure="out_of_sample_fail",
                iteration=1,
                known_semantic_fingerprints=known,
            )
        )
        self.assertIsNone(candidate)
        self.assertEqual([], changes)
        self.assertIsNone(semantic)
        self.assertEqual(2, len(skipped))
        self.assertEqual("trend_persistence_generalization", family)


if __name__ == "__main__":
    unittest.main()
