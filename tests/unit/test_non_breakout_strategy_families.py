"""feature/mean-reversion-strategy-family (Research Brain wiring).

PRs #187-#191 gave RuleBasedBacktestEngine real non-breakout entry
computations (mean-reversion, momentum, volatility thrust) and two
cross-symbol/regime filters - but the Research Brain could still only
propose the 16 breakout-combination families in
``strategy_candidate.py``. `new_candidate("mean_reversion_standard")`
raised ``ValueError: unknown strategy family``.

This suite proves the first non-breakout family is now a first-class
research candidate: it resolves through ``_template`` /
``build_candidate_spec`` / ``new_candidate``, its persisted ``spec_rules``
reconstruct (candidate-native, NOT via free-text) into an engine-
SUPPORTED spec that genuinely uses the mean-reversion entry trigger, its
family fingerprint is deterministic and distinct from every breakout
family, and it stays OUT of the breakout rotation / positional-zip
tuples so existing missions are untouched.
"""

from __future__ import annotations

import unittest

from gaon.knowledge.strategy_candidate import (
    ALL_STRATEGY_FAMILY_TEMPLATES,
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_TEMPLATES,
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
MR = "mean_reversion_standard"


def _reconstructed(candidate):
    return candidate_spec_from_rules_json(candidate.spec_rules, symbol="005930", created_at=NOW)


class MeanReversionFamilyIsResolvableTests(unittest.TestCase):
    def test_family_is_registered_and_builds_a_candidate(self) -> None:
        self.assertIn(MR, {t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES})
        candidate = new_candidate(MR, sequence=1, now=NOW)
        self.assertEqual(candidate.strategy_family, MR)
        self.assertTrue(candidate.strategy_fingerprint)
        self.assertIn("entry", candidate.spec_rules)

    def test_build_candidate_spec_carries_the_mean_reversion_rules(self) -> None:
        spec = build_candidate_spec(MR, created_at=NOW)
        self.assertIn("mean_reversion_ma_lookback", spec.entry)
        self.assertNotIn("breakout_lookback", spec.entry)
        self.assertIn("protective_stop_pct", spec.exit)


class MeanReversionCandidateIsEngineNativeTests(unittest.TestCase):
    def test_spec_rules_reconstruct_to_an_engine_supported_mean_reversion_spec(self) -> None:
        candidate = new_candidate(MR, sequence=1, now=NOW)
        spec = _reconstructed(candidate)
        # candidate-native reconstruction (NOT free text) - the real rules.
        self.assertIn("mean_reversion_ma_lookback", spec.entry)
        self.assertNotIn("breakout_lookback", spec.entry)
        self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))
        # exactly one entry trigger, and it is the mean-reversion one.
        triggers = RULE_BASED_BACKTEST_CAPABILITIES.entry_trigger_rules & set(spec.entry)
        self.assertEqual(triggers, {"mean_reversion_ma_lookback"})

    def test_free_text_round_trip_is_NOT_authoritative_for_this_family(self) -> None:
        # The Korean description is display-only; a breakout-only parser
        # cannot reproduce the mean-reversion rules, and nothing relies on
        # it doing so (candidate-native spec_rules are the source of truth).
        candidate = new_candidate(MR, sequence=1, now=NOW)
        text = render_candidate_request_text(candidate, "005930")
        self.assertNotIn("돌파", text)
        parsed = UserStrategyParser().parse(text, symbol="005930")
        self.assertNotEqual(parsed.strategy_family_fingerprint, candidate.strategy_fingerprint)


class MeanReversionFingerprintIsDistinctTests(unittest.TestCase):
    def test_fingerprint_is_deterministic(self) -> None:
        a = build_candidate_spec(MR, created_at=NOW).strategy_family_fingerprint
        b = build_candidate_spec(MR, created_at="2020-01-01T00:00:00Z").strategy_family_fingerprint
        self.assertEqual(a, b)

    def test_fingerprint_differs_from_every_breakout_family(self) -> None:
        mr_fp = build_candidate_spec(MR, created_at=NOW).strategy_family_fingerprint
        breakout_fps = {
            build_candidate_spec(t.family, created_at=NOW).strategy_family_fingerprint
            for t in (*ALL_STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES)
        }
        self.assertNotIn(mr_fp, breakout_fps)


class MeanReversionDoesNotDisturbBreakoutRotationTests(unittest.TestCase):
    def test_all_strategy_family_templates_still_length_nine(self) -> None:
        self.assertEqual(len(ALL_STRATEGY_FAMILY_TEMPLATES), 9)

    def test_non_breakout_tuple_is_separate_from_the_breakout_tuples(self) -> None:
        breakout_families = {
            t.family
            for t in (*STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_TEMPLATES, *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES)
        }
        non_breakout = {t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES}
        self.assertEqual(breakout_families & non_breakout, set())

    def test_next_untried_family_never_returns_a_non_breakout_family(self) -> None:
        # next_untried_family drives the CURRENT breakout rotation; a
        # non-breakout family must not appear there (autonomous rotation
        # across paradigms is a later, explicit PR).
        seen = set()
        existing: tuple = ()
        for _ in range(20):
            fam = next_untried_family(existing)
            if fam is None:
                break
            seen.add(fam)
            existing = existing + (new_candidate(fam, sequence=len(seen), now=NOW),)
        self.assertNotIn(MR, seen)


if __name__ == "__main__":
    unittest.main()
