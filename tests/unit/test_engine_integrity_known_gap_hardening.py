"""fix/engine-integrity-known-gap-hardening.

Closes three residual gaps flagged in PR #185's report, BEFORE any
non-breakout strategy family is added:

1. A registered PREDICATE rule (close_gt_ma20 / ma20_gt_ma60 /
   volume_gte_ma20) whose CanonicalStrategySpec value is not a real bool
   was silently coerced by `bool(provenanced.value)` in
   `_predicate_rule_active`. It must instead fail closed at
   `RuleBasedBacktestCapabilities.validate` - like every other spec the
   engine cannot honour exactly.

2. `render_candidate_request_text` silently disguised a family with no
   `_FAMILY_REQUEST_TEXT` entry as `breakout_standard`'s specific request
   text. It must instead produce an honest, family-named description.

3. `is_mission_compatible_with_request` ignored engine-supportedness. When
   a durable owner mission already has a concrete active candidate whose
   exact rules the engine CANNOT run, it was still resolved as a
   continuation target. A mission with NO candidate yet keeps its
   family/market compatibility semantics unchanged.
"""

from __future__ import annotations

import unittest

from gaon.knowledge.research_mission import (
    DEFAULT_KR_EXCHANGES,
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
    is_mission_compatible_with_request,
)
from gaon.knowledge.strategy_candidate import (
    StrategyFamilyTemplate,
    _TEMPLATE_BY_FAMILY,
    build_candidate_spec,
    new_candidate,
    render_candidate_request_text,
)
from gaon.research.krx_real_pipeline import (
    RULE_BASED_BACKTEST_CAPABILITIES,
    CanonicalStrategySpec,
    FieldProvenance,
    KRXFixtureMarketDataProvider,
    ProvenancedValue,
    RuleBasedBacktestEngine,
    UnsupportedStrategySpecError,
    default_execution_assumptions,
)

NOW = "2026-07-25T00:00:00Z"


def _v(value, prov=FieldProvenance.RESEARCH_CANDIDATE):
    return ProvenancedValue(value, prov)


def _spec(entry, exit_rules, filters):
    return CanonicalStrategySpec("canonical-strategy:test", "005930", dict(entry), dict(exit_rules), dict(filters), "test", NOW)


_ENTRY = {"breakout_lookback": _v(20)}
_EXIT = {"protective_stop_pct": _v(-5.0), "channel_exit_lookback": _v(10)}


def _run(spec):
    ds = KRXFixtureMarketDataProvider().fetch_bars("005930", start_date="2026-01-01", end_date="2026-07-10")
    return RuleBasedBacktestEngine().run("unit-run", spec, ds, default_execution_assumptions(), generated_at=NOW)


