"""feature/mean-reversion-capability (engine layer).

The first genuinely non-breakout entry computation for
RuleBasedBacktestEngine: a MEAN-REVERSION dip entry - go long when the
close falls a configurable band below its N-day simple moving average.
This is NOT a renamed breakout rule; ``bar.close > highest_high(n)`` and
``bar.close <= sma(n) * (1 - band)`` are different signals computed from
different quantities.

Scope of THIS PR: the engine + executable rule registry + capability +
fail-closed validation + synthetic-dataset signal proof. It does NOT add
a `mean_reversion` StrategyFamilyTemplate, a UserStrategyParser path, a
candidate template or autonomous family rotation - those are a separate
follow-up.

New rules (all component "entry"):
  - mean_reversion_ma_lookback  (entry_trigger, int)      the N for the SMA
  - mean_reversion_band_pct     (parameter, optional %)   how far below the
                                                          SMA to trigger,
                                                          default 5.0 (=5%)

`breakout_lookback` and `mean_reversion_ma_lookback` are the two members
of the "entry trigger" group: a spec must carry EXACTLY ONE of them.
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
    return MarketDataset("dataset:synthetic-mr", (MarketSymbol("005930", "S", "KOSPI"),), bars, meta)


def _run(spec, dataset):
    return RuleBasedBacktestEngine().run("unit-run", spec, dataset, default_execution_assumptions(), generated_at=NOW)


_MR_ENTRY = {"mean_reversion_ma_lookback": _v(20), "mean_reversion_band_pct": _v(8.0)}


class RegistryHasMeanReversionRulesTests(unittest.TestCase):
    def test_registry_and_capability_expose_the_new_rules(self) -> None:
        validate_rule_registry_integrity()
        self.assertIn("mean_reversion_ma_lookback", BACKTEST_RULE_REGISTRY)
        self.assertIn("mean_reversion_band_pct", BACKTEST_RULE_REGISTRY)
        self.assertEqual(BACKTEST_RULE_REGISTRY["mean_reversion_ma_lookback"].kind, "entry_trigger")
        self.assertEqual(BACKTEST_RULE_REGISTRY["breakout_lookback"].kind, "entry_trigger")
        caps = RULE_BASED_BACKTEST_CAPABILITIES
        self.assertIn("mean_reversion_ma_lookback", caps.supported_entry_rules)
        self.assertIn("mean_reversion_band_pct", caps.supported_entry_rules)
        # mean-reversion joined the entry-trigger group (later PRs add more).
        self.assertLessEqual(
            frozenset({"breakout_lookback", "mean_reversion_ma_lookback"}), caps.entry_trigger_rules
        )
        self.assertIn("mean_reversion_ma_lookback", caps.entry_trigger_rules)


class EntryTriggerGroupIsExactlyOneTests(unittest.TestCase):
    def test_no_entry_trigger_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec({"close_gt_ma20": _v(True)}))
        self.assertIn("entry trigger", str(ctx.exception).lower())

    def test_two_entry_triggers_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError) as ctx:
            RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec({"breakout_lookback": _v(20), "mean_reversion_ma_lookback": _v(20)}))
        msg = str(ctx.exception).lower()
        self.assertTrue("entry trigger" in msg or "conflict" in msg)

    def test_breakout_only_still_valid(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec({"breakout_lookback": _v(20)}))

    def test_mean_reversion_only_valid(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec(_MR_ENTRY))
        self.assertTrue(RULE_BASED_BACKTEST_CAPABILITIES.supports(_spec(_MR_ENTRY)))

    def test_band_pct_is_optional(self) -> None:
        RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec({"mean_reversion_ma_lookback": _v(20)}))


class MeanReversionIsADistinctComputationTests(unittest.TestCase):
    """Synthetic data where a breakout spec makes NO trade but a
    mean-reversion spec DOES (and vice versa) - proving the two entry
    signals are genuinely different, not a renamed breakout."""

    def setUp(self) -> None:
        # A long, gently declining series (no new highs -> no breakout),
        # with one sharp dip well below the 20-day SMA on bar 75, then a
        # partial recovery. Mean-reversion should buy that dip.
        base = [200.0 - 0.4 * i for i in range(75)]  # 200 -> ~170.4, slow decline
        base.append(base[-1] * 0.80)  # bar 75: sharp -20% dip
        base += [base[-2] * 0.95] * 20  # recovery-ish tail, still no new highs
        self.dataset = _dataset(base)

    def test_breakout_spec_makes_no_trade_on_a_declining_series(self) -> None:
        result = _run(_spec({"breakout_lookback": _v(20)}), self.dataset)
        self.assertEqual(result.metrics.trade_count, 0)

    def test_mean_reversion_spec_buys_the_dip_the_breakout_missed(self) -> None:
        result = _run(_spec(_MR_ENTRY), self.dataset)
        self.assertGreaterEqual(result.metrics.trade_count, 1)
        self.assertEqual(result.status, "completed")
        # The entry is the dip bar (index 75) or later, never before it.
        self.assertGreaterEqual(result.trades[0].entry_date, self.dataset.bars[75].timestamp)

    def test_band_pct_controls_sensitivity(self) -> None:
        wide = _run(_spec({"mean_reversion_ma_lookback": _v(20), "mean_reversion_band_pct": _v(15.0)}), self.dataset)
        narrow = _run(_spec({"mean_reversion_ma_lookback": _v(20), "mean_reversion_band_pct": _v(2.0)}), self.dataset)
        # A narrower band triggers at least as often as a wider one.
        self.assertGreaterEqual(narrow.metrics.trade_count, wide.metrics.trade_count)

    def test_mean_reversion_handlers_are_invoked_on_the_run_path(self) -> None:
        from unittest.mock import patch

        from gaon.research.krx_real_pipeline import BacktestRuleDefinition

        for key in ("mean_reversion_ma_lookback", "mean_reversion_band_pct"):
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
                    _run(_spec(_MR_ENTRY), self.dataset)
                self.assertGreater(calls["n"], 0)


class MeanReversionPredicatesAndExitStillApplyTests(unittest.TestCase):
    def test_volume_filter_still_gates_a_mean_reversion_entry(self) -> None:
        base = [200.0 - 0.4 * i for i in range(75)]
        base.append(base[-1] * 0.80)
        base += [base[-2] * 0.95] * 20
        vols = [1000.0] * len(base)
        vols[75] = 1.0  # the dip bar has almost no volume
        dataset = _dataset(base, vols)
        with_filter = _run(_spec({**_MR_ENTRY, }, filters={"volume_gte_ma20": _v(True)}), dataset)
        without = _run(_spec(_MR_ENTRY), dataset)
        self.assertLess(with_filter.metrics.trade_count, max(1, without.metrics.trade_count))

    def test_protective_stop_still_required(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            RULE_BASED_BACKTEST_CAPABILITIES.validate(_spec(_MR_ENTRY, exit_rules={"channel_exit_lookback": _v(10)}))


class UnknownRuleStillFailsClosedWithMeanReversionTests(unittest.TestCase):
    def test_mean_reversion_plus_an_unknown_rule_fails_closed(self) -> None:
        with self.assertRaises(UnsupportedStrategySpecError):
            _run(_spec({**_MR_ENTRY, "rsi_below": _v(30)}), _dataset([100.0] * 90))


if __name__ == "__main__":
    unittest.main()
