from __future__ import annotations

import unittest

from gaon.knowledge.autonomous_quant_partner import (
    _adaptive_candidate_for_failure,
    _adaptive_research_dimensions,
)
from gaon.research.krx_real_pipeline import (
    CanonicalStrategySpec,
    FieldProvenance,
    ProvenancedValue,
)


def _value(value):
    return ProvenancedValue(value, FieldProvenance.DEFAULT)


def _baseline() -> CanonicalStrategySpec:
    return CanonicalStrategySpec(
        "canonical-strategy:test",
        "005930",
        {
            "breakout_lookback": _value(20),
            "close_gt_ma20": _value(True),
            "ma20_gt_ma60": _value(True),
        },
        {
            "protective_stop_pct": _value(-5.0),
            "channel_exit_lookback": _value(10),
        },
        {"volume_gte_ma20": _value(True)},
        "test strategy",
        "2026-08-15T00:00:00Z",
    )


class AdaptiveCandidateStructuralDiversificationTests(unittest.TestCase):
    def test_oos_changes_confirmation_structure(self) -> None:
        base = _baseline()
        candidate, changes = _adaptive_candidate_for_failure(
            base,
            observed_failure="out_of_sample_fail",
            iteration=1,
        )
        self.assertNotIn("close_gt_ma20", candidate.entry)
        self.assertIn("ma20_gt_ma60", candidate.entry)
        self.assertIn("volume_gte_ma20", candidate.filters)
        self.assertTrue(
            any("redundant_oos_confirmation" in item for item in changes)
        )

    def test_walk_forward_simplifies_optional_filter(self) -> None:
        base = _baseline()
        candidate, changes = _adaptive_candidate_for_failure(
            base,
            observed_failure="walk_forward_fail",
            iteration=2,
        )
        self.assertNotIn("volume_gte_ma20", candidate.filters)
        self.assertEqual(
            base.entry["breakout_lookback"].value,
            candidate.entry["breakout_lookback"].value,
        )
        self.assertTrue(
            any("walk_forward_simplification" in item for item in changes)
        )

    def test_cost_fragility_changes_entry_and_exit_horizons(self) -> None:
        base = _baseline()
        candidate, changes = _adaptive_candidate_for_failure(
            base,
            observed_failure="cost_fragile",
            iteration=3,
        )
        self.assertGreater(
            candidate.entry["breakout_lookback"].value,
            base.entry["breakout_lookback"].value,
        )
        self.assertGreater(
            candidate.exit["channel_exit_lookback"].value,
            base.exit["channel_exit_lookback"].value,
        )
        self.assertTrue(
            any("channel_exit_lookback" in item for item in changes)
        )

    def test_sample_insufficiency_increases_frequency_without_filter_removal(self) -> None:
        base = _baseline()
        candidate, changes = _adaptive_candidate_for_failure(
            base,
            observed_failure="insufficient_trades",
            iteration=4,
        )
        self.assertLess(
            candidate.entry["breakout_lookback"].value,
            base.entry["breakout_lookback"].value,
        )
        self.assertEqual(base.filters, candidate.filters)
        self.assertIn("close_gt_ma20", candidate.entry)
        self.assertIn("ma20_gt_ma60", candidate.entry)
        self.assertIn(
            "opportunity_frequency:increase_without_filter_removal",
            changes,
        )

    def test_failure_types_produce_materially_distinct_fingerprints(self) -> None:
        base = _baseline()
        failures = (
            "out_of_sample_fail",
            "walk_forward_fail",
            "cost_fragile",
            "insufficient_trades",
        )
        fingerprints = {
            _adaptive_candidate_for_failure(
                base,
                observed_failure=failure,
                iteration=index,
            )[0].fingerprint
            for index, failure in enumerate(failures, start=1)
        }
        self.assertEqual(len(failures), len(fingerprints))

    def test_research_dimensions_match_structural_intent(self) -> None:
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
        self.assertIn(
            "opportunity_frequency",
            _adaptive_research_dimensions("insufficient_trades", []),
        )


if __name__ == "__main__":
    unittest.main()