# ---------------------------------------------------------------------------
# GAP 1 - non-bool predicate value fails closed
# ---------------------------------------------------------------------------
class NonBooleanPredicateValueFailsClosedTests(unittest.TestCase):
    def test_string_value_for_a_predicate_rule_is_rejected(self) -> None:
        spec = _spec({**_ENTRY, "close_gt_ma20": _v("true")}, _EXIT, {})
        self.assertFalse(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            RULE_BASED_BACKTEST_CAPABILITIES.validate(spec)
        self.assertIn("close_gt_ma20", str(ctx.exception))
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(spec)

    def test_int_value_for_a_filter_predicate_is_rejected(self) -> None:
        spec = _spec(_ENTRY, _EXIT, {"volume_gte_ma20": _v(1)})
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            _run(spec)
        self.assertIn("volume_gte_ma20", str(ctx.exception))

    def test_real_bool_values_still_pass(self) -> None:
        for value in (True, False):
            with self.subTest(value=value):
                spec = _spec({**_ENTRY, "ma20_gt_ma60": _v(value)}, _EXIT, {"volume_gte_ma20": _v(value)})
                RULE_BASED_BACKTEST_CAPABILITIES.validate(spec)  # no raise
                self.assertEqual(_run(spec).status, "completed")

    def test_a_parameter_rule_int_value_is_unaffected(self) -> None:
        # breakout_lookback is a parameter, not a predicate - an int is
        # exactly what it wants.
        spec = _spec({"breakout_lookback": _v(20)}, _EXIT, {})
        RULE_BASED_BACKTEST_CAPABILITIES.validate(spec)
        self.assertEqual(_run(spec).status, "completed")


# ---------------------------------------------------------------------------
# GAP 2 - render text is honest for an unmapped family
# ---------------------------------------------------------------------------
class RenderCandidateRequestTextNoBreakoutDisguiseTests(unittest.TestCase):
    def test_unmapped_family_text_names_the_family_and_is_not_breakout_standard(self) -> None:
        gap_family = "engine_integrity_test_unmapped_family"
        template = StrategyFamilyTemplate(
            gap_family, "테스트 전용", {"breakout_lookback": 20},
            {"protective_stop_pct": -5.0, "channel_exit_lookback": 10}, {},
        )
        from unittest.mock import patch

        with patch.dict(_TEMPLATE_BY_FAMILY, {gap_family: template}):
            candidate = new_candidate(gap_family, sequence=1, now=NOW)
            text = render_candidate_request_text(candidate, "005930")
        self.assertIn(gap_family, text)
        self.assertNotIn("고가 돌파", text)  # breakout_standard's specific wording
        self.assertTrue(text.startswith("005930 "))

    def test_every_mapped_family_text_is_unchanged(self) -> None:
        # Regression: the 16 shipped families all have a curated entry, so
        # their descriptive text must be byte-for-byte what it was.
        from gaon.knowledge.strategy_candidate import _FAMILY_REQUEST_TEXT

        for family in _TEMPLATE_BY_FAMILY:
            with self.subTest(family=family):
                candidate = new_candidate(family, sequence=1, now=NOW)
                self.assertEqual(
                    render_candidate_request_text(candidate, "005930"),
                    f"005930 {_FAMILY_REQUEST_TEXT[family]}",
                )


# ---------------------------------------------------------------------------
# GAP 3 - mission compatibility consults engine supportedness
# ---------------------------------------------------------------------------
def _mission(candidates=(), active_candidate_id=None, strategy_family="short_term_daytrade"):
    return ResearchMission(
        mission_id="research-mission:compat-test",
        market="KR", universe_scope=MissionUniverseScope.MARKET_WIDE, symbols=(),
        exchanges=DEFAULT_KR_EXCHANGES, strategy_family=strategy_family,
        improve_return=True, improve_safety=True, baseline_comparison="registered_strategy",
        target_promotion_ready_candidates=3, current_promotion_ready_candidates=0,
        promotion_ready_candidates=(), explored_symbols=(), status=MissionStatus.ACTIVE,
        blocked_reason=None, cycles_completed=1, created_at=NOW, updated_at=NOW,
        originating_request="test", candidates=tuple(candidates), active_candidate_id=active_candidate_id,
    )


class MissionCompatibilityConsultsEngineSupportednessTests(unittest.TestCase):
    def test_mission_with_a_supported_active_candidate_stays_compatible(self) -> None:
        cand = new_candidate("breakout_standard", sequence=1, now=NOW)
        mission = _mission(candidates=(cand.to_json(),), active_candidate_id=cand.candidate_id)
        self.assertTrue(is_mission_compatible_with_request(mission, "단타 연구 계속해줘"))

    def test_mission_with_an_engine_unsupported_active_candidate_is_incompatible(self) -> None:
        from dataclasses import replace

        cand = new_candidate("breakout_standard", sequence=1, now=NOW)
        corrupted = replace(cand, spec_rules={
            "entry": {**dict(cand.spec_rules["entry"]), "rsi_below": {"value": 30, "provenance": "research_candidate"}},
            "exit": dict(cand.spec_rules["exit"]),
            "filters": dict(cand.spec_rules["filters"]),
        })
        mission = _mission(candidates=(corrupted.to_json(),), active_candidate_id=corrupted.candidate_id)
        self.assertFalse(is_mission_compatible_with_request(mission, "단타 연구 계속해줘"))

    def test_mission_with_no_candidate_yet_keeps_family_market_semantics(self) -> None:
        mission = _mission(candidates=(), active_candidate_id=None)
        # No spec knowable -> unchanged: compatible with a scope-less request,
        # incompatible only when the text explicitly contradicts family/market.
        self.assertTrue(is_mission_compatible_with_request(mission, "단타 연구 계속해줘"))
        self.assertFalse(is_mission_compatible_with_request(mission, "스윙 연구 계속해줘"))

    def test_unreconstructable_active_candidate_spec_fails_closed(self) -> None:
        cand = new_candidate("breakout_standard", sequence=1, now=NOW)
        bad_json = cand.to_json()
        bad_json["spec_rules"] = {"entry": {"breakout_lookback": {"value": None, "provenance": "research_candidate"}}, "exit": {}, "filters": {}}
        mission = _mission(candidates=(bad_json,), active_candidate_id=cand.candidate_id)
        self.assertFalse(is_mission_compatible_with_request(mission, "단타 연구 계속해줘"))


if __name__ == "__main__":
    unittest.main()
