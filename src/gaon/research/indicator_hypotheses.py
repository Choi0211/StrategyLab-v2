"""Explainable indicator hypotheses, research only, not trading signals.

No automatic promotion, strategy mutation, or order execution.
"""
from __future__ import annotations
from dataclasses import dataclass
from gaon.research.market_feature_engine import FeatureReport

@dataclass(frozen=True)
class ResearchHypothesis:
    market: str
    symbol: str
    direction: str
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    status: str = "needs_backtest"
    order_allowed: bool = False

def propose(report: FeatureReport) -> ResearchHypothesis:
    if report.executable:
        raise ValueError("research report must be nonexecutable")
    f=report.features
    if report.bar_count < 35 or any(f.get(k) is None for k in ("sma20","rsi14","macd","volume","adx14")):
        return ResearchHypothesis(report.market,report.symbol,"NONE",(),("insufficient_indicator_history",))
    price = f.get("last_close")
    # A feature report has no last close; price-vs-SMA requires explicitly supplied
    # last closed price to avoid reconstructing an implicit entry quote.
    macd=f["macd"]["histogram"]
    rsi=f["rsi14"]
    rv=f["volume"]["relative_volume"]
    adx=f["adx14"]
    evidence=[]
    counter=[]
    if rv is None:
        counter.append("volume_baseline_unavailable")
    elif rv < 1:
        counter.append("below_average_volume")
    else:
        evidence.append("above_average_volume")
    if adx < 20:
        counter.append("weak_trend_adx")
    else:
        evidence.append("trend_strength_adx")
    if rsi >= 75 or rsi <= 25:
        counter.append("rsi_extreme")
    if macd > 0 and rsi > 50:
        direction="LONG"
        evidence.append("positive_macd_rsi")
    elif macd < 0 and rsi < 50:
        direction="SHORT"
        evidence.append("negative_macd_rsi")
    else:
        direction="NONE"
        counter.append("momentum_disagreement")
    if counter:
        direction="NONE"
    return ResearchHypothesis(report.market,report.symbol,direction,tuple(evidence),tuple(counter))
