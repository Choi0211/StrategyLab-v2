"""Explicit, offline research CLI. Reads a local OHLCV JSON file; never trades.

Usage: python -m gaon.research.offline_research_cli --input bars.json
       --database /path/research.sqlite --market BINANCE --account research
       --strategy-version-id candidate-v1 --timeframe 1m
"""
from __future__ import annotations
import argparse
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from gaon.research.offline_research_pipeline import research_and_record

def main(argv=None):
    parser=argparse.ArgumentParser(description="Offline research only; no orders")
    parser.add_argument("--input",required=True)
    parser.add_argument("--database",required=True)
    parser.add_argument("--market",choices=("KR_STOCK","US_STOCK","BINANCE"),required=True)
    parser.add_argument("--account",required=True)
    parser.add_argument("--strategy-version-id",required=True)
    parser.add_argument("--timeframe",required=True)
    parser.add_argument("--fee-bps",type=float,default=5.0)
    parser.add_argument("--slippage-bps",type=float,default=5.0)
    args=parser.parse_args(argv)
    path=Path(args.input).resolve(strict=True)
    if path.stat().st_size>25_000_000:
        parser.error("input exceeds 25 MB")
    data=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data,list):
        parser.error("input must be a list of closed OHLCV candles")
    database=Path(args.database).resolve()
    if database==path:
        parser.error("database must not overwrite input")
    # No database write occurs until input data has passed pipeline validation.
    with sqlite3.connect(str(database),timeout=10) as conn:
        result=research_and_record(conn,data,market=args.market,
            account=args.account,strategy_version_id=args.strategy_version_id,
            timeframe=args.timeframe,fee_bps=args.fee_bps,
            slippage_bps=args.slippage_bps,
            observed_at=datetime.now(timezone.utc).isoformat())
    print(json.dumps(asdict(result),ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
