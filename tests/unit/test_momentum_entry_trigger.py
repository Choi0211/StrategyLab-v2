"""feature/momentum-entry-trigger (engine layer).

The third entry computation for RuleBasedBacktestEngine, after breakout
(close vs a trailing HIGH) and mean-reversion (close vs a trailing
AVERAGE, on weakness): MOMENTUM - go long when the N-bar rate of change
is at least a threshold, i.e. the close is meaningfully HIGHER than it
was N bars ago. ``close_t / close_{t-N} - 1 >= momentum_min_roc_pct/100``.

This is not a renamed breakout: an N-bar-high breakout needs a NEW high
(close above every intervening bar); an N-bar ROC only needs the close
to have risen enough versus the single bar N periods back, so a series
that keeps climbing without printing a fresh 20-bar high still triggers
momentum but never breakout - and a series that dips below its MA and
partially recovers triggers mean-reversion but not momentum.

Scope of THIS PR: engine + executable rule registry + capability +
fail-closed group validation + synthetic-dataset signal proof. It does
NOT add a `momentum` StrategyFamilyTemplate, a UserStrategyParser path,
a candidate template or autonomous family rotation.

New rules (component "entry"):
  - momentum_roc_lookback  entry_trigger, int      the N for the ROC window
  - momentum_min_roc_pct   parameter, optional %   minimum N-bar return to
                                                   trigger, default 10.0

The entry-trigger GROUP is now {breakout_lookback,
mean_reversion_ma_lookback, momentum_roc_lookback}; a spec carries
exactly one.
"""

from __future__ import annotations

import datetime
import unittest

from gaon.research.krx_real_pipeline import (
    BACKTEST_RULE_REGISTRY,
    RULE_BASED_BACKTEST_CAPABILITIES,
    CanonicalStrategySpec,
    FieldProvenance,
    ProvenancedValue,
    RuleBasedBacktestEngine,
    UnsupportedStrategySpecError,
    default_execution_assumptions,
    validate_rule_registry_integrity,
)
from gaon.research.real_research import MarketBar, MarketDataMetadata, MarketDataset, MarketSymbol

NOW = "2026-07-25T00:00:00Z"


def _v(value, prov=FieldProvenance.RESEARCH_CANDIDATE):
    return ProvenancedValue(value, prov)


def _spec(entry, exit_rules=None, filters=None):
    return CanonicalStrategySpec(
        "canonical-strategy:test", "005930", dict(entry),
        dict(exit_rules or {"protective_stop_pct": _v(-5.0), "channel_exit_lookback": _v(10)}),
        dict(filters or {}), "test", NOW,
    )


def _dataset(closes, volumes=None):
    volumes = volumes or [1000.0] * len(closes)
    d0 = datetime.date(2026, 1, 1)
    bars = tuple(
        MarketBar((d0 + datetime.timedelta(days=i)).isoformat(), "005930", c, c * 1.002, c * 0.998, c, int(v), int(v * c))
        for i, (c, v) in enumerate(zip(closes, volumes))
    )
    meta = MarketDataMetadata("synthetic", "KOSPI", "daily", bars[0].timestamp, bars[-1].timestamp, True, "2026-07-25T00:00:00Z", True)
    return MarketDataset("dataset:synthetic-mom", (MarketSymbol("005930", "S", "KOSPI"),), bars, meta)


def _run(spec, dataset):
    return RuleBasedBacktestEngine().run("unit-run", spec, dataset, default_execution_assumptions(), generated_at=NOW)


_MOM_ENTRY = {"momentum_roc_lookback": _v(20), "momentum_min_roc_pct": _v(8.0)}
# A tiny protective stop turns every entry into its own ~1-bar trade, so
# trade_count tracks the number of bars the entry trigger actually fired -
# which is what these distinctness tests need to compare.
_FAST_EXIT = {"protective_stop_pct": _v(-0.1), "channel_exit_lookback": _v(10)}


def _step_series():
    """Flat, one big step up, then flat again. On the second plateau a
    20-bar ROC is still ~100% (close 20 bars back was on the low shelf)
    for 20 bars, while a 20-bar-high breakout can never re-fire - the
    close only equals, never exceeds, the post-step high."""
    return [100.0] * 71 + [200.0] * 70


class RegistryHasMomentumRulesTests(unittest.TestCase):
    def test_registry_and_capability_expose_the_new_rules(self) -> None:
        validate_rule_registry_integrity()
        self.assertIn("momentum_roc_lookback", BACKTEST_RULE_REGISTRY)
        self.assertIn("momentum_min_roc_pct", BACKTEST_RULE_REGISTRY)
        self.assertEqual(BACKTEST_RULE_REGISTRY["momentum_roc_lookback"].kind, "entry_trigger")
        self.assertEqual(BACKTEST_RULE_REGISTRY["momentum_min_roc_pct"].kind, "parameter")
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        self.assertIn("momentum_roc_lookback", caps.supported_entry_rules)
        self.assertIn("momentum_min_roc_pct", caps.supported_entry_rules)
        self.assertEqual(
            caps.entry_trigger_rules,
            frozenset({"breakout_lookback", "mean_reversion_ma_lookback", "momentum_roc_lookback"}),
        )


