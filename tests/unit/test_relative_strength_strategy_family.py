"""feature/relative-strength-strategy-family (Research Brain wiring, A5).

PR #190 gave RuleBasedBacktestEngine a cross-symbol relative-strength
filter (relative_strength_min). This wires it into a research family,
``breakout_relative_strength`` - the standard 20-day breakout gated so a
position only opens when the traded symbol's 20-bar return is at least
the equal-weight benchmark of the OTHER symbols in the dataset.

The critical property this suite pins: the family can only be validated
with a REAL multi-symbol dataset. On a single-symbol dataset the engine
fails CLOSED (no benchmark -> block every entry -> 0 trades) - it never
invents a zero benchmark or a synthetic peer - so a candidate run
through the single-symbol wrapper produces 0 trades and cannot look
"supported" or promotable. With actual peers it does produce trades.
"""

from __future__ import annotations

import datetime
import unittest

from gaon.knowledge.strategy_candidate import (
    NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES,
    RELATIVE_STRENGTH_STRATEGY_FAMILY_TEMPLATES,
    build_candidate_spec,
    new_candidate,
    next_untried_family,
)
from gaon.research.krx_real_pipeline import (
    RULE_BASED_BACKTEST_CAPABILITIES,
    RuleBasedBacktestEngine,
    candidate_spec_from_rules_json,
    default_execution_assumptions,
)
from gaon.research.real_research import MarketBar, MarketDataMetadata, MarketDataset, MarketSymbol

NOW = "2026-09-06T00:00:00Z"
FAM = "breakout_relative_strength"
PRIMARY = "000001"
PEERS = ("000002", "000003")


def _spec():
    return candidate_spec_from_rules_json(
        new_candidate(FAM, sequence=1, now=NOW).spec_rules, symbol=PRIMARY, created_at=NOW
    )


def _bars(symbol, closes):
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
    return MarketDataset("dataset:rs-family", syms, tuple(bars), meta)


def _run(spec, dataset):
    return RuleBasedBacktestEngine().run("unit-run", spec, dataset, default_execution_assumptions(), generated_at=NOW)


def _rising(rate, n=140):
    return [100.0 * (1.0 + rate) ** i for i in range(n)]


class RelativeStrengthFamilyIsResolvableTests(unittest.TestCase):
    def test_family_is_registered_and_candidate_native(self) -> None:
        self.assertIn(FAM, {t.family for t in RELATIVE_STRENGTH_STRATEGY_FAMILY_TEMPLATES})
        candidate = new_candidate(FAM, sequence=1, now=NOW)
        self.assertEqual(candidate.strategy_family, FAM)
        spec = candidate_spec_from_rules_json(candidate.spec_rules, symbol=PRIMARY, created_at=NOW)
        self.assertIn("breakout_lookback", spec.entry)
        self.assertEqual(spec.filters["relative_strength_min"].value, True)
        self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(spec))
        # exits unchanged.
        self.assertEqual(spec.exit["protective_stop_pct"].value, -5.0)

    def test_fingerprint_is_deterministic_and_distinct_from_plain_breakout(self) -> None:
        a = build_candidate_spec(FAM, created_at=NOW).strategy_family_fingerprint
        b = build_candidate_spec(FAM, created_at="2020-01-01T00:00:00Z").strategy_family_fingerprint
        self.assertEqual(a, b)
        self.assertNotEqual(a, build_candidate_spec("breakout_standard", created_at=NOW).strategy_family_fingerprint)


class SingleSymbolWrapperCannotValidateItTests(unittest.TestCase):
    def test_single_symbol_dataset_yields_zero_trades_and_no_fake_benchmark(self) -> None:
        # exactly the shape the deep single-symbol validation wrapper uses:
        # one symbol only. The relative-strength gate cannot be evaluated,
        # so it fails closed - no synthetic peer, no zero benchmark.
        result = _run(_spec(), _dataset({PRIMARY: _rising(0.02)}))
        self.assertEqual(result.metrics.trade_count, 0)
        # a strategy that makes 0 trades cannot clear the promotion
        # minimum-trade-sample gate - it can never look "promotable" here.
        from gaon.knowledge.strategy_candidate import PROMOTION_MIN_TRADE_SAMPLE

        self.assertLess(result.metrics.trade_count, PROMOTION_MIN_TRADE_SAMPLE)

    def test_with_real_peers_it_can_trade(self) -> None:
        # primary outperforms its peers -> relative strength positive ->
        # the breakout entries are allowed. Proves the 0-trade single-symbol
        # result is a CONTEXT limitation, not a broken family.
        ds = _dataset({PRIMARY: _rising(0.02), PEERS[0]: _rising(0.005), PEERS[1]: _rising(0.005)})
        result = _run(_spec(), ds)
        self.assertGreater(result.metrics.trade_count, 0)
        self.assertEqual(result.status, "completed")


class RelativeStrengthFamilyRotationIsolationTests(unittest.TestCase):
    def test_not_in_breakout_rotation(self) -> None:
        seen: set = set()
        existing: tuple = ()
        for _ in range(20):
            fam = next_untried_family(existing)
            if fam is None:
                break
            seen.add(fam)
            existing = existing + (new_candidate(fam, sequence=len(seen), now=NOW),)
        self.assertNotIn(FAM, seen)

    def test_not_in_the_non_breakout_paradigm_rotation_tuple(self) -> None:
        self.assertNotIn(FAM, {t.family for t in NON_BREAKOUT_STRATEGY_FAMILY_TEMPLATES})


if __name__ == "__main__":
    unittest.main()
