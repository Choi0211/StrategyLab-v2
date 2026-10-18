"""Read-only daily equity research runner. No orders or strategy activation."""
from __future__ import annotations
import argparse
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
from gaon.research.real_equity_research_bridge import fetch_real_daily_bars
from gaon.research.offline_research_pipeline import research_and_record

def run(*, database, symbols, as_of=None, provider_factory=None):
    day=as_of or datetime.now(timezone.utc).date()
    if day>datetime.now(timezone.utc).date():
        raise ValueError("future as_of prohibited")
    end=day-timedelta(days=1)
    start=end-timedelta(days=365)
    results=[]
    for market,symbol in symbols:
        provider=provider_factory(market) if provider_factory else None
        candles=fetch_real_daily_bars(market=market,symbol=symbol,
            start_date=start.isoformat(),end_date=end.isoformat(),provider=provider)
        with sqlite3.connect(database,timeout=10) as conn:
            result=research_and_record(conn,candles,market=market,account="automated-research",
                strategy_version_id="offline-equity-v1",timeframe="daily",
                observed_at=datetime.now(timezone.utc).isoformat())
        results.append({"market":market,"symbol":symbol,**asdict(result)})
    return results

def main(argv=None):
    p=argparse.ArgumentParser(description="Read-only equity research")
    p.add_argument("--database",required=True)
    p.add_argument("--kr-symbol",action="append",default=[])
    p.add_argument("--us-symbol",action="append",default=[])
    args=p.parse_args(argv)
    symbols=[("KR_STOCK",x) for x in args.kr_symbol]+[("US_STOCK",x) for x in args.us_symbol]
    if not symbols or len(symbols)>20:p.error("1-20 symbols required")
    path=Path(args.database).resolve()
    if not path.parent.is_dir():p.error("database directory missing")
    print(json.dumps(run(database=str(path),symbols=symbols),ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
