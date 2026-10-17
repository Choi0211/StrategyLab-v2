from __future__ import annotations

import unittest

from gaon.knowledge.strategy_candidate import (
    ALL_STRATEGY_FAMILY_TEMPLATES,
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES,
    STRUCTURAL_FILTER_STRATEGY_FAMILY_TEMPLATES,
    build_candidate_spec,
    expand_strategy_space_candidate,
    new_candidate,
)
from gaon.research.krx_real_pipeline import RuleBasedBacktestCapabilities

NOW = "2026-10-17T00:00:00Z"
LATER = "2026-10-18T00:00:00Z"

_PREVIOUS_ROTATION = (
    *ALL_STRATEGY_FAMILY_TEMPLATES,
    *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES,
    *NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    *REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES,
)


class StructuralFilterHypothesisExpansionTests(unittest.TestCase):
    def test_new_phase_starts_only_after_previous_rotation_is_exhausted(self) -> None:
        history = tuple(new_candidate(t.family, sequence=i + 1, now=NOW) for i, t in enumerate(_PREVIOUS_ROTATION))
        expansion = expand_strategy_space_candidate(history, sequence=len(history) + 1, now=LATER)
        self.assertIsNotNone(expansion.candidate)
        self.assertEqual(expansion.reason, "structural_filter_hypothesis_expansion")
        self.assertEqual(expansion.candidate.strategy_family, STRUCTURAL_FILTER_STRATEGY_FAMILY_TEMPLATES[0].family)

    def test_phase_is_bounded_restart_safe_and_drains_without_duplicates(self) -> None:
        history = [new_candidate(t.family, sequence=i + 1, now=NOW) for i, t in enumerate(_PREVIOUS_ROTATION)]
        seen = []
        for _ in range(len(STRUCTURAL_FILTER_STRATEGY_FAMILY_TEMPLATES)):
            a = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
            b = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
            self.assertIsNotNone(a.candidate)
            self.assertEqual(a.candidate.strategy_family, b.candidate.strategy_family)
            self.assertEqual(a.candidate.strategy_fingerprint, b.candidate.strategy_fingerprint)
            self.assertEqual(a.reason, "structural_filter_hypothesis_expansion")
            seen.append(a.candidate.strategy_family)
            history.append(a.candidate)
        self.assertEqual(seen, [t.family for t in STRUCTURAL_FILTER_STRATEGY_FAMILY_TEMPLATES])
        terminal = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
        self.assertIsNone(terminal.candidate)
        self.assertEqual(terminal.reason, "strategy_hypothesis_space_exhausted")

    def test_every_new_family_is_engine_native_unique_and_keeps_default_risk_exit(self) -> None:
        fingerprints = set()
        capabilities = RuleBasedBacktestCapabilities()
        for template in STRUCTURAL_FILTER_STRATEGY_FAMILY_TEMPLATES:
            spec = build_candidate_spec(template.family, created_at=NOW)
            # The engine's own executable capability contract is authoritative:
            # no unknown or missing rule may enter the autonomous rotation.
            self.assertEqual(capabilities.unsupported_components(spec), ())
            self.assertNotIn(spec.strategy_family_fingerprint, fingerprints)
            fingerprints.add(spec.strategy_family_fingerprint)
            self.assertEqual(spec.exit["protective_stop_pct"].value, -5.0)
            self.assertEqual(spec.exit["channel_exit_lookback"].value, 10)
            self.assertNotIn("leverage", spec.entry)
            self.assertNotIn("position_size", spec.entry)
            self.assertTrue(
                bool(spec.filters.get("volume_gte_ma20")) or bool(spec.filters.get("regime_bullish_only")),
                template.family,
            )


if __name__ == "__main__":
    unittest.main()
