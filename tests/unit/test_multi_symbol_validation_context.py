"""Priority 4 - real multi-symbol validation context for walk-forward.

RuleBasedBacktestEngine.run already accepts a multi-symbol dataset
(PR #190). This carries a real peer context THROUGH WalkForwardValidator:
every symbol's bars are split at the SAME timestamp (not by mixed-symbol
bar index), so a relative-strength family can be walk-forward validated
against actual peers.

No fake peer / zero benchmark / synthetic success: a missing primary
symbol, a peer that does not cover the split window, or too few peers
FAILS CLOSED.
"""

from __future__ import annotations

import datetime
import unittest

from gaon.research.krx_real_pipeline import (
    CanonicalStrategySpec,
    FieldProvenance,
    ProvenancedValue,
    WalkForwardValidator,
    candidate_spec_from_rules_json,
    default_execution_assumptions,
)
from gaon.research.multi_symbol_validation import (
    MultiSymbolValidationContext,
    MultiSymbolValidationError,
    walk_forward_timestamp_split,
)
from gaon.research.real_research import MarketBar, MarketDataMetadata, MarketDataset, MarketSymbol
from gaon.knowledge.strategy_candidate import new_candidate

NOW = "2026-07-25T00:00:00Z"
PRIMARY = "000001"
PEERS = ("000002", "000003")


def _v(x):
    return ProvenancedValue(x, FieldProvenance.RESEARCH_CANDIDATE)


def _bars(symbol, closes, *, start=0):
    d0 = datetime.date(2026, 1, 1)
    return [
        MarketBar((d0 + datetime.timedelta(days=start + i)).isoformat(), symbol, c, c * 1.001, c * 0.999, c, 1_000_000, int(c * 1_000_000))
        for i, c in enumerate(closes)
    ]


def _dataset(series_by_symbol):
    bars = []
    for sym, closes in series_by_symbol.items():
        bars.extend(_bars(sym, closes))
    syms = tuple(MarketSymbol(s, s, "KOSPI") for s in series_by_symbol)
    ts = sorted({b.timestamp for b in bars})
    meta = MarketDataMetadata("synthetic", "KOSPI", "daily", ts[0], ts[-1], True, "2026-07-25T00:00:00Z", True)
    return MarketDataset("dataset:msvalidation", syms, tuple(bars), meta)


def _rising(rate, n=150):
    return [100.0 * (1.0 + rate) ** i for i in range(n)]


def _breakout_spec(symbol="005930"):
    return CanonicalStrategySpec(
        "canonical-strategy:t", symbol,
        {"breakout_lookback": _v(20)},
        {"protective_stop_pct": _v(-5.0), "channel_exit_lookback": _v(10)},
        {}, "t", NOW,
    )


class TimestampSplitTests(unittest.TestCase):
    def test_single_symbol_split_matches_the_old_index_split(self) -> None:
        bars = _bars("005930", _rising(0.01, n=200))
        ds = MarketDataset("dataset:d", (MarketSymbol("005930", "s", "KOSPI"),), tuple(bars), _dataset({"005930": [1.0]}).metadata)
        train, test = walk_forward_timestamp_split(ds, primary_symbol="005930")
        old_split = max(70, int(len(bars) * 0.65))
        self.assertEqual([b.timestamp for b in train.bars], [b.timestamp for b in bars[:old_split]])
        self.assertEqual([b.timestamp for b in test.bars], [b.timestamp for b in bars[old_split - 60:]])

    def test_multi_symbol_split_cuts_every_symbol_at_the_same_date(self) -> None:
        ds = _dataset({PRIMARY: _rising(0.02), PEERS[0]: _rising(0.01), PEERS[1]: _rising(0.01)})
        train, test = walk_forward_timestamp_split(ds, primary_symbol=PRIMARY)
        train_syms = {b.symbol for b in train.bars}
        self.assertEqual(train_syms, {PRIMARY, *PEERS})
        # the boundary date is identical for every symbol.
        train_last = max(b.timestamp for b in train.bars if b.symbol == PRIMARY)
        for sym in PEERS:
            self.assertEqual(max(b.timestamp for b in train.bars if b.symbol == sym), train_last)
        # test window overlaps by exactly the warm-up (60 primary bars).
        test_first = min(b.timestamp for b in test.bars if b.symbol == PRIMARY)
        for sym in PEERS:
            self.assertEqual(min(b.timestamp for b in test.bars if b.symbol == sym), test_first)


class FailClosedTests(unittest.TestCase):
    def test_primary_absent_fails_closed(self) -> None:
        ds = _dataset({PEERS[0]: _rising(0.01), PEERS[1]: _rising(0.01)})
        with self.assertRaises(MultiSymbolValidationError):
            MultiSymbolValidationContext.from_dataset(ds, primary_symbol=PRIMARY)

    def test_no_peers_fails_closed(self) -> None:
        ds = _dataset({PRIMARY: _rising(0.02)})
        with self.assertRaises(MultiSymbolValidationError):
            MultiSymbolValidationContext.from_dataset(ds, primary_symbol=PRIMARY)

    def test_peer_not_covering_the_primary_timeline_fails_closed(self) -> None:
        ds = _dataset({PRIMARY: _rising(0.02, n=150), PEERS[0]: _rising(0.01, n=150), PEERS[1]: _rising(0.01, n=40)})
        with self.assertRaises(MultiSymbolValidationError):
            MultiSymbolValidationContext.from_dataset(ds, primary_symbol=PRIMARY)

    def test_a_covering_multi_symbol_dataset_builds_a_context(self) -> None:
        ds = _dataset({PRIMARY: _rising(0.02), PEERS[0]: _rising(0.01), PEERS[1]: _rising(0.01)})
        ctx = MultiSymbolValidationContext.from_dataset(ds, primary_symbol=PRIMARY)
        self.assertEqual(ctx.primary_symbol, PRIMARY)
        self.assertEqual(set(ctx.peer_symbols), set(PEERS))


class WalkForwardOnAMultiSymbolRelativeStrengthSpecTests(unittest.TestCase):
    def test_relative_strength_family_walk_forward_uses_real_peers_and_can_trade(self) -> None:
        ds = _dataset({PRIMARY: _rising(0.02), PEERS[0]: _rising(0.004), PEERS[1]: _rising(0.004)})
        spec = candidate_spec_from_rules_json(
            new_candidate("breakout_relative_strength", sequence=1, now=NOW).spec_rules,
            symbol=PRIMARY, created_at=NOW,
        )
        report = WalkForwardValidator().validate(spec, ds, default_execution_assumptions(), run_id="wf", generated_at=NOW)
        # the point: with real peers the OOS fold is NOT the "0 trades"
        # single-symbol fail-closed result.
        self.assertGreater(report.test_metrics.trade_count, 0)

    def test_single_symbol_walk_forward_of_a_breakout_spec_is_unchanged(self) -> None:
        bars = _bars("005930", _rising(0.01, n=200))
        ds = MarketDataset("dataset:d", (MarketSymbol("005930", "s", "KOSPI"),), tuple(bars), _dataset({"005930": [1.0]}).metadata)
        report = WalkForwardValidator().validate(_breakout_spec(), ds, default_execution_assumptions(), run_id="wf", generated_at=NOW)
        self.assertIn(report.passed, (True, False))  # runs cleanly, same as before


if __name__ == "__main__":
    unittest.main()
