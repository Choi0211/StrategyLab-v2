"""Cross-market OHLCV technical indicators with explicit warm-up and no lookahead.

Only closed candles should be passed by the caller. None means insufficient
history or undefined denominator. This is a research feature API, not an order signal.
"""
from __future__ import annotations
from math import isfinite, sqrt
from typing import Sequence

CATALOG = {
    "trend": ("sma", "ema", "macd", "adx"),
    "momentum": ("rsi", "stochastic", "roc"),
    "volatility": ("atr", "bollinger"),
    "volume": ("obv", "vwap"),
}

def _series(values: Sequence[float], *, positive=False) -> list[float]:
    out = [float(v) for v in values]
    if not all(isfinite(v) and (not positive or v >= 0) for v in out):
        raise ValueError("nonfinite or negative input")
    return out

def sma(values, period=20):
    x = _series(values)
    if period < 1: raise ValueError("period")
    return sum(x[-period:]) / period if len(x) >= period else None

def ema(values, period=20):
    x = _series(values)
    if period < 1: raise ValueError("period")
    if len(x) < period: return None
    value = sum(x[:period]) / period
    alpha = 2 / (period + 1)
    for item in x[period:]:
        value += alpha * (item - value)
    return value

def rsi(close, period=14):
    x = _series(close)
    if period < 1: raise ValueError("period")
    if len(x) < period + 1: return None
    changes = [x[i] - x[i-1] for i in range(1, len(x))]
    gains = sum(max(v, 0) for v in changes[:period]) / period
    losses = sum(max(-v, 0) for v in changes[:period]) / period
    for change in changes[period:]:
        gains = (gains * (period - 1) + max(change, 0)) / period
        losses = (losses * (period - 1) + max(-change, 0)) / period
    if losses == 0: return 100.0 if gains > 0 else 50.0
    return 100 - 100 / (1 + gains / losses)

def atr(high, low, close, period=14):
    h,l,c = _series(high),_series(low),_series(close)
    if not len(h) == len(l) == len(c): raise ValueError("length mismatch")
    if any(lo > hi or not lo <= cl <= hi for hi,lo,cl in zip(h,l,c)):
        raise ValueError("invalid OHLC")
    if period < 1: raise ValueError("period")
    if len(c) < period + 1: return None
    tr = [max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]
    value = sum(tr[:period])/period
    for v in tr[period:]:
        value = (value*(period-1)+v)/period
    return value

def bollinger(close, period=20, deviations=2):
    x = _series(close)
    if period < 2 or deviations <= 0: raise ValueError("parameters")
    if len(x) < period: return None
    window = x[-period:]
    mean = sum(window)/period
    std = sqrt(sum((v-mean)**2 for v in window)/period)
    return {"lower":mean-deviations*std,"middle":mean,"upper":mean+deviations*std}

def roc(close, period=12):
    x = _series(close)
    if period < 1: raise ValueError("period")
    if len(x) <= period or x[-period-1] == 0: return None
    return (x[-1]/x[-period-1]-1)*100

def stochastic(high, low, close, period=14):
    h,l,c = _series(high),_series(low),_series(close)
    if len(h)!=len(l) or len(l)!=len(c): raise ValueError("length mismatch")
    if period < 1: raise ValueError("period")
    if len(c)<period: return None
    top,bottom=max(h[-period:]),min(l[-period:])
    return 50.0 if top==bottom else 100*(c[-1]-bottom)/(top-bottom)

def obv(close, volume):
    c,v = _series(close),_series(volume,positive=True)
    if len(c)!=len(v): raise ValueError("length mismatch")
    if not c: return None
    return sum(v[i] if c[i]>c[i-1] else -v[i] if c[i]<c[i-1] else 0 for i in range(1,len(c)))

def vwap(high,low,close,volume,period=None):
    h,l,c,v= _series(high),_series(low),_series(close),_series(volume,positive=True)
    if not len(h)==len(l)==len(c)==len(v): raise ValueError("length mismatch")
    if period is not None:
        if period<1: raise ValueError("period")
        if len(c)<period: return None
        h,l,c,v=h[-period:],l[-period:],c[-period:],v[-period:]
    if not v or sum(v)==0: return None
    return sum((hi+lo+cl)/3*vol for hi,lo,cl,vol in zip(h,l,c,v))/sum(v)

