"""Isolated, deterministic Paper fill ledger. No exchange credentials or orders.

Only closed candle next-open simulated fills, with fee/slippage. This is not
the live Binance bot's Paper account and must not be described as such.
"""
from __future__ import annotations
from dataclasses import dataclass
from math import isfinite

@dataclass(frozen=True)
class SimulatedFill:
    symbol: str
    direction: str
    entry: float
    exit: float
    quantity: float
    gross_pnl: float
    fees: float
    net_pnl: float
    kind: str = "offline_simulated_not_exchange_fill"

def simulate_next_bar(*, symbol, direction, next_bar, notional_usd,
                      fee_bps=5.0, slippage_bps=5.0):
    if not isinstance(symbol,str) or not symbol or direction not in ("LONG","SHORT"):
        raise ValueError("invalid paper intent")
    values=(notional_usd,fee_bps,slippage_bps)
    if any(type(v) not in (int,float) or not isfinite(v) for v in values):
        raise ValueError("nonfinite paper parameters")
    if notional_usd<=0 or fee_bps<0 or slippage_bps<0 or fee_bps>1000 or slippage_bps>1000:
        raise ValueError("invalid paper risk or costs")
    if not isinstance(next_bar,dict) or next_bar.get("symbol")!=symbol:
        raise ValueError("wrong paper symbol")
    try:
        op=float(next_bar["open"])
        cl=float(next_bar["close"])
        hi=float(next_bar["high"])
        lo=float(next_bar["low"])
    except (KeyError,ValueError,TypeError) as exc:
        raise ValueError("invalid paper candle") from exc
    if not all(isfinite(v) for v in (op,cl,hi,lo)) or op<=0 or not 0<lo<=min(op,cl)<=max(op,cl)<=hi:
        raise ValueError("invalid paper OHLC")
    slip=slippage_bps/10000
    entry=op*(1+slip if direction=="LONG" else 1-slip)
    exit=cl*(1-slip if direction=="LONG" else 1+slip)
    if entry<=0: raise ValueError("invalid slippage")
    quantity=notional_usd/entry
    sign=1 if direction=="LONG" else -1
    gross=sign*(exit-entry)*quantity
    fees=(entry+exit)*quantity*fee_bps/10000
    return SimulatedFill(symbol,direction,entry,exit,quantity,gross,fees,gross-fees)