class EntryTriggerGroupIsStillExactlyOneTests(unittest.TestCase):
    def test_momentum_only_is_valid(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec(_MOM_ENTRY))
        self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(_spec(_MOM_ENTRY)))

    def test_min_roc_pct_is_optional(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec({"momentum_roc_lookback": _v(20)}))

    def test_momentum_plus_breakout_is_a_conflict(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            RULE_BASED_BACKTEST_CAPABILITIES.validate(
                _spec({"breakout_lookback": _v(20), "momentum_roc_lookback": _v(20)})
            )
        self.assertIn("entry trigger", str(ctx.exception).lower())

    def test_momentum_plus_mean_reversion_is_a_conflict(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            RULE_BASED_BACKTEST_CAPABILITIES.validate(
                _spec({"mean_reversion_ma_lookback": _v(20), "momentum_roc_lookback": _v(20)})
            )

    def test_min_roc_pct_alone_is_not_an_entry_trigger(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec({"momentum_min_roc_pct": _v(8.0)}))
        self.assertIn("entry trigger", str(ctx.exception).lower())


class MomentumIsADistinctComputationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = _dataset(_step_series())

    def test_breakout_makes_exactly_one_trade_the_plateau_blocks_re_entry(self) -> None:
        result = _run(_spec({"breakout_lookback": _v(20)}, exit_rules=_FAST_EXIT), self.dataset)
        # The step breaks out once; on the flat shelf the close only equals
        # the prior high, never exceeds it -> no further breakout entries.
        self.assertEqual(result.metrics.trade_count, 1)

    def test_momentum_re_enters_across_the_plateau_where_breakout_is_dead(self) -> None:
        mom = _run(_spec(_MOM_ENTRY, exit_rules=_FAST_EXIT), self.dataset)
        brk = _run(_spec({"breakout_lookback": _v(20)}, exit_rules=_FAST_EXIT), self.dataset)
        # ROC stays >= 8% for ~20 bars after the step (close 20 bars back
        # was still 100), so momentum keeps re-entering; breakout cannot.
        self.assertGreater(mom.metrics.trade_count, brk.metrics.trade_count)
        self.assertGreaterEqual(mom.metrics.trade_count, 5)
        self.assertEqual(mom.status, "completed")

    def test_momentum_does_not_fire_on_a_flat_series(self) -> None:
        flat = _dataset([100.0] * 120)
        result = _run(_spec(_MOM_ENTRY, exit_rules=_FAST_EXIT), flat)
        self.assertEqual(result.metrics.trade_count, 0)

    def test_momentum_does_not_fire_on_a_declining_series(self) -> None:
        decline = _dataset([200.0 - 0.5 * i for i in range(160)])
        result = _run(_spec(_MOM_ENTRY, exit_rules=_FAST_EXIT), decline)
        self.assertEqual(result.metrics.trade_count, 0)

    def test_higher_threshold_triggers_no_more_often_than_a_lower_one(self) -> None:
        low = _run(_spec({"momentum_roc_lookback": _v(20), "momentum_min_roc_pct": _v(2.0)}, exit_rules=_FAST_EXIT), self.dataset)
        high = _run(_spec({"momentum_roc_lookback": _v(20), "momentum_min_roc_pct": _v(150.0)}, exit_rules=_FAST_EXIT), self.dataset)
        self.assertGreater(low.metrics.trade_count, high.metrics.trade_count)

    def test_momentum_handlers_are_invoked_on_the_run_path(self) -> None:
        from unittest.mock import patch

        from gaon.research.krx_real_pipeline import BacktestRuleDefinition

        for key in ("momentum_roc_lookback", "momentum_min_roc_pct"):
            with self.subTest(rule=key):
                original = BACKTEST_RULE_REGISTRY[key]
                calls = {"n": 0}

                def _spy(*a, _orig=original, **kw):
                    calls["n"] += 1
                    return _orig.handler(*a, **kw)

                spied = BacktestRuleDefinition(
                    original.key, original.component, original.kind, original.required,
                    _spy, original.default, original.lookback,
                )
                with patch.dict(BACKTEST_RULE_REGISTRY, {key: spied}):
                    _run(_spec(_MOM_ENTRY), self.dataset)
                self.assertGreater(calls["n"], 0)


class MomentumPredicatesAndExitStillApplyTests(unittest.TestCase):
    def test_volume_filter_still_gates_a_momentum_entry(self) -> None:
        closes = _step_series()
        vols = [1000.0] * len(closes)
        for i in range(71, len(closes)):
            vols[i] = 1.0  # starve the plateau where momentum wants to re-enter
        dataset = _dataset(closes, vols)
        with_filter = _run(_spec(_MOM_ENTRY, exit_rules=_FAST_EXIT, filters={"volume_gte_ma20": _v(True)}), dataset)
        without = _run(_spec(_MOM_ENTRY, exit_rules=_FAST_EXIT), dataset)
        self.assertLess(with_filter.metrics.trade_count, without.metrics.trade_count)

    def test_protective_stop_still_required(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec(_MOM_ENTRY, exit_rules={"channel_exit_lookback": _v(10)}))


class UnknownRuleStillFailsClosedWithMomentumTests(unittest.TestCase):
    def test_momentum_plus_an_unknown_rule_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(_spec({**_MOM_ENTRY, "rsi_below": _v(30)}), _dataset([100.0] * 120))


if __name__ == "__main__":
    unittest.main()
