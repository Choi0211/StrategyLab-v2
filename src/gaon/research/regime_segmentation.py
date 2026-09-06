"""Priority 5 - BULL / NEUTRAL / BEAR regime performance segmentation.

A pure, post-hoc read-model over a COMPLETED backtest. It buckets each
trade by the market regime at its ENTRY bar - using the same
close-vs-SMA(N) + close-vs-N-bars-ago definition the engine's
``regime_bullish_only`` filter uses - and reports per-regime performance.

It NEVER changes a trade decision, a stop, a leverage, a position size
or any risk limit. A regime with fewer than ``min_trades_for_evidence``
trades is reported as ``insufficient_evidence`` rather than a misleading
statistic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from gaon.research.krx_real_pipeline import RealBacktestTrade, _classify_market_regime
from gaon.research.real_research import MarketBar

_REGIMES = ("bull", "neutral", "bear", "unclassifiable")
DEFAULT_MIN_TRADES_FOR_EVIDENCE = 5


@dataclass(frozen=True)
class RegimeSegment:
    regime: str
    trade_count: int
    total_pnl: float
    total_return_pct: float
    win_rate: float | None
    profit_factor: float | None
    avg_win: float | None
    avg_loss: float | None
    insufficient_evidence: bool

    def to_json(self) -> dict[str, object]:
        return {
            "regime": self.regime,
            "trade_count": self.trade_count,
            "total_pnl": round(self.total_pnl, 6),
            "total_return_pct": round(self.total_return_pct, 6),
            "win_rate": None if self.win_rate is None else round(self.win_rate, 6),
            "profit_factor": None if self.profit_factor is None else round(self.profit_factor, 6),
            "avg_win": None if self.avg_win is None else round(self.avg_win, 6),
            "avg_loss": None if self.avg_loss is None else round(self.avg_loss, 6),
            "insufficient_evidence": self.insufficient_evidence,
        }


@dataclass(frozen=True)
class RegimePerformanceBreakdown:
    bull: RegimeSegment
    neutral: RegimeSegment
    bear: RegimeSegment
    unclassifiable: RegimeSegment

    def to_json(self) -> dict[str, object]:
        return {
            "bull": self.bull.to_json(),
            "neutral": self.neutral.to_json(),
            "bear": self.bear.to_json(),
            "unclassifiable": self.unclassifiable.to_json(),
        }


def _segment(regime: str, trades: list[RealBacktestTrade], *, min_trades: int) -> RegimeSegment:
    count = len(trades)
    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = (len(wins) / count) if count else None
    profit_factor = (sum(wins) / abs(sum(losses))) if losses else (None if not wins else float("inf"))
    return RegimeSegment(
        regime=regime,
        trade_count=count,
        total_pnl=sum(pnls),
        total_return_pct=sum(t.return_pct for t in trades),
        win_rate=win_rate,
        profit_factor=(None if profit_factor == float("inf") else profit_factor),
        avg_win=(sum(wins) / len(wins)) if wins else None,
        avg_loss=(sum(losses) / len(losses)) if losses else None,
        insufficient_evidence=count < min_trades,
    )


def segment_trades_by_regime(
    trades: Sequence[RealBacktestTrade],
    bars: Sequence[MarketBar],
    *,
    ma_lookback: int = 50,
    min_trades_for_evidence: int = DEFAULT_MIN_TRADES_FOR_EVIDENCE,
) -> RegimePerformanceBreakdown:
    """Bucket ``trades`` by the regime at their entry bar in ``bars``.

    A trade whose entry timestamp is not in ``bars``, or falls before
    ``ma_lookback`` bars of history exist, is ``unclassifiable`` - never
    force-assigned to a regime."""
    ordered = sorted(bars, key=lambda b: b.timestamp)
    index_by_ts = {b.timestamp: i for i, b in enumerate(ordered)}
    buckets: dict[str, list[RealBacktestTrade]] = {r: [] for r in _REGIMES}

    for trade in trades:
        i = index_by_ts.get(trade.entry_date)
        if i is None:
            buckets["unclassifiable"].append(trade)
            continue
        prior_closes = tuple(b.close for b in ordered[:i])
        regime = _classify_market_regime(ordered[i].close, prior_closes, ma_lookback)
        buckets[regime if regime in ("bull", "neutral", "bear") else "unclassifiable"].append(trade)

    return RegimePerformanceBreakdown(
        bull=_segment("bull", buckets["bull"], min_trades=min_trades_for_evidence),
        neutral=_segment("neutral", buckets["neutral"], min_trades=min_trades_for_evidence),
        bear=_segment("bear", buckets["bear"], min_trades=min_trades_for_evidence),
        unclassifiable=_segment("unclassifiable", buckets["unclassifiable"], min_trades=0),
    )
