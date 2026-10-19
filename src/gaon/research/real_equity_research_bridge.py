"""Read-only bridge from existing real equity providers into offline research.

No fixture fallback, no orders, no automatic scheduling.
"""
from __future__ import annotations
from datetime import date, datetime, timezone
from gaon.research.global_market import GlobalMarketDataProvider
from gaon.research.krx_real_pipeline import YahooKRXHistoricalDataProvider

def fetch_real_daily_bars(*, market, symbol, start_date, end_date, provider=None):
    if market not in ("KR_STOCK","US_STOCK"):
        raise ValueError("equity market required")
    start=date.fromisoformat(start_date)
    end=date.fromisoformat(end_date)
    if start>end or end>=datetime.now(timezone.utc).date():
        raise ValueError("research must exclude current UTC date")
    if (end-start).days>3650:
        raise ValueError("range too long")
    if not isinstance(symbol,str) or not symbol.strip():
        raise ValueError("symbol required")
    source=provider or (YahooKRXHistoricalDataProvider() if market=="KR_STOCK" else GlobalMarketDataProvider())
    dataset=source.fetch_bars(symbol,start_date=start_date,end_date=end_date,timeframe="daily")
    metadata=dataset.metadata
    if getattr(metadata,"fixture_backed",True) or not str(getattr(metadata,"source","")).startswith("real:"):
        raise ValueError("verified real provider provenance required")
    result=[]
    for b in dataset.bars:
        day=date.fromisoformat(b.timestamp)
        if not start<=day<=end:
            raise ValueError("out-of-range provider candle")
        result.append(dict(symbol=b.symbol,timestamp=day.isoformat()+"T00:00:00Z",
                           open=b.open,high=b.high,low=b.low,close=b.close,volume=b.volume))
    if len(result)<40:
        raise ValueError("insufficient real historical bars")
    from gaon.research.closed_bar_validation import validate_closed_bars
    validate_closed_bars(result)
    return result