def macd(close,fast=12,slow=26,signal=9):
    c=_series(close)
    if not 0<fast<slow or signal<1: raise ValueError("parameters")
    if len(c)<slow+signal-1: return None
    line=[ema(c[:i],fast)-ema(c[:i],slow) for i in range(slow,len(c)+1)]
    sig=ema(line,signal)
    return {"macd":line[-1],"signal":sig,"histogram":line[-1]-sig}

def adx(high,low,close,period=14):
    h,l,c=_series(high),_series(low),_series(close)
    if not len(h)==len(l)==len(c): raise ValueError("length mismatch")
    if period<1: raise ValueError("period")
    if len(c)<2*period: return None
    tr=[]; plus=[]; minus=[]
    for i in range(1,len(c)):
        up=h[i]-h[i-1]; down=l[i-1]-l[i]
        plus.append(up if up>down and up>0 else 0)
        minus.append(down if down>up and down>0 else 0)
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    smtr=sum(tr[:period]); smp=sum(plus[:period]); smm=sum(minus[:period])
    dx=[]
    for i in range(period-1,len(tr)):
        if i>=period:
            smtr=smtr-smtr/period+tr[i]
            smp=smp-smp/period+plus[i]
            smm=smm-smm/period+minus[i]
        denom=smp+smm
        dx.append(0 if denom==0 else 100*abs(smp-smm)/denom)
    value=sum(dx[:period])/period
    for item in dx[period:]:
        value=(value*(period-1)+item)/period
    return value


def volume_profile(close, volume, bins=12):
    """Approximate close-price volume histogram, NOT exchange volume-at-price."""
    c,v = _series(close), _series(volume, positive=True)
    if len(c) != len(v): raise ValueError("length mismatch")
    if not isinstance(bins, int) or not 2 <= bins <= 200: raise ValueError("bins")
    if not c or sum(v) == 0: return None
    lo,hi = min(c),max(c)
    if lo == hi: return {"poc":lo,"bins":[{"low":lo,"high":hi,"volume":sum(v)}],"method":"close_proxy"}
    width = (hi-lo)/bins
    totals = [0.0]*bins
    for price,amount in zip(c,v):
        idx = min(bins-1,int((price-lo)/width))
        totals[idx] += amount
    levels = [{"low":lo+i*width,"high":lo+(i+1)*width,"volume":amount} for i,amount in enumerate(totals)]
    poc_index = max(range(bins),key=lambda i:totals[i])
    return {"poc":(levels[poc_index]["low"]+levels[poc_index]["high"])/2,"bins":levels,"method":"close_proxy"}

def volume_analysis(high,low,close,volume,period=20):
    """Research-only volume context. Uses only supplied closed candles.

    ratio: last volume / prior period mean, excludes current candle.
    signed_volume is close-to-close direction proxy, NOT actual buy/sell tape.
    """
    h,l,c,v = _series(high),_series(low),_series(close),_series(volume,positive=True)
    if not len(h)==len(l)==len(c)==len(v): raise ValueError("length mismatch")
    if period<2: raise ValueError("period")
    if len(c)<period+1: return None
    if any(lo>hi or not lo<=cl<=hi for hi,lo,cl in zip(h,l,c)):
        raise ValueError("invalid OHLC")
    baseline=sum(v[-period-1:-1])/period
    ratio=v[-1]/baseline if baseline>0 else None
    prior_price=c[-2]
    signed=v[-1] if c[-1]>prior_price else -v[-1] if c[-1]<prior_price else 0.0
    return {"volume":v[-1],"mean_prior_volume":baseline,"relative_volume":ratio,
            "signed_volume_proxy":signed,"obv":obv(c,v),
            "vwap_window":vwap(h,l,c,v,period=period),
            "notional_proxy":c[-1]*v[-1],
            "interpretation":"proxy_not_trade_side_or_order_book"}

