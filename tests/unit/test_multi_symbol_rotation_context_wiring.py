"""Priority 2 (continuation) - wire the real multi-symbol context flag
from the mission into the autonomous rotation.

``expand_strategy_space_candidate`` has had a
``multi_symbol_context_available`` gate since PR #206, but the only LIVE
call site (``LLMConversationBrain._try_mission_driven_research_cycle`` in
``gaon.runtime.llm_conversation``) never passed it, so a mission with a
real peer universe could still never rotate into the relative-strength
family.

This wires ``mission_multi_symbol_context_available(mission)`` into that
call site: True only when the mission carries an explicit multi-symbol
set (a primary + at least one real peer). A single-symbol mission stays
fail-closed, with ``relative_strength_requires_multi_symbol_context`` on
the exhausted verdict. No fake peer is ever synthesised.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
import unittest

from gaon.knowledge.research_mission import (
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
    mission_multi_symbol_context_available,
)
from gaon.knowledge.strategy_candidate import (
    ALL_STRATEGY_FAMILY_TEMPLATES,
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES,
    RELATIVE_STRENGTH_STRATEGY_FAMILY_TEMPLATES,
    STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES,
    expand_strategy_space_candidate,
    new_candidate,
)
from gaon.runtime import llm_conversation

NOW = "2026-09-06T00:00:00Z"
LATER = "2026-09-07T00:00:00Z"

_BREAKOUT = (*ALL_STRATEGY_FAMILY_TEMPLATES, *STRATEGY_SPACE_EXPANSION_ROUND_2_TEMPLATES)
_NON_BREAKOUT = tuple(t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES)
_REGIME = tuple(t.family for t in REGIME_FILTERED_STRATEGY_FAMILY_TEMPLATES)
_RS = tuple(t.family for t in RELATIVE_STRENGTH_STRATEGY_FAMILY_TEMPLATES)


def _mission(symbols: tuple[str, ...]) -> ResearchMission:
    return ResearchMission(
        mission_id="research-mission:wiring-test",
        market="KR",
        universe_scope=MissionUniverseScope.MARKET_WIDE if not symbols else MissionUniverseScope.SELECTED_SYMBOLS,
        symbols=symbols,
        exchanges=("KRX",),
        strategy_family="short_term_daytrade",
        improve_return=True,
        improve_safety=True,
        baseline_comparison="registered_strategy",
        target_promotion_ready_candidates=3,
        current_promotion_ready_candidates=0,
        promotion_ready_candidates=(),
        explored_symbols=(),
        status=MissionStatus.ACTIVE,
        blocked_reason=None,
        cycles_completed=4,
        created_at=NOW,
        updated_at=NOW,
        originating_request="wiring-test",
    )


def _drain(multi_symbol: bool):
    hist = [new_candidate(t.family, sequence=i + 1, now=NOW) for i, t in enumerate(_BREAKOUT)]
    seen = []
    for _ in range(40):
        exp = expand_strategy_space_candidate(
            tuple(hist), sequence=len(hist) + 1, now=LATER, multi_symbol_context_available=multi_symbol
        )
        if exp.candidate is None:
            return seen, exp
        seen.append(exp.candidate.strategy_family)
        hist.append(exp.candidate)
    raise AssertionError("rotation did not terminate")


class MissionMultiSymbolContextHelperTests(unittest.TestCase):
    def test_zero_or_one_symbol_has_no_multi_symbol_context(self) -> None:
        self.assertFalse(mission_multi_symbol_context_available(_mission(())))
        self.assertFalse(mission_multi_symbol_context_available(_mission(("005930",))))

    def test_two_or_more_symbols_is_a_real_multi_symbol_context(self) -> None:
        self.assertTrue(mission_multi_symbol_context_available(_mission(("005930", "000660"))))
        self.assertTrue(mission_multi_symbol_context_available(_mission(("005930", "000660", "005380"))))


class LiveRotationCallSiteIsWiredTests(unittest.TestCase):
    def test_try_mission_driven_cycle_passes_the_helper_result_to_expand(self) -> None:
        src = textwrap.dedent(
            inspect.getsource(llm_conversation.LLMConversationBrain._try_mission_driven_research_cycle)
        )
        tree = ast.parse(src)
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "expand_strategy_space_candidate"
        ]
        self.assertTrue(calls, "no expand_strategy_space_candidate call found in the live rotation method")
        for call in calls:
            kw = {k.arg: k.value for k in call.keywords}
            self.assertIn(
                "multi_symbol_context_available",
                kw,
                "the live rotation call must pass multi_symbol_context_available",
            )
            value = kw["multi_symbol_context_available"]
            self.assertIsInstance(value, ast.Call, "flag must be computed, not a literal")
            self.assertEqual(getattr(value.func, "id", None), "mission_multi_symbol_context_available")


class HelperResultActuallyUnlocksRelativeStrengthTests(unittest.TestCase):
    def test_single_symbol_helper_value_keeps_relative_strength_gated(self) -> None:
        flag = mission_multi_symbol_context_available(_mission(("005930",)))
        seen, terminal = _drain(flag)
        for fam in _RS:
            self.assertNotIn(fam, seen)
        self.assertIn("relative_strength_requires_multi_symbol_context", terminal.evidence_signals)

    def test_multi_symbol_helper_value_lets_relative_strength_into_the_rotation(self) -> None:
        flag = mission_multi_symbol_context_available(_mission(("005930", "000660")))
        seen, terminal = _drain(flag)
        self.assertEqual(seen[-len(_RS):], list(_RS))
        self.assertNotIn("relative_strength_requires_multi_symbol_context", terminal.evidence_signals)


if __name__ == "__main__":
    unittest.main()
