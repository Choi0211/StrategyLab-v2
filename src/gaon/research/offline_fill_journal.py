"""Durable OFFLINE simulated fills only. Never exchange/broker Paper fills."""
from __future__ import annotations
import hashlib
import json
from dataclasses import asdict
from gaon.research.offline_paper_fills import simulate_next_bar
from gaon.learning.experience_journal import record

def simulate_and_record(connection, *, account, strategy_version_id, symbol,
                        direction, next_bar, notional_usd, observed_at,
                        fee_bps=5.0, slippage_bps=5.0):
    fill=simulate_next_bar(symbol=symbol,direction=direction,next_bar=next_bar,
        notional_usd=notional_usd,fee_bps=fee_bps,slippage_bps=slippage_bps)
    candle={k:next_bar[k] for k in ("symbol","timestamp","open","high","low","close")}
    evidence={"kind":fill.kind,"fill":asdict(fill),"candle":candle,
              "fee_bps":fee_bps,"slippage_bps":slippage_bps,
              "notional_usd":notional_usd,"real_paper_order":False,
              "real_live_order":False}
    identity=json.dumps([account,strategy_version_id,symbol,direction,candle,
                         notional_usd,fee_bps,slippage_bps],sort_keys=True,allow_nan=False)
    run_id="offline-fill:"+hashlib.sha256(identity.encode()).hexdigest()
    existing=connection.execute("SELECT observed_at FROM gaon_research_experiences WHERE market='BINANCE' AND account=? AND strategy_version_id=? AND run_id=?",
        (account,strategy_version_id,run_id)).fetchone() if connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='gaon_research_experiences'").fetchone() else None
    if existing: observed_at=existing[0]
    outcome="WIN" if fill.net_pnl>0 else "LOSS" if fill.net_pnl<0 else "FLAT"
    inserted=record(connection,market="BINANCE",account=account,
        strategy_version_id=strategy_version_id,run_id=run_id,
        observed_at=observed_at,outcome=outcome,net_pnl=fill.net_pnl,evidence=evidence)
    return {"run_id":run_id,"inserted":inserted,"kind":fill.kind,
            "net_pnl":fill.net_pnl,"promotion_allowed":False}
