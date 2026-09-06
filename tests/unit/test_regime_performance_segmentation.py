"""Priority 5 - BULL / NEUTRAL / BEAR regime performance segmentation.

A pure, post-hoc analysis over a COMPLETED backtest: bucket each trade
by the market regime at its entry bar, and report per-regime
performance. It never changes a trade decision, a stop, or a risk limit
- read-model only. A regime with too few trades is reported as
``insufficient_evidence`` rather than a misleading statistic.
"""

from __future__ import annotations

import datetime
import unittest

from gaon.research.regime_segmentation import (
    RegimePerformanceBreakdown,
    RegimeSegment,
    segment_trades_by_regime,
)
from gaon.research.krx_real_pipeline import RealBacktestTrade
from gaon.research.real_research import MarketBar

MA = 20  # small lookback for compact fixtures


def _bars(closes):
    d0 = datetime.date(2026, 1, 1)
    return [
        MarketBar((d0 + datetime.timedelta(days=i)).isoformat(), "005930", c, c * 1.001, c * 0.999, c, 1_000, int(c * 1000))
        for i, c in enumerate(closes)
    ]


def _trade(entry_ts, ret_pct):
    return RealBacktestTrade(
        trade_id="t", symbol="005930", entry_date=entry_ts, exit_date=entry_ts,
        entry_price=100.0, exit_price=100.0 * (1 + ret_pct), quantity=1,
        pnl=100.0 * ret_pct, return_pct=ret_pct, exit_reason="channel_low_exit",
    )


class BucketingTests(unittest.TestCase):
    def test_a_bull_leg_trade_lands_in_the_bull_bucket(self) -> None:
        bars = _bars([100.0 + i for i in range(60)])  # steady rise -> bull
        trades = [_trade(bars[40].timestamp, 0.05)]
        out = segment_trades_by_regime(trades, bars, ma_lookback=MA)
        self.assertIsInstance(out, RegimePerformanceBreakdown)
        self.assertEqual(out.bull.trade_count, 1)
        self.assertEqual(out.bear.trade_count, 0)
        self.assertEqual(out.neutral.trade_count, 0)

    def test_a_bear_leg_trade_lands_in_the_bear_bucket(self) -> None:
        bars = _bars([200.0 - i for i in range(60)])  # steady fall -> bear
        trades = [_trade(bars[40].timestamp, -0.03)]
        out = segment_trades_by_regime(trades, bars, ma_lookback=MA)
        self.assertEqual(out.bear.trade_count, 1)
        self.assertEqual(out.bull.trade_count, 0)

    def test_a_trade_before_enough_history_is_unclassifiable(self) -> None:
        bars = _bars([100.0 + i for i in range(60)])
        trades = [_trade(bars[5].timestamp, 0.01)]  # index 5 < ma_lookback
        out = segment_trades_by_regime(trades, bars, ma_lookback=MA)
        self.assertEqual(out.unclassifiable.trade_count, 1)
        self.assertEqual(out.bull.trade_count, 0)

    def test_a_trade_with_no_matching_bar_is_unclassifiable(self) -> None:
        bars = _bars([100.0 + i for i in range(60)])
        trades = [_trade("2099-01-01", 0.01)]
        out = segment_trades_by_regime(trades, bars, ma_lookback=MA)
        self.assertEqual(out.unclassifiable.trade_count, 1)


class SegmentStatisticsTests(unittest.TestCase):
    def test_per_segment_win_rate_and_profit_factor(self) -> None:
        bars = _bars([100.0 + i for i in range(80)])  # all bull after warmup
        trades = [
            _trade(bars[40].timestamp, 0.10),
            _trade(bars[45].timestamp, 0.05),
            _trade(bars[50].timestamp, -0.04),
        ]
        out = segment_trades_by_regime(trades, bars, ma_lookback=MA, min_trades_for_evidence=3)
        seg = out.bull
        self.assertEqual(seg.trade_count, 3)
        self.assertAlmostEqual(seg.win_rate, 2 / 3)
        self.assertAlmostEqual(seg.profit_factor, (10.0 + 5.0) / 4.0)
        self.assertFalse(seg.insufficient_evidence)

    def test_thin_segment_is_flagged_insufficient_evidence(self) -> None:
        bars = _bars([100.0 + i for i in range(80)])
        trades = [_trade(bars[40].timestamp, 0.02)]
        out = segment_trades_by_regime(trades, bars, ma_lookback=MA, min_trades_for_evidence=5)
        self.assertTrue(out.bull.insufficient_evidence)
        # an empty segment is also flagged.
        self.assertTrue(out.bear.insufficient_evidence)
        self.assertEqual(out.bear.trade_count, 0)

    def test_to_json_is_stable_and_covers_every_regime(self) -> None:
        bars = _bars([100.0 + i for i in range(80)])
        out = segment_trades_by_regime([_trade(bars[40].timestamp, 0.02)], bars, ma_lookback=MA)
        j = out.to_json()
        self.assertEqual(set(j), {"bull", "neutral", "bear", "unclassifiable"})
        self.assertEqual(j["bull"]["trade_count"], 1)


class NoDecisionSurfaceTests(unittest.TestCase):
    def test_module_is_analysis_only_no_execution_or_risk_names(self) -> None:
        import gaon.research.regime_segmentation as m

        for banned in ("apply", "execute", "set_risk", "override_stop", "place_order", "activate"):
            self.assertNotIn(banned, set(dir(m)))


if __name__ == "__main__":
    unittest.main()
