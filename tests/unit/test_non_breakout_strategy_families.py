"""feature/mean-reversion-strategy-family, feature/momentum-strategy-family, ...

The engine PRs #187-#191 gave RuleBasedBacktestEngine real non-breakout
signals; these tests prove each one is wired into the Research Brain as a
first-class strategy family: it resolves through ``_template`` /
``build_candidate_spec`` / ``new_candidate``, its persisted ``spec_rules``
reconstruct (candidate-native, NOT via free text) into an engine-
SUPPORTED spec whose ONE entry trigger is the family's real trigger, its
family fingerprint is deterministic and distinct from every other
family, and it stays OUT of the breakout rotation / positional-zip
tuples so existing missions are untouched.

Each non-breakout family adds one row to ``_FAMILIES`` below; the shared
invariants are then exercised for it automatically.
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

# family -> (expected sole entry-trigger key, a substring that must NOT
# appear in the descriptive request text).
_FAMILIES = {
    "mean_reversion_standard": ("mean_reversion_ma_lookback", "돌파"),
    "momentum_roc_standard": ("momentum_roc_lookback", "돌파"),
}


def _reconstructed(candidate):
    return candidate_spec_from_rules_json(candidate.spec_rules, symbol="005930", created_at=NOW)


class NonBreakoutFamiliesAreFirstClassCandidatesTests(unittest.TestCase):
    def test_each_family_is_registered_in_the_non_breakout_tuple(self) -> None:
        registered = {t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES}
        for family in _FAMILIES:
            with self.subTest(family=family):
                self.assertIn(family, registered)

    def test_each_family_builds_a_candidate_native_engine_supported_spec(self) -> None:
        for family, (trigger_key, _) in _FAMILIES.items():
            with self.subTest(family=family):
                candidate = new_candidate(family, sequence=1, now=NOW)
                self.assertEqual(candidate.strategy_family, family)
                spec = _reconstructed(candidate)
                self.assertNotIn("breakout_lookback", spec.entry)
                self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))
                triggers = RULE_BASED_BACKTEST_CAPABILITIES.entry_trigger_rules & set(spec.entry)
                self.assertEqual(triggers, {trigger_key})
                # the persisted spec_rules carry the same trigger.
                self.assertIn(trigger_key, candidate.spec_rules["entry"])

    def test_free_text_round_trip_is_not_authoritative_for_any_non_breakout_family(self) -> None:
        for family, (_, forbidden) in _FAMILIES.items():
            with self.subTest(family=family):
                candidate = new_candidate(family, sequence=1, now=NOW)
                text = render_candidate_request_text(candidate, "005930")
                self.assertNotIn(forbidden, text)
                parsed = UserStrategyParser().parse(text, symbol="005930")
                self.assertNotEqual(parsed.strategy_family_fingerprint, candidate.strategy_fingerprint)


class NonBreakoutFamilyFingerprintsAreDistinctTests(unittest.TestCase):
    def test_each_fingerprint_is_deterministic(self) -> None:
        for family in _FAMILIES:
            with self.subTest(family=family):
                a = build_candidate_spec(family, created_at=NOW).strategy_family_fingerprint
                b = build_candidate_spec(family, created_at="2020-01-01T00:00:00Z").strategy_family_fingerprint
                self.assertEqual(a, b)

    def test_all_family_fingerprints_are_pairwise_distinct(self) -> None:
        breakout = [
            t.family for t in (*ALL_STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES)
        ]
        non_breakout = list(_FAMILIES)
        fps = {
            fam: build_candidate_spec(fam, created_at=NOW).strategy_family_fingerprint
            for fam in (*breakout, *non_breakout)
        }
        self.assertEqual(len(set(fps.values())), len(fps))


class NonBreakoutFamiliesDoNotDisturbBreakoutRotationTests(unittest.TestCase):
    def test_all_strategy_family_templates_still_length_nine(self) -> None:
        self.assertEqual(len(ALL_STRATEGY_FAMILY_TEMPLATES), 9)

    def test_non_breakout_tuple_is_disjoint_from_the_breakout_tuples(self) -> None:
        breakout_families = {
            t.family
            for t in (*STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_TEMPLATES, *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES)
        }
        non_breakout = {t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES}
        self.assertEqual(breakout_families & non_breakout, set())

    def test_next_untried_family_never_returns_a_non_breakout_family(self) -> None:
        seen: set = set()
        existing: tuple = ()
        for _ in range(30):
            fam = next_untried_family(existing)
            if fam is None:
                break
            seen.add(fam)
            existing = existing + (new_candidate(fam, sequence=len(seen), now=NOW),)
        self.assertEqual(seen & set(_FAMILIES), set())


if __name__ == "__main__":
    unittest.main()
