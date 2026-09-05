"""feature/market-regime-filter (engine layer).

A second FILTER for RuleBasedBacktestEngine, after the relative-strength
gate (PR #190): a market-regime gate. When switched on it only lets an
entry through when the traded symbol is in a BULLISH regime - defined,
on closed bars only, as the close being BOTH above its N-bar simple
moving average AND higher than it was N bars ago (price above trend and
trend rising). Anything else is BEARISH (below the MA and falling) or
NEUTRAL.

Regime is a PREFERENCE, not a licence: it can only ever BLOCK an entry
an entry trigger already wanted to take. It never changes position
sizing, the protective stop, or any other guard, and it never forces an
entry.

If the regime cannot be evaluated (not enough history), the gate fails
CLOSED (blocks the entry).

Scope: engine + registry + capability + `_BarEvalContext.market_regime`
+ synthetic signal proof. NOT a parser path / candidate template /
family / research-brain rotation - those are later PRs.

New rules (component "filter"):
  - regime_bullish_only   predicate, bool      the on/off switch
  - regime_ma_lookback    parameter, optional  N for the MA + momentum
                                               window, default 50
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
SYM = "000001"


def _v(value, prov=FieldProvenance.RESEARCH_CANDIDATE):
    return ProvenancedValue(value, prov)


def _spec(entry, exit_rules=None, filters=None):
    return CanonicalStrategySpec(
        "canonical-strategy:test", SYM, dict(entry),
        dict(exit_rules or {"protective_stop_pct": _v(-5.0), "channel_exit_lookback": _v(10)}),
        dict(filters or {}), "test", NOW,
    )


def _dataset(closes):
    d0 = datetime.date(2026, 1, 1)
    bars = tuple(
        MarketBar((d0 + datetime.timedelta(days=i)).isoformat(), SYM, c, c * 1.001, c * 0.999, c, 1_000_000, int(c * 1_000_000))
        for i, c in enumerate(closes)
    )
    meta = MarketDataMetadata("synthetic", "KOSPI", "daily", bars[0].timestamp, bars[-1].timestamp, True, "2026-07-25T00:00:00Z", True)
    return MarketDataset("dataset:synthetic-regime", (MarketSymbol(SYM, SYM, "KOSPI"),), bars, meta)


def _run(spec, dataset):
    return RuleBasedBacktestEngine().run("unit-run", spec, dataset, default_execution_assumptions(), generated_at=NOW)


_BREAKOUT = {"breakout_lookback": _v(20)}
_FAST_EXIT = {"protective_stop_pct": _v(-0.1), "channel_exit_lookback": _v(10)}
_REGIME_ON = {"regime_bullish_only": _v(True), "regime_ma_lookback": _v(50)}


def _rising(rate, n=160):
    return [100.0 * (1.0 + rate) ** i for i in range(n)]


def _rise_then_fall():
    """80 bars up at +0.4%/bar (bullish regime), then 80 bars down at
    -0.4%/bar. A breakout entry trigger fires all through the rising leg;
    once falling, the close drops below its 50-bar MA and below its level
    50 bars back, so the regime turns non-bullish and the gate blocks the
    (few) late breakout attempts."""
    up = [100.0 * 1.004 ** i for i in range(80)]
    peak = up[-1]
    down = [peak * 0.996 ** i for i in range(1, 81)]
    return up + down


class RegistryHasRegimeRulesTests(unittest.TestCase):
    def test_registry_and_capability_expose_the_new_filter_rules(self) -> None:
        validate_rule_registry_integrity()
        self.assertIn("regime_bullish_only", BACKTEST_RULE_REGISTRY)
        self.assertIn("regime_ma_lookback", BACKTEST_RULE_REGISTRY)
        self.assertEqual(BACKTEST_RULE_REGISTRY["regime_bullish_only"].kind, "predicate")
        self.assertEqual(BACKTEST_RULE_REGISTRY["regime_bullish_only"].component, "filter")
        self.assertEqual(BACKTEST_RULE_REGISTRY["regime_ma_lookback"].kind, "parameter")
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        self.assertIn("regime_bullish_only", caps.supported_filters)
        self.assertIn("regime_ma_lookback", caps.supported_filters)
        self.assertNotIn("regime_bullish_only", caps.entry_trigger_rules)


class RegimeGateTests(unittest.TestCase):
    def test_bull_regime_lets_entries_through(self) -> None:
        ds = _dataset(_rising(0.01))
        gated = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT, filters=_REGIME_ON), ds)
        plain = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT), ds)
        self.assertGreater(gated.metrics.trade_count, 0)
        self.assertEqual(gated.metrics.trade_count, plain.metrics.trade_count)

    def test_non_bull_regime_blocks_entries(self) -> None:
        # 100 flat bars at 100, a 20-bar crash to 50, then a 40-bar linear
        # recovery that only reaches 70. The recovery makes a fresh 20-bar
        # high every bar (breakout fires), but every recovery bar's close
        # is still BELOW its level 50 bars ago (which was pre-crash 100 or
        # mid-crash), so the regime is never "bull" and the gate blocks
        # every one of those entries.
        flat = [100.0] * 100
        crash = [100.0 - 2.5 * i for i in range(1, 21)]      # -> 50.0
        recover = [50.0 + 0.5 * i for i in range(1, 41)]     # -> 70.0
        ds = _dataset(flat + crash + recover)
        gated = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT, filters=_REGIME_ON), ds)
        plain = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT), ds)
        self.assertGreater(plain.metrics.trade_count, 0)
        self.assertEqual(gated.metrics.trade_count, 0)

    def test_gate_only_removes_trades_never_adds_them(self) -> None:
        ds = _dataset(_rise_then_fall())
        gated = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT, filters=_REGIME_ON), ds)
        plain = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT), ds)
        self.assertLessEqual(gated.metrics.trade_count, plain.metrics.trade_count)
        self.assertGreater(plain.metrics.trade_count, 0)

    def test_gate_off_is_a_no_op(self) -> None:
        ds = _dataset(_rising(0.01))
        off = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT, filters={"regime_bullish_only": _v(False)}), ds)
        plain = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT), ds)
        self.assertEqual(off.metrics.trade_count, plain.metrics.trade_count)
        self.assertGreater(off.metrics.trade_count, 0)


class RegimeDoesNotTouchRiskTests(unittest.TestCase):
    def test_gate_leaves_position_size_and_stop_identical(self) -> None:
        ds = _dataset(_rising(0.01))
        gated = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT, filters=_REGIME_ON), ds)
        plain = _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT), ds)
        # same entries -> the individual trades must match bar-for-bar.
        self.assertEqual(len(gated.trades), len(plain.trades))
        for g, p in zip(gated.trades, plain.trades):
            self.assertEqual(g.entry_date, p.entry_date)
            self.assertEqual(g.quantity, p.quantity)
            self.assertEqual(g.exit_reason, p.exit_reason)


class RegimeFailClosedAndValidationTests(unittest.TestCase):
    def test_classifier_returns_none_without_enough_history(self) -> None:
        from gaon.research.krx_real_pipeline import _classify_market_regime

        # defence in depth - run()'s warm-up already guarantees a full
        # window, but the classifier still refuses to guess on a short one.
        self.assertIsNone(_classify_market_regime(100.0, tuple(range(10)), 50))
        self.assertIsNone(_classify_market_regime(100.0, (), 50))

    def test_classifier_labels_bull_bear_neutral(self) -> None:
        from gaon.research.krx_real_pipeline import _classify_market_regime

        rising = tuple(90.0 + i for i in range(50))  # 90..139, sma ~114
        self.assertEqual(_classify_market_regime(150.0, rising, 50), "bull")   # above sma, above rising[0]
        falling = tuple(140.0 - i for i in range(50))  # 140..91, sma ~115
        self.assertEqual(_classify_market_regime(80.0, falling, 50), "bear")   # below sma, below falling[0]
        self.assertEqual(_classify_market_regime(120.0, falling, 50), "neutral")  # above sma but below falling[0]

    def test_handlers_are_invoked_on_the_run_path(self) -> None:
        from unittest.mock import patch

        from gaon.research.krx_real_pipeline import BacktestRuleDefinition

        ds = _dataset(_rising(0.01))
        for key in ("regime_bullish_only", "regime_ma_lookback"):
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
                    _run(_spec(_BREAKOUT, exit_rules=_FAST_EXIT, filters=_REGIME_ON), ds)
                self.assertGreater(calls["n"], 0)

    def test_unknown_rule_alongside_regime_fails_closed(self) -> None:
        ds = _dataset(_rising(0.01))
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(_spec({**_BREAKOUT, "rsi_below": _v(30)}, filters=_REGIME_ON), ds)

    def test_regime_lookback_without_the_switch_is_still_valid(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec(_BREAKOUT, filters={"regime_ma_lookback": _v(40)}))


if __name__ == "__main__":
    unittest.main()
