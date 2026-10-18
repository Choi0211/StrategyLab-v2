"""Shared technical research features for KRX, US and crypto OHLCV bars.

Consumes closed candles, never places orders or approves strategy changes.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite
from typing import Iterable
from gaon.research.technical_indicators import (
    sma, ema, rsi, macd, adx, atr, bollinger, roc, stochastic,
    obv, vwap, volume_analysis, volume_profile,
)

@dataclass(frozen=True)
class FeatureReport:
    symbol: str
    market: str
    timeframe: str
    bar_count: int
    features: dict[str, object]
    missing: tuple[str, ...]
    executable: bool = False

def extract_features(bars: Iterable[object], *, market: str, timeframe: str) -> FeatureReport:
    if market not in {"KR_STOCK", "US_STOCK", "BINANCE"}:
        raise ValueError("unsupported market")
    if not timeframe:
        raise ValueError("timeframe required")
    records = list(bars)
    if not records:
        raise ValueError("empty bars")
    if len(records) > 100000:
        raise ValueError("too many bars")
    def field(item, name):
        return item[name] if isinstance(item, dict) else getattr(item, name)
    symbol = str(field(records[0], "symbol"))
    if not symbol or any(str(field(b,"symbol")) != symbol for b in records):
        raise ValueError("mixed symbols")
    times = [str(field(b,"timestamp")) for b in records]
    if len(set(times)) != len(times) or times != sorted(times):
        raise ValueError("unsorted or duplicate timestamps")
    h = [float(field(b,"high")) for b in records]
    l = [float(field(b,"low")) for b in records]
    c = [float(field(b,"close")) for b in records]
    v = [float(field(b,"volume")) for b in records]
    if any(not all(isfinite(z) for z in values) for values in (h,l,c,v)):
        raise ValueError("nonfinite bar")
    if any(lo>cl or cl>hi or lo<0 or vol<0 for hi,lo,cl,vol in zip(h,l,c,v)):
        raise ValueError("invalid OHLCV")
    features = {
        "sma20":sma(c,20), "ema20":ema(c,20), "rsi14":rsi(c,14),
        "macd":macd(c), "adx14":adx(h,l,c,14),
        "atr14":atr(h,l,c,14), "bollinger20":bollinger(c,20),
        "roc12":roc(c,12), "stochastic14":stochastic(h,l,c,14),
        "obv":obv(c,v), "vwap20":vwap(h,l,c,v,period=20),
        "volume":volume_analysis(h,l,c,v,period=20),
        "volume_profile":volume_profile(c[-100:],v[-100:]),
    }
    return FeatureReport(symbol,market,timeframe,len(records),features,
                         tuple(k for k,val in features.items() if val is None))
