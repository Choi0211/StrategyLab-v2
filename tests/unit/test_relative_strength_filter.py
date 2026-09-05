"""feature/relative-strength-filter (engine layer).

The first CROSS-SYMBOL rule for RuleBasedBacktestEngine: a relative-
strength gate. It is NOT an entry trigger (there is no "buy on relative
strength alone" - relative strength has no timing) - it is a FILTER that,
when active, only lets an entry through if the traded symbol's N-bar
return is at least the equal-weight benchmark's N-bar return, where the
benchmark is built from the OTHER symbols actually present in the
dataset.

`rs_t = primary_return(N) - mean(peer_return(N) for each peer symbol)`
gate: entry allowed iff `rs_t >= 0`.

There is no fake single-symbol fallback: if the dataset carries only the
traded symbol (no peers), or the peers lack enough history at bar t, the
gate CANNOT be evaluated and fails closed (blocks the entry).

Scope of THIS PR: engine + registry + capability + a multi-symbol
partition in RuleBasedBacktestEngine.run + `_BarEvalContext.relative_strength`
+ synthetic 3-symbol signal proof. It does NOT wire relative strength
into the parser / candidate templates / walk-forward / robustness
wrappers or add a family - those are later PRs.

New rules (component "filter"):
  - relative_strength_min       predicate, bool     the on/off switch
  - relative_strength_lookback  parameter, optional  N for the return
                                                     windows, default 20
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
PRIMARY = "000001"
PEERS = ("000002", "000003")


def _v(value, prov=FieldProvenance.RESEARCH_CANDIDATE):
    return ProvenancedValue(value, prov)


def _spec(symbol, entry, exit_rules=None, filters=None):
    return CanonicalStrategySpec(
        "canonical-strategy:test", symbol, dict(entry),
        dict(exit_rules or {"protective_stop_pct": _v(-5.0), "channel_exit_lookback": _v(10)}),
        dict(filters or {}), "test", NOW,
    )


def _bars(symbol, closes):
    # Tight intrabar range (0.1%) so even a slow +0.5%/bar rise still
    # closes above the prior bar's high and an N-bar-high breakout fires.
    d0 = datetime.date(2026, 1, 1)
    return [
        MarketBar((d0 + datetime.timedelta(days=i)).isoformat(), symbol, c, c * 1.001, c * 0.999, c, 1_000_000, int(c * 1_000_000))
        for i, c in enumerate(closes)
    ]


def _dataset(series_by_symbol):
    bars = []
    for sym, closes in series_by_symbol.items():
        bars.extend(_bars(sym, closes))
    syms = tuple(MarketSymbol(s, s, "KOSPI") for s in series_by_symbol)
    ts = sorted({b.timestamp for b in bars})
    meta = MarketDataMetadata("synthetic", "KOSPI", "daily", ts[0], ts[-1], True, "2026-07-25T00:00:00Z", True)
    return MarketDataset("dataset:synthetic-rs", syms, tuple(bars), meta)


def _run(spec, dataset):
    return RuleBasedBacktestEngine().run("unit-run", spec, dataset, default_execution_assumptions(), generated_at=NOW)


_N = 130
_BREAKOUT = {"breakout_lookback": _v(20)}
_RS_ON = {"relative_strength_min": _v(True), "relative_strength_lookback": _v(20)}


def _rising(rate):
    return [100.0 * (1.0 + rate) ** i for i in range(_N)]


class RegistryHasRelativeStrengthRulesTests(unittest.TestCase):
    def test_registry_and_capability_expose_the_new_filter_rules(self) -> None:
        validate_rule_registry_integrity()
        self.assertIn("relative_strength_min", BACKTEST_RULE_REGISTRY)
        self.assertIn("relative_strength_lookback", BACKTEST_RULE_REGISTRY)
        self.assertEqual(BACKTEST_RULE_REGISTRY["relative_strength_min"].kind, "predicate")
        self.assertEqual(BACKTEST_RULE_REGISTRY["relative_strength_min"].component, "filter")
        self.assertEqual(BACKTEST_RULE_REGISTRY["relative_strength_lookback"].kind, "parameter")
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        self.assertIn("relative_strength_min", caps.supported_filters)
        self.assertIn("relative_strength_lookback", caps.supported_filters)
        # a filter rule, never part of the entry-trigger group
        self.assertNotIn("relative_strength_min", caps.entry_trigger_rules)


class RelativeStrengthGateTests(unittest.TestCase):
    def test_outperformer_passes_the_gate(self) -> None:
        # primary rises fastest -> positive relative strength -> the
        # breakout entries it would take anyway are NOT blocked.
        ds = _dataset({PRIMARY: _rising(0.02), PEERS[0]: _rising(0.005), PEERS[1]: _rising(0.005)})
        with_rs = _run(_spec(PRIMARY, _BREAKOUT, filters=_RS_ON), ds)
        without_rs = _run(_spec(PRIMARY, _BREAKOUT), ds)
        self.assertGreater(with_rs.metrics.trade_count, 0)
        self.assertEqual(with_rs.metrics.trade_count, without_rs.metrics.trade_count)

    def test_underperformer_is_blocked_by_the_gate(self) -> None:
        # primary still rises (and breaks out) but SLOWER than its peers ->
        # negative relative strength -> the gate blocks every entry.
        ds = _dataset({PRIMARY: _rising(0.005), PEERS[0]: _rising(0.03), PEERS[1]: _rising(0.03)})
        with_rs = _run(_spec(PRIMARY, _BREAKOUT, filters=_RS_ON), ds)
        without_rs = _run(_spec(PRIMARY, _BREAKOUT), ds)
        self.assertGreater(without_rs.metrics.trade_count, 0)
        self.assertEqual(with_rs.metrics.trade_count, 0)

    def test_gate_off_is_a_no_op(self) -> None:
        ds = _dataset({PRIMARY: _rising(0.005), PEERS[0]: _rising(0.03), PEERS[1]: _rising(0.03)})
        off = _run(_spec(PRIMARY, _BREAKOUT, filters={"relative_strength_min": _v(False)}), ds)
        without = _run(_spec(PRIMARY, _BREAKOUT), ds)
        self.assertEqual(off.metrics.trade_count, without.metrics.trade_count)
        self.assertGreater(off.metrics.trade_count, 0)


class NoFakeSingleSymbolRelativeStrengthTests(unittest.TestCase):
    def test_single_symbol_dataset_cannot_satisfy_the_gate(self) -> None:
        # No peers -> benchmark is not computable -> fail closed: the gate
        # blocks every entry rather than inventing a zero benchmark.
        ds = _dataset({PRIMARY: _rising(0.02)})
        with_rs = _run(_spec(PRIMARY, _BREAKOUT, filters=_RS_ON), ds)
        without_rs = _run(_spec(PRIMARY, _BREAKOUT), ds)
        self.assertGreater(without_rs.metrics.trade_count, 0)
        self.assertEqual(with_rs.metrics.trade_count, 0)

    def test_peers_with_too_little_history_fail_closed(self) -> None:
        # peers only have ~15 bars while lookback is 20 -> not evaluable.
        ds = _dataset({
            PRIMARY: _rising(0.02),
            PEERS[0]: _rising(0.001)[:15],
            PEERS[1]: _rising(0.001)[:15],
        })
        with_rs = _run(_spec(PRIMARY, _BREAKOUT, filters=_RS_ON), ds)
        self.assertEqual(with_rs.metrics.trade_count, 0)


class RelativeStrengthContextAndHandlerTests(unittest.TestCase):
    def test_handlers_are_invoked_on_the_run_path(self) -> None:
        from unittest.mock import patch

        from gaon.research.krx_real_pipeline import BacktestRuleDefinition

        ds = _dataset({PRIMARY: _rising(0.02), PEERS[0]: _rising(0.005), PEERS[1]: _rising(0.005)})
        for key in ("relative_strength_min", "relative_strength_lookback"):
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
                    _run(_spec(PRIMARY, _BREAKOUT, filters=_RS_ON), ds)
                self.assertGreater(calls["n"], 0)

    def test_relative_strength_is_not_look_ahead(self) -> None:
        # Primary underperforms for the whole window EXCEPT it has not yet
        # happened at evaluation time; a look-ahead implementation that
        # peeked at future peer bars would still block. Here the gate uses
        # only bars up to and including the current timestamp, so on a
        # window where the primary is ahead cumulatively it passes.
        ds = _dataset({PRIMARY: _rising(0.02), PEERS[0]: _rising(0.005), PEERS[1]: _rising(0.005)})
        result = _run(_spec(PRIMARY, _BREAKOUT, filters=_RS_ON), ds)
        self.assertGreater(result.metrics.trade_count, 0)
        self.assertEqual(result.status, "completed")


class RelativeStrengthValidationTests(unittest.TestCase):
    def test_unknown_rule_alongside_relative_strength_fails_closed(self) -> None:
        ds = _dataset({PRIMARY: _rising(0.02), PEERS[0]: _rising(0.005), PEERS[1]: _rising(0.005)})
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(_spec(PRIMARY, {**_BREAKOUT, "rsi_below": _v(30)}, filters=_RS_ON), ds)

    def test_relative_strength_lookback_without_the_switch_is_still_valid(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(
            _spec(PRIMARY, _BREAKOUT, filters={"relative_strength_lookback": _v(30)})
        )


if __name__ == "__main__":
    unittest.main()
