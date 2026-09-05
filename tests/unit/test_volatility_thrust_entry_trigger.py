"""feature/volatility-thrust-entry-trigger (engine layer).

The fourth entry computation for RuleBasedBacktestEngine, after breakout
(PR #186), mean-reversion (PR #187) and momentum (PR #188): a VOLATILITY
THRUST - go long when a single bar's up-move is large RELATIVE TO recent
range, i.e. `close_t - close_{t-1} >= volatility_thrust_k * avg_range(N)`
where `avg_range(N)` is the mean of `high - low` over the last N bars (a
range-based ATR approximation - deterministic, closed-bar, no
prev-close alignment needed).

This is not a renamed breakout / momentum: breakout needs a fresh N-bar
HIGH; momentum needs an N-bar RETURN; a volatility thrust needs one
bar's advance to be a multiple of the recent typical daily range - it
can fire mid-range (no new high) and on the very first strong bar (no
20-bar return yet), and it does NOT fire on a slow grind-up whose daily
moves are all small relative to range.

Scope: engine + executable rule registry + capability + fail-closed
group validation + a new `_BarEvalContext` field (prior highs/lows) +
synthetic-dataset signal proof. NOT a `volatility` StrategyFamilyTemplate
/ parser path / candidate template / autonomous rotation.

New rules (component "entry"):
  - volatility_atr_lookback  entry_trigger, int     the N for avg_range
  - volatility_thrust_k      parameter, optional     multiple of avg_range
                                                     the 1-bar advance must
                                                     exceed, default 1.5
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


def _dataset(bars_hlc, volumes=None):
    """bars_hlc: list of (high, low, close) triples."""
    volumes = volumes or [1000.0] * len(bars_hlc)
    d0 = datetime.date(2026, 1, 1)
    bars = tuple(
        MarketBar((d0 + datetime.timedelta(days=i)).isoformat(), "005930", c, h, low, c, int(vol), int(vol * c))
        for i, ((h, low, c), vol) in enumerate(zip(bars_hlc, volumes))
    )
    meta = MarketDataMetadata("synthetic", "KOSPI", "daily", bars[0].timestamp, bars[-1].timestamp, True, "2026-07-25T00:00:00Z", True)
    return MarketDataset("dataset:synthetic-vol", (MarketSymbol("005930", "S", "KOSPI"),), bars, meta)


_THRUST_BARS = (90, 114)  # both sit at i % 12 == 6, mid-ramp of the sawtooth


def _channel_with_thrust_spikes():
    """150 bars of a tight sawtooth: a +0.9/bar ramp for 12 bars then a
    reset back down. Every bar's range is 2.0 (close +/- 1.0), so
    avg_range(20) is 2.0 and a 1.5x thrust needs a >= 3.0 close-to-close
    advance - the +0.9 ramp bars never clear that and the price never
    leaves the ~[100, 111] channel, so an N-bar-high breakout essentially
    never fires. On bars 90 and 114 a single bar jumps ~+5.1 from
    mid-ramp straight to 110.5 - a genuine volatility thrust (>= 3.0)
    that still stays BELOW the trailing 20-bar high (~110.9), so breakout
    stays silent while the thrust fires."""
    rows = []
    for i in range(150):
        close = 100.0 + (i % 12) * 0.9
        if i in _THRUST_BARS:
            close = 110.5
        rows.append((close + 1.0, close - 1.0, close))
    return rows


def _run(spec, dataset):
    return RuleBasedBacktestEngine().run("unit-run", spec, dataset, default_execution_assumptions(), generated_at=NOW)


_VOL_ENTRY = {"volatility_atr_lookback": _v(20), "volatility_thrust_k": _v(1.5)}
_FAST_EXIT = {"protective_stop_pct": _v(-0.1), "channel_exit_lookback": _v(10)}


class RegistryHasVolatilityRulesTests(unittest.TestCase):
    def test_registry_and_capability_expose_the_new_rules(self) -> None:
        validate_rule_registry_integrity()
        self.assertIn("volatility_atr_lookback", BACKTEST_RULE_REGISTRY)
        self.assertIn("volatility_thrust_k", BACKTEST_RULE_REGISTRY)
        self.assertEqual(BACKTEST_RULE_REGISTRY["volatility_atr_lookback"].kind, "entry_trigger")
        self.assertEqual(BACKTEST_RULE_REGISTRY["volatility_thrust_k"].kind, "parameter")
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        self.assertIn("volatility_atr_lookback", caps.supported_entry_rules)
        self.assertIn("volatility_thrust_k", caps.supported_entry_rules)
        self.assertLessEqual(
            frozenset({"breakout_lookback", "mean_reversion_ma_lookback", "momentum_roc_lookback", "volatility_atr_lookback"}),
            caps.entry_trigger_rules,
        )


class EntryTriggerGroupStillExactlyOneTests(unittest.TestCase):
    def test_volatility_only_is_valid(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec(_VOL_ENTRY))
        self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(_spec(_VOL_ENTRY)))

    def test_thrust_k_is_optional(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec({"volatility_atr_lookback": _v(20)}))

    def test_volatility_plus_momentum_is_a_conflict(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            RULE_BASED_BACKTEST_CAPABILITIES.validate(
                _spec({"volatility_atr_lookback": _v(20), "momentum_roc_lookback": _v(20)})
            )
        self.assertIn("entry trigger", str(ctx.exception).lower())

    def test_thrust_k_alone_is_not_an_entry_trigger(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec({"volatility_thrust_k": _v(1.5)}))
        self.assertIn("entry trigger", str(ctx.exception).lower())


class VolatilityThrustIsADistinctComputationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.dataset = _dataset(_channel_with_thrust_spikes())

    def test_thrust_fires_on_the_spike_bars_the_ramp_never_produces(self) -> None:
        result = _run(_spec(_VOL_ENTRY, exit_rules=_FAST_EXIT), self.dataset)
        self.assertGreaterEqual(result.metrics.trade_count, 1)
        self.assertEqual(result.status, "completed")
        # first entry is the first spike bar (index 90) or the next eligible bar
        self.assertGreaterEqual(result.trades[0].entry_date, self.dataset.bars[_THRUST_BARS[0]].timestamp)

    def test_breakout_stays_silent_where_the_thrust_fires(self) -> None:
        thr = _run(_spec(_VOL_ENTRY, exit_rules=_FAST_EXIT), self.dataset)
        brk = _run(_spec({"breakout_lookback": _v(20)}, exit_rules=_FAST_EXIT), self.dataset)
        # The spikes jump within the channel, never above the trailing
        # 20-bar high, so breakout never triggers; the thrust does.
        self.assertGreaterEqual(thr.metrics.trade_count, 2)
        self.assertEqual(brk.metrics.trade_count, 0)

    def test_no_thrust_on_a_uniformly_narrow_series(self) -> None:
        rows = [(100.0 + 0.25, 100.0 - 0.25, 100.0 + (0.05 if i % 2 else -0.05)) for i in range(160)]
        result = _run(_spec(_VOL_ENTRY, exit_rules=_FAST_EXIT), _dataset(rows))
        self.assertEqual(result.metrics.trade_count, 0)

    def test_higher_k_triggers_no_more_often_than_lower_k(self) -> None:
        low = _run(_spec({"volatility_atr_lookback": _v(20), "volatility_thrust_k": _v(0.5)}, exit_rules=_FAST_EXIT), self.dataset)
        high = _run(_spec({"volatility_atr_lookback": _v(20), "volatility_thrust_k": _v(20.0)}, exit_rules=_FAST_EXIT), self.dataset)
        self.assertGreaterEqual(low.metrics.trade_count, high.metrics.trade_count)

    def test_handlers_are_invoked_on_the_run_path(self) -> None:
        from unittest.mock import patch

        from gaon.research.krx_real_pipeline import BacktestRuleDefinition

        for key in ("volatility_atr_lookback", "volatility_thrust_k"):
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
                    _run(_spec(_VOL_ENTRY, exit_rules=_FAST_EXIT), self.dataset)
                self.assertGreater(calls["n"], 0)


class VolatilityPredicatesAndExitStillApplyTests(unittest.TestCase):
    def test_protective_stop_still_required(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec(_VOL_ENTRY, exit_rules={"channel_exit_lookback": _v(10)}))

    def test_unknown_rule_alongside_volatility_fails_closed(self) -> None:
        rows = [(100.0 + 0.25, 100.0 - 0.25, 100.0) for _ in range(120)]
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(_spec({**_VOL_ENTRY, "rsi_below": _v(30)}), _dataset(rows))


if __name__ == "__main__":
    unittest.main()
