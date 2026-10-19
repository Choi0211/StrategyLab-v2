"""Closed-candle, next-open walk-forward research simulation.

Advisory only: no broker access, strategy activation or live orders.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from gaon.research.market_feature_engine import extract_features
from gaon.research.indicator_hypotheses import propose

@dataclass(frozen=True)
class WalkForwardReport:
    market: str
    symbol: str
    observations: int
    trades: int
    total_return: float
    win_rate: float | None
    trade_returns: tuple[float, ...]
    promotion_allowed: bool = False
    order_allowed: bool = False

def evaluate(bars, *, market: str, timeframe: str, fee_bps=5.0, slippage_bps=5.0):
    """At t close, choose direction; enter at t+1 open, exit at t+1 close.

    Fee/slippage charged on both entry and exit. One-bar horizon only.
    This is NOT a realistic fill simulator or profitability proof.
    """
    records=list(bars)
    if len(records)<40: raise ValueError("at least 40 closed candles required")
    if len(records)>100000: raise ValueError("too many candles")
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not isfinite(x) or x<0
           for x in (fee_bps,slippage_bps)):
        raise ValueError("invalid cost")
    # Validate complete input before any research to reject bad tails.
    extract_features(records,market=market,timeframe=timeframe)
    def field(b,k): return b[k] if isinstance(b,dict) else getattr(b,k)
    for bar in records:
        entry=float(field(bar,"open"))
        hi=float(field(bar,"high"))
        lo=float(field(bar,"low"))
        if not all(isfinite(x) for x in (entry,hi,lo)) or entry<=0 or not lo<=entry<=hi:
            raise ValueError("invalid open/high/low")
    returns=[]
    for i in range(35,len(records)-1):
        hypothesis=propose(extract_features(records[:i+1],market=market,timeframe=timeframe))
        if hypothesis.direction=="NONE": continue
        following=records[i+1]
        entry=float(field(following,"open"))
        close=float(field(following,"close"))
        hi=float(field(following,"high"))
        lo=float(field(following,"low"))
        if not all(isfinite(x) for x in (entry,close,hi,lo)) or entry<=0 or not lo<=entry<=hi:
            raise ValueError("invalid next-bar OHLC")
        gross=(close/entry-1) * (1 if hypothesis.direction=="LONG" else -1)
        net=gross-2*(fee_bps+slippage_bps)/10000
        returns.append(net)
    compounded=1.0
    for value in returns: compounded*=1+value
    return WalkForwardReport(market,str(field(records[0],"symbol")),len(records),
        len(returns),compounded-1 if returns else 0.0,
        sum(x>0 for x in returns)/len(returns) if returns else None,
        tuple(returns))
