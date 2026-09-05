"""refactor/backtest-capabilities-executable-registry.

PR #184 made RuleBasedBacktestEngine fail closed on rule keys it does not
read, but left two residual architectural gaps its own report called out:

1. The declared "supported" rule sets
   (RULE_BASED_ENGINE_SUPPORTED_ENTRY_RULES / ..._EXIT_RULES / ..._FILTERS
   and RuleBasedBacktestCapabilities' fields) and the actual rule
   evaluation in RuleBasedBacktestEngine.run were two INDEPENDENT
   hand-maintained things. A rule could be declared "supported" while the
   engine has no code that executes it - a silent divergence identical in
   effect to the pre-#184 silent-drop bug.

2. The optional boolean predicate rules close_gt_ma20 / ma20_gt_ma60 /
   volume_gte_ma20 were applied based on KEY PRESENCE only: run() does
   `not strategy.entry.get("close_gt_ma20")`, and .get() returns the
   truthy ProvenancedValue OBJECT, so `.value == False` still enforced
   the predicate.

This module reproduces both, then pins the fixed behaviour: supported
rules are DERIVED from an executable rule registry (one source of truth),
a declared-but-unimplemented rule is structurally impossible, every
registered predicate is actually invoked on the run path, and a schema
boolean False disables its predicate.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from gaon.knowledge.strategy_candidate import (
    _FAMILY_REQUEST_TEXT,
    _TEMPLATE_BY_FAMILY,
    build_candidate_spec,
)
from gaon.research import krx_real_pipeline as krx
from gaon.research.krx_real_pipeline import (
    BACKTEST_RULE_REGISTRY,
    RULE_BASED_BACKTEST_CAPABILITIES,
    BacktestRuleDefinition,
    CanonicalStrategySpec,
    FieldProvenance,
    KRXFixtureMarketDataProvider,
    ProvenancedValue,
    RuleBasedBacktestCapabilities,
    RuleBasedBacktestEngine,
    UnsupportedStrategySpecError,
    default_execution_assumptions,
    validate_rule_registry_integrity,
)

NOW = "2026-07-25T00:00:00Z"


def _v(value):
    return ProvenancedValue(value, FieldProvenance.RESEARCH_CANDIDATE)


def _spec(entry, exit_rules, filters):
    return CanonicalStrategySpec("canonical-strategy:test", "005930", dict(entry), dict(exit_rules), dict(filters), "test", NOW)


_ENTRY = {"breakout_lookback": _v(20)}
_EXIT = {"protective_stop_pct": _v(-5.0), "channel_exit_lookback": _v(10)}


def _dataset():
    return KRXFixtureMarketDataProvider().fetch_bars("005930", start_date="2026-01-01", end_date="2026-07-10")


_DATASET = _dataset()


def _run(spec):
    return RuleBasedBacktestEngine().run("unit-run", spec, _DATASET, default_execution_assumptions(), generated_at=NOW)


# ---------------------------------------------------------------------------
# PART 3 / 6 / 15 - Single source of truth
# ---------------------------------------------------------------------------
class SupportedRulesComeFromExecutableRegistryTests(unittest.TestCase):
    def test_capability_supported_sets_are_exactly_the_registry_keys(self) -> None:
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        entry = {k for k, d in BACKTEST_RULE_REGISTRY.items() if d.component == "entry"}
        exit_ = {k for k, d in BACKTEST_RULE_REGISTRY.items() if d.component == "exit"}
        filt = {k for k, d in BACKTEST_RULE_REGISTRY.items() if d.component == "filter"}
        self.assertEqual(set(caps.supported_entry_rules), entry)
        self.assertEqual(set(caps.supported_exit_rules), exit_)
        self.assertEqual(set(caps.supported_filters), filt)
        self.assertEqual(
            set(caps.required_entry_rules),
            {k for k, d in BACKTEST_RULE_REGISTRY.items() if d.component == "entry" and d.required},
        )
        self.assertEqual(
            set(caps.required_exit_rules),
            {k for k, d in BACKTEST_RULE_REGISTRY.items() if d.component == "exit" and d.required},
        )

    def test_every_registered_rule_has_a_callable_handler(self) -> None:
        for key, definition in BACKTEST_RULE_REGISTRY.items():
            with self.subTest(rule=key):
                self.assertTrue(callable(definition.handler))
                self.assertIn(definition.component, {"entry", "exit", "filter"})
                # "entry_trigger" is the rule that decides whether this bar
                # opens a position (breakout_lookback /
                # mean_reversion_ma_lookback / momentum_roc_lookback).
                self.assertIn(definition.kind, {"parameter", "predicate", "entry_trigger"})
                if definition.kind == "entry_trigger":
                    self.assertTrue(callable(definition.lookback))

    def test_capabilities_has_no_hand_declared_rule_set_constructor_argument(self) -> None:
        # The old escape hatch - constructing capabilities with an
        # arbitrary supported_* set decoupled from the registry - must not
        # exist any more.
        with self.assertRaises(TypeError):
            RuleBasedBacktestCapabilities(supported_entry_rules=frozenset({"whatever"}))  # type: ignore[call-arg]


class DeclaredButUnimplementedRuleImpossibleTests(unittest.TestCase):
    """PART 2 + PART 15: a rule cannot be 'supported' without an executable
    handler - either the state cannot be constructed, or the integrity
    invariant rejects it immediately."""

    def test_registering_a_rule_without_a_handler_fails_the_integrity_invariant(self) -> None:
        broken = BACKTEST_RULE_REGISTRY | {
            "future_test_rule": BacktestRuleDefinition(
                key="future_test_rule", component="entry", kind="predicate", required=False, handler=None  # type: ignore[arg-type]
            )
        }
        with patch.object(krx, "BACKTEST_RULE_REGISTRY", broken):
            with self.assertRaises(RuntimeError):
                validate_rule_registry_integrity()

    def test_a_capability_supported_set_cannot_name_a_rule_absent_from_the_registry(self) -> None:
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        for key in (*caps.supported_entry_rules, *caps.supported_exit_rules, *caps.supported_filters):
            self.assertIn(key, BACKTEST_RULE_REGISTRY)

    def test_adding_an_evaluator_to_the_registry_makes_it_appear_in_capabilities_one_direction_only(self) -> None:
        extra = BACKTEST_RULE_REGISTRY | {
            "extra_filter": BacktestRuleDefinition(
                key="extra_filter", component="filter", kind="predicate", required=False,
                handler=lambda active, ctx: (not active) or True,
            )
        }
        with patch.object(krx, "BACKTEST_RULE_REGISTRY", extra):
            self.assertIn("extra_filter", RULE_BASED_BACKTEST_CAPABILITIES.supported_filters)


class RegistryIntegrityTests(unittest.TestCase):
    def test_production_invariant_holds_for_the_shipped_registry(self) -> None:
        validate_rule_registry_integrity()  # must not raise

    def test_duplicate_key_is_rejected(self) -> None:
        dup = (*krx.BACKTEST_RULE_DEFINITIONS, krx.BACKTEST_RULE_DEFINITIONS[0])
        with patch.object(krx, "BACKTEST_RULE_DEFINITIONS", dup):
            with self.assertRaises(RuntimeError):
                validate_rule_registry_integrity()

    def test_required_parameter_rule_must_not_carry_a_default(self) -> None:
        bad = tuple(
            BacktestRuleDefinition(d.key, d.component, d.kind, d.required, d.handler, default=99)
            if d.key == "breakout_lookback" else d
            for d in krx.BACKTEST_RULE_DEFINITIONS
        )
        with patch.object(krx, "BACKTEST_RULE_DEFINITIONS", bad), patch.object(
            krx, "BACKTEST_RULE_REGISTRY", {d.key: d for d in bad}
        ):
            with self.assertRaises(RuntimeError):
                validate_rule_registry_integrity()


# ---------------------------------------------------------------------------
# PART 8 - evaluator execution completeness
# ---------------------------------------------------------------------------
class EveryRegisteredPredicateIsExecutedTests(unittest.TestCase):
    def test_each_registered_predicate_handler_is_invoked_on_the_run_path(self) -> None:
        predicate_keys = [k for k, d in BACKTEST_RULE_REGISTRY.items() if d.kind == "predicate"]
        self.assertTrue(predicate_keys)
        spec = _spec({**_ENTRY, "close_gt_ma20": _v(True), "ma20_gt_ma60": _v(True)}, _EXIT, {"volume_gte_ma20": _v(True)})
        for key in predicate_keys:
            with self.subTest(rule=key):
                with patch.dict(BACKTEST_RULE_REGISTRY, {}, clear=False):
                    original = BACKTEST_RULE_REGISTRY[key]
                    calls = {"n": 0}

                    def _spy(active, ctx, _orig=original):
                        calls["n"] += 1
                        return _orig.handler(active, ctx)

                    spied = BacktestRuleDefinition(original.key, original.component, original.kind, original.required, _spy)
                    with patch.dict(BACKTEST_RULE_REGISTRY, {key: spied}):
                        _run(spec)
                    self.assertGreater(calls["n"], 0)

    def test_each_registered_parameter_handler_is_consumed_on_the_run_path(self) -> None:
        parameter_keys = [k for k, d in BACKTEST_RULE_REGISTRY.items() if d.kind == "parameter"]
        # A parameter key is consumed only on a run whose spec actually
        # activates it - breakout params on a breakout spec, mean-reversion
        # params on a mean-reversion spec, momentum params on a momentum
        # spec. A new param key with no entry here fails loudly (KeyError),
        # forcing the author to prove it is exercised.
        mr_spec = _spec(
            {"mean_reversion_ma_lookback": _v(20), "mean_reversion_band_pct": _v(5.0)}, _EXIT, {}
        )
        mom_spec = _spec(
            {"momentum_roc_lookback": _v(20), "momentum_min_roc_pct": _v(10.0)}, _EXIT, {}
        )
        spec_by_key = {
            "protective_stop_pct": _spec(_ENTRY, _EXIT, {}),
            "channel_exit_lookback": _spec(_ENTRY, _EXIT, {}),
            "mean_reversion_band_pct": mr_spec,
            "momentum_min_roc_pct": mom_spec,
        }
        for key in parameter_keys:
            with self.subTest(rule=key):
                spec = spec_by_key[key]
                original = BACKTEST_RULE_REGISTRY[key]
                calls = {"n": 0}

                def _spy(s, _orig=original):
                    calls["n"] += 1
                    return _orig.handler(s)

                spied = BacktestRuleDefinition(original.key, original.component, original.kind, original.required, _spy, original.default, original.lookback)
                with patch.dict(BACKTEST_RULE_REGISTRY, {key: spied}):
                    _run(spec)
                self.assertGreater(calls["n"], 0)

    def test_each_registered_entry_trigger_handler_and_lookback_are_consumed_on_the_run_path(self) -> None:
        trigger_specs = {
            "breakout_lookback": _spec(_ENTRY, _EXIT, {}),
            "mean_reversion_ma_lookback": _spec({"mean_reversion_ma_lookback": _v(20)}, _EXIT, {}),
            "momentum_roc_lookback": _spec({"momentum_roc_lookback": _v(20)}, _EXIT, {}),
        }
        for key, spec in trigger_specs.items():
            with self.subTest(rule=key):
                original = BACKTEST_RULE_REGISTRY[key]
                self.assertEqual(original.kind, "entry_trigger")
                calls = {"handler": 0, "lookback": 0}

                def _handler_spy(s, ctx, _orig=original):
                    calls["handler"] += 1
                    return _orig.handler(s, ctx)

                def _lookback_spy(s, _orig=original):
                    calls["lookback"] += 1
                    return _orig.lookback(s)

                spied = BacktestRuleDefinition(
                    original.key, original.component, original.kind, original.required,
                    _handler_spy, original.default, _lookback_spy,
                )
                with patch.dict(BACKTEST_RULE_REGISTRY, {key: spied}):
                    _run(spec)
                self.assertGreater(calls["handler"], 0)
                self.assertGreater(calls["lookback"], 0)


# ---------------------------------------------------------------------------
# PART 5 - boolean False semantics
# ---------------------------------------------------------------------------
def _synthetic_dataset(closes, volumes):
    import datetime as _dt

    from gaon.research.real_research import MarketBar, MarketDataMetadata, MarketDataset, MarketSymbol

    d0 = _dt.date(2026, 1, 1)
    bars = tuple(
        MarketBar((d0 + _dt.timedelta(days=i)).isoformat(), "005930", c, c * 1.002, c * 0.998, c, int(vol), int(vol * c))
        for i, (c, vol) in enumerate(zip(closes, volumes))
    )
    meta = MarketDataMetadata("synthetic", "KOSPI", "daily", bars[0].timestamp, bars[-1].timestamp, True, "2026-07-25T00:00:00Z", True)
    return MarketDataset("dataset:synthetic-predicate", (MarketSymbol("005930", "S", "KOSPI"),), bars, meta)


def _run_on(dataset, spec):
    return RuleBasedBacktestEngine().run("unit-run", spec, dataset, default_execution_assumptions(), generated_at=NOW)


class BooleanFalseDisablesPredicateTests(unittest.TestCase):
    """PART 5: a schema boolean value of False must DISABLE its predicate
    (== rule omitted). Pre-refactor run() checked KEY PRESENCE only, so
    close_gt_ma20 / ma20_gt_ma60 / volume_gte_ma20 == False still enforced
    the predicate (behaved identically to True) - reproduced here on
    synthetic data where each predicate genuinely blocks the one breakout.
    """

    def setUp(self) -> None:
        # Dataset A: lookback=20. A downtrend (ma20 < ma60 at the breakout)
        # and a low-volume breakout bar - so ma20_gt_ma60 and
        # volume_gte_ma20, when active, block the only entry.
        closes_a = [200.0] * 41 + [200.0 - (100.0 * (i + 1) / 35) for i in range(35)]
        prior_high_20 = max(c * 1.005 for c in closes_a[56:76])
        spike_a = prior_high_20 + 1.0
        closes_a = closes_a + [spike_a] + [spike_a - 2] * 13
        vols_a = [1000.0] * len(closes_a)
        vols_a[76] = 1.0
        self.dataset_a = _synthetic_dataset(closes_a, vols_a)
        self.entry20 = {"breakout_lookback": _v(20)}

        # Dataset B: lookback=10. A sharp drop then a small breakout still
        # far below ma20 - so close_gt_ma20, when active, blocks the entry.
        closes_b = [300.0] * 56 + [100.0] * 15 + [101.0] + [100.5] * 18
        self.dataset_b = _synthetic_dataset(closes_b, [1000.0] * len(closes_b))
        self.entry10 = {"breakout_lookback": _v(10)}

    def _keys(self, dataset, entry, **entry_over):
        return [
            (t.entry_date, t.exit_date, t.exit_reason)
            for t in _run_on(dataset, _spec({**entry, **entry_over}, _EXIT, {})).trades
        ]

    def _keys_filter(self, dataset, entry, **filters):
        return [
            (t.entry_date, t.exit_date, t.exit_reason)
            for t in _run_on(dataset, _spec(entry, _EXIT, filters)).trades
        ]

    def test_close_gt_ma20_false_equals_omitted_and_true_blocks(self) -> None:
        omitted = self._keys(self.dataset_b, self.entry10)
        false_ = self._keys(self.dataset_b, self.entry10, close_gt_ma20=_v(False))
        true_ = self._keys(self.dataset_b, self.entry10, close_gt_ma20=_v(True))
        self.assertEqual(false_, omitted)
        self.assertEqual(len(omitted), 1)
        self.assertEqual(true_, [])

    def test_ma20_gt_ma60_false_equals_omitted_and_true_blocks(self) -> None:
        omitted = self._keys(self.dataset_a, self.entry20)
        false_ = self._keys(self.dataset_a, self.entry20, ma20_gt_ma60=_v(False))
        true_ = self._keys(self.dataset_a, self.entry20, ma20_gt_ma60=_v(True))
        self.assertEqual(false_, omitted)
        self.assertEqual(len(omitted), 1)
        self.assertEqual(true_, [])

    def test_volume_gte_ma20_false_equals_omitted_and_true_blocks(self) -> None:
        omitted = self._keys_filter(self.dataset_a, self.entry20)
        false_ = self._keys_filter(self.dataset_a, self.entry20, volume_gte_ma20=_v(False))
        true_ = self._keys_filter(self.dataset_a, self.entry20, volume_gte_ma20=_v(True))
        self.assertEqual(false_, omitted)
        self.assertEqual(len(omitted), 1)
        self.assertEqual(true_, [])

    def test_boolean_true_behaviour_is_unchanged_for_a_normal_dataset(self) -> None:
        # On the standard fixture the shipped families (all use True) keep
        # exactly their pre-refactor trades - see the golden test - and a
        # True predicate is never LESS strict than omitting it.
        strict = _run(_spec({**_ENTRY, "close_gt_ma20": _v(True), "ma20_gt_ma60": _v(True)}, _EXIT, {"volume_gte_ma20": _v(True)}))
        loose = _run(_spec(_ENTRY, _EXIT, {}))
        self.assertLessEqual(strict.metrics.trade_count, loose.metrics.trade_count)


# ---------------------------------------------------------------------------
# PART 7 / 12 - fail-closed and existing-family regressions preserved
# ---------------------------------------------------------------------------
class FailClosedPreservedTests(unittest.TestCase):
    def test_unknown_rule_still_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(_spec({**_ENTRY, "rsi_below": _v(30)}, _EXIT, {}))

    def test_partial_support_still_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(_spec({**_ENTRY, "rsi_below": _v(30)}, {**_EXIT, "trailing_atr_mult": _v(2.0)}, {"adx_gte": _v(25)}))

    def test_missing_required_rule_still_fails_closed_as_a_domain_error(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            _run(_spec({"close_gt_ma20": _v(True)}, _EXIT, {}))
        self.assertNotIsInstance(ctx.exception, KeyError)


class AllExistingFamiliesAcceptedTests(unittest.TestCase):
    def test_every_shipped_family_still_validates_and_runs(self) -> None:
        self.assertEqual(len(_TEMPLATE_BY_FAMILY), 16)
        for family in _TEMPLATE_BY_FAMILY:
            with self.subTest(family=family):
                spec = build_candidate_spec(family, created_at=NOW)
                self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))
                result = _run(spec)
                self.assertEqual(result.status, "completed")

    def test_every_family_request_text_parse_still_validates(self) -> None:
        from gaon.research.krx_real_pipeline import UserStrategyParser

        parser = UserStrategyParser()
        for family, text in _FAMILY_REQUEST_TEXT.items():
            with self.subTest(family=family):
                spec = parser.parse(f"005930 {text}", symbol="005930", created_at=NOW)
                self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))


class ExistingFamilyBehaviorUnchangedTests(unittest.TestCase):
    """PART 12: for every shipped family the backtest must be identical to
    the PRE-refactor engine. Compared against
    test_backtest_rule_registry_golden.json captured from unmodified main
    (a569a3f). Deterministic fields only - RealBacktestResult.fingerprint /
    result_id embed build_candidate_spec's random uuid4 spec_id, so those
    are intentionally NOT part of the golden; strategy_family_fingerprint
    (rules-only, deterministic), the full trade list and every performance
    metric are."""

    def test_result_matches_pre_refactor_golden(self) -> None:
        import json
        import pathlib

        golden = json.loads(pathlib.Path(__file__).with_name("test_backtest_rule_registry_golden.json").read_text(encoding="utf-8"))
        self.assertEqual(set(golden), set(_TEMPLATE_BY_FAMILY))
        for family in _TEMPLATE_BY_FAMILY:
            with self.subTest(family=family):
                spec = build_candidate_spec(family, created_at=NOW)
                result = _run(spec)
                g = golden[family]
                self.assertEqual(spec.strategy_family_fingerprint, g["strategy_family_fingerprint"])
                self.assertEqual(result.metrics.trade_count, g["trade_count"])
                self.assertEqual(result.metrics.to_json(), g["metrics"])
                self.assertEqual(
                    [[t.entry_date, t.exit_date, round(t.entry_price, 4), round(t.exit_price, 4), t.quantity, round(t.return_pct, 6), t.exit_reason] for t in result.trades],
                    g["trades"],
                )
                self.assertEqual(result.equity_curve[-1] if result.equity_curve else None, g["equity_curve_last"])


class ValidationOccursBeforeExecutionTests(unittest.TestCase):
    def test_no_rule_handler_runs_when_the_spec_is_unsupported(self) -> None:
        from gaon.research.krx_real_pipeline import PerformanceMetricsCalculator

        with patch.object(PerformanceMetricsCalculator, "calculate", autospec=True) as metrics:
            with self.assertRaises(UnsupportedStrategySpecError):
                _run(_spec({**_ENTRY, "rsi_below": _v(30)}, _EXIT, {}))
        metrics.assert_not_called()


if __name__ == "__main__":
    unittest.main()
