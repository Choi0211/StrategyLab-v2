"""feature/autonomous-paradigm-rotation (A7 - autonomous family rotation).

Before this change the Research Brain's bounded strategy space was
breakout-only: base 4 families -> STRATEGY_SPACE_EXPANSION_TEMPLATES
(round 1, 5) -> STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES (round 2, 7)
-> ``strategy_hypothesis_space_exhausted``. A mission that used all 16
breakout combinations terminated, even though the engine can now compute
genuinely different paradigms (mean-reversion, momentum, volatility) and
those families are registered.

``expand_strategy_space_candidate`` now has a THIRD phase: once both
breakout expansion rounds are exhausted it rotates, in deterministic
tuple order, through NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES - one
candidate per paradigm, restart-safe (keyed only off the persisted
candidate history) - with ``reason="strategy_paradigm_rotation"``. Only
once those are ALSO used does it return ``candidate=None`` /
``strategy_hypothesis_space_exhausted`` - the SAME terminal string and
downstream handling as before, just reached later.
"""

from __future__ import annotations

import unittest

from gaon.knowledge.strategy_candidate import (
    ALL_STRATEGY_FAMILY_TEMPLATES,
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES,
    expand_strategy_space_candidate,
    new_candidate,
)

NOW = "2026-09-06T00:00:00Z"
LATER = "2026-09-07T00:00:00Z"

_ALL_BREAKOUT = (*ALL_STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES)


def _breakout_history():
    return [new_candidate(t.family, sequence=i + 1, now=NOW) for i, t in enumerate(_ALL_BREAKOUT)]


class ParadigmRotationBeginsAfterBreakoutExhaustionTests(unittest.TestCase):
    def test_first_rotation_candidate_is_a_non_breakout_family(self) -> None:
        history = _breakout_history()
        exp = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
        self.assertIsNotNone(exp.candidate)
        assert exp.candidate is not None
        self.assertIn(
            exp.candidate.strategy_family,
            {t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES},
        )
        self.assertEqual(exp.reason, "strategy_paradigm_rotation")
        self.assertEqual(exp.action, "EXPAND_STRATEGY_SPACE")

    def test_rotation_follows_deterministic_tuple_order(self) -> None:
        history = _breakout_history()
        seen: list[str] = []
        for _ in range(len(NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES)):
            exp = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
            self.assertIsNotNone(exp.candidate)
            assert exp.candidate is not None
            seen.append(exp.candidate.strategy_family)
            history.append(exp.candidate)
        self.assertEqual(seen, [t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES])
        # ordered: mean_reversion -> momentum -> volatility
        self.assertEqual(seen[0], "mean_reversion_standard")

    def test_terminal_state_only_after_every_paradigm_is_used(self) -> None:
        history = _breakout_history()
        for _ in range(len(NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES)):
            exp = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
            assert exp.candidate is not None
            history.append(exp.candidate)
        exp = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
        self.assertIsNone(exp.candidate)
        self.assertEqual(exp.reason, "strategy_hypothesis_space_exhausted")

    def test_rotation_is_restart_safe_and_never_repeats_a_family(self) -> None:
        history = _breakout_history()
        first = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
        again = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
        assert first.candidate is not None and again.candidate is not None
        self.assertEqual(first.candidate.strategy_family, again.candidate.strategy_family)
        self.assertEqual(first.candidate.strategy_fingerprint, again.candidate.strategy_fingerprint)
        # add it, the next call must move on, never repeat.
        history.append(first.candidate)
        nxt = expand_strategy_space_candidate(tuple(history), sequence=len(history) + 1, now=LATER)
        assert nxt.candidate is not None
        self.assertNotEqual(nxt.candidate.strategy_family, first.candidate.strategy_family)


class BreakoutSpaceUnchangedTests(unittest.TestCase):
    def test_breakout_rounds_still_come_first_and_unchanged(self) -> None:
        # Only base 4 breakout used -> round 1 still selected first.
        base = [new_candidate(t.family, sequence=i + 1, now=NOW) for i, t in enumerate(ALL_STRATEGY_FAMILY_TEMPLATES)]
        exp = expand_strategy_space_candidate(tuple(base), sequence=len(base) + 1, now=LATER)
        assert exp.candidate is not None
        self.assertEqual(exp.reason, "strategy_family_space_exhausted")
        self.assertNotIn(
            exp.candidate.strategy_family,
            {t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES},
        )


if __name__ == "__main__":
    unittest.main()
