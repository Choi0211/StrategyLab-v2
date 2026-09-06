"""feature/regime-filtered-strategy-family (Research Brain wiring, A6).

PR #191 gave RuleBasedBacktestEngine a market-regime filter
(regime_bullish_only). This wires it into a first-class research family,
``breakout_regime_filtered`` - the standard 20-day breakout gated so it
can only open a position in a bullish regime (close above its 50-bar SMA
AND above its level 50 bars ago).

The regime gate is a PREFERENCE, not a licence: the candidate's
reconstructed spec still carries the same breakout entry trigger and the
same protective-stop / channel-low exits - the filter can only ever
REMOVE an entry the breakout already wanted, and it changes no risk
parameter. That is proven at the engine level in
tests/unit/test_market_regime_filter.py; here we prove the family is a
usable, candidate-native, distinctly-fingerprinted research candidate
that stays out of the breakout rotation and the autonomous paradigm
rotation.
"""

from __future__ import annotations

import unittest

from gaon.knowledge.strategy_candidate import (
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES,
    build_candidate_spec,
    new_candidate,
    next_untried_family,
    render_candidate_request_text,
)
from gaon.research.krx_real_pipeline import (
    RULE_BASED_BACKTEST_CAPABILITIES,
    UserStrategyParser,
    candidate_spec_from_rules_json,
)

NOW = "2026-09-06T00:00:00Z"
FAM = "breakout_regime_filtered"


def _reconstructed(candidate):
    return candidate_spec_from_rules_json(candidate.spec_rules, symbol="005930", created_at=NOW)


class RegimeFilteredFamilyIsResolvableTests(unittest.TestCase):
    def test_family_is_registered_and_builds_a_candidate(self) -> None:
        self.assertIn(FAM, {t.family for t in REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES})
        candidate = new_candidate(FAM, sequence=1, now=NOW)
        self.assertEqual(candidate.strategy_family, FAM)
        self.assertTrue(candidate.strategy_fingerprint)

    def test_spec_carries_the_breakout_trigger_and_the_regime_filter(self) -> None:
        spec = build_candidate_spec(FAM, created_at=NOW)
        self.assertIn("breakout_lookback", spec.entry)
        self.assertEqual(spec.filters["regime_bullish_only"].value, True)
        self.assertIn("regime_ma_lookback", spec.filters)
        # exits unchanged - regime never alters risk.
        self.assertEqual(spec.exit["protective_stop_pct"].value, -5.0)
        self.assertEqual(spec.exit["channel_exit_lookback"].value, 10)


class RegimeFilteredCandidateIsEngineNativeTests(unittest.TestCase):
    def test_spec_rules_reconstruct_to_an_engine_supported_spec(self) -> None:
        candidate = new_candidate(FAM, sequence=1, now=NOW)
        spec = _reconstructed(candidate)
        self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))
        # one entry trigger, still the breakout one.
        triggers = RULE_BASED_BACKTEST_CAPABILITIES.entry_trigger_rules & set(spec.entry)
        self.assertEqual(triggers, {"breakout_lookback"})
        self.assertIn("regime_bullish_only", spec.filters)

    def test_free_text_round_trip_drops_the_regime_gate_and_is_not_authoritative(self) -> None:
        candidate = new_candidate(FAM, sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "005930")
        parsed = UserStrategyParser().parse(text, symbol="005930")
        self.assertNotIn("regime_bullish_only", parsed.filters)
        self.assertNotEqual(parsed.strategy_family_fingerprint, candidate.strategy_fingerprint)


class RegimeFilteredFingerprintTests(unittest.TestCase):
    def test_fingerprint_is_deterministic(self) -> None:
        a = build_candidate_spec(FAM, created_at=NOW).strategy_family_fingerprint
        b = build_candidate_spec(FAM, created_at="2020-01-01T00:00:00Z").strategy_family_fingerprint
        self.assertEqual(a, b)

    def test_fingerprint_differs_from_plain_breakout_standard(self) -> None:
        regime_fp = build_candidate_spec(FAM, created_at=NOW).strategy_family_fingerprint
        plain_fp = build_candidate_spec("breakout_standard", created_at=NOW).strategy_family_fingerprint
        self.assertNotEqual(regime_fp, plain_fp)


class RegimeFilteredFamilyRotationIsolationTests(unittest.TestCase):
    def test_not_in_breakout_rotation(self) -> None:
        seen: set = set()
        existing: tuple = ()
        for _ in range(20):
            fam = next_untried_family(existing)
            if fam is None:
                break
            seen.add(fam)
            existing = existing + (new_candidate(fam, sequence=len(seen), now=NOW),)
        self.assertNotIn(FAM, seen)

    def test_not_in_the_non_breakout_paradigm_rotation_tuple(self) -> None:
        self.assertNotIn(FAM, {t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES})


if __name__ == "__main__":
    unittest.main()
