"""Offline chronological data validation. Research-only, no trading actions."""
from __future__ import annotations
from datetime import datetime, timezone
from math import isfinite

def validate_closed_bars(bars, *, as_of=None, timeframe_seconds=None):
    if not isinstance(bars,list) or not bars:
        raise ValueError("nonempty list required")
    if timeframe_seconds is not None and (isinstance(timeframe_seconds,bool) or
        not isinstance(timeframe_seconds,(int,float)) or
        not isfinite(timeframe_seconds) or timeframe_seconds<=0):
        raise ValueError("invalid timeframe")
    if as_of is not None and (not isinstance(as_of,datetime) or as_of.tzinfo is None):
        raise ValueError("timezone-aware as_of required")
    previous=None
    for bar in bars:
        if not isinstance(bar,dict):
            raise ValueError("dict bars required")
        stamp=bar.get("timestamp")
        if not isinstance(stamp,str):
            raise ValueError("ISO timestamp required")
        try:
            parsed=datetime.fromisoformat(stamp.replace("Z","+00:00"))
        except ValueError as exc:
            raise ValueError("invalid timestamp") from exc
        if parsed.tzinfo is None:
            raise ValueError("timezone-aware timestamp required")
        parsed=parsed.astimezone(timezone.utc)
        if previous is not None and parsed<=previous:
            raise ValueError("out-of-order or duplicate candle")
        if as_of is not None and timeframe_seconds is not None:
            if parsed.timestamp()+timeframe_seconds>as_of.timestamp():
                raise ValueError("unclosed candle")
        previous=parsed
    return True
