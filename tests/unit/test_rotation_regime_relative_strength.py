"""Priority 6 - autonomous rotation completion: regime + relative strength.

After breakout base -> expansion round 1 -> round 2 -> the non-breakout
paradigms (mean_reversion -> momentum -> volatility), the rotation now
also visits:
  - the regime-filtered family (safe on a single symbol), then
  - the relative-strength family, but ONLY when the mission actually has
    a multi-symbol validation context. Without one it is NEVER offered as
    a research candidate; the exhausted verdict carries
    ``relative_strength_requires_multi_symbol_context`` so the reason is
    explicit, not silent.
"""

from __future__ import annotations

import unittest

from gaon.knowledge.strategy_candidate import (
    ALL_STRATEGY_FAMILY_TEMPLATES,
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES,
    RELATIVE_STRENGTH_STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES,
    expand_strategy_space_candidate,
    new_candidate,
)

NOW = "2026-09-06T00:00:00Z"
LATER = "2026-09-07T00:00:00Z"

_BREAKOUT = (*ALL_STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES)
_NON_BREAKOUT = tuple(t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES)
_REGIME = tuple(t.family for t in REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES)
_RS = tuple(t.family for t in RELATIVE_STRENGTH_STRATEGY_FAMILY_TEMPLATES)


def _history(*families):
    return [new_candidate(f, sequence=i + 1, now=NOW) for i, f in enumerate(families)]


def _drain(history, *, multi_symbol):
    out = []
    hist = list(history)
    for _ in range(40):
        exp = expand_strategy_space_candidate(
            tuple(hist), sequence=len(hist) + 1, now=LATER, multi_symbol_context_available=multi_symbol
        )
        if exp.candidate is None:
            return out, exp
        out.append(exp.candidate.strategy_family)
        hist.append(exp.candidate)
    raise AssertionError("rotation did not terminate")


class RegimeFamilyEntersTheRotationTests(unittest.TestCase):
    def test_regime_family_is_rotated_after_the_non_breakout_paradigms(self) -> None:
        seen, terminal = _drain(_history(*[t.family for t in _BREAKOUT]), multi_symbol=False)
        # order: non-breakout paradigms, then regime-filtered, then terminal.
        self.assertEqual(seen[: len(_NON_BREAKOUT)], list(_NON_BREAKOUT))
        self.assertEqual(seen[len(_NON_BREAKOUT):], list(_REGIME))
        self.assertIsNone(terminal.candidate)
        self.assertEqual(terminal.reason, "strategy_hypothesis_space_exhausted")


class RelativeStrengthNeedsAMultiSymbolContextTests(unittest.TestCase):
    def test_single_symbol_mission_never_rotates_into_relative_strength(self) -> None:
        seen, terminal = _drain(_history(*[t.family for t in _BREAKOUT]), multi_symbol=False)
        for fam in _RS:
            self.assertNotIn(fam, seen)
        self.assertIn("relative_strength_requires_multi_symbol_context", terminal.evidence_signals)

    def test_multi_symbol_mission_does_rotate_into_relative_strength_last(self) -> None:
        seen, terminal = _drain(_history(*[t.family for t in _BREAKOUT]), multi_symbol=True)
        self.assertEqual(seen[-len(_RS):], list(_RS))
        self.assertIsNone(terminal.candidate)
        self.assertNotIn("relative_strength_requires_multi_symbol_context", terminal.evidence_signals)

    def test_rotation_is_restart_safe_across_the_new_phases(self) -> None:
        hist = _history(*[t.family for t in _BREAKOUT], *_NON_BREAKOUT)
        a = expand_strategy_space_candidate(tuple(hist), sequence=len(hist) + 1, now=LATER, multi_symbol_context_available=True)
        b = expand_strategy_space_candidate(tuple(hist), sequence=len(hist) + 1, now=LATER, multi_symbol_context_available=True)
        assert a.candidate is not None and b.candidate is not None
        self.assertEqual(a.candidate.strategy_family, b.candidate.strategy_family)
        self.assertEqual(a.candidate.strategy_fingerprint, b.candidate.strategy_fingerprint)


class BreakoutAndParadigmPhasesUnchangedTests(unittest.TestCase):
    def test_default_call_without_the_flag_still_works_and_excludes_relative_strength(self) -> None:
        # backward-compatible signature: multi_symbol_context_available defaults False.
        hist = _history(*[t.family for t in _BREAKOUT])
        exp = expand_strategy_space_candidate(tuple(hist), sequence=len(hist) + 1, now=LATER)
        assert exp.candidate is not None
        self.assertIn(exp.candidate.strategy_family, _NON_BREAKOUT)


if __name__ == "__main__":
    unittest.main()
