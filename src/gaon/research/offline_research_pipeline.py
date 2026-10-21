"""Opt-in offline research pipeline: bars -> features -> hypothesis -> walk-forward -> journal.

Does not run automatically or communicate with trading engines. Recorded
outcomes are research evaluations, never broker/Paper fills.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from gaon.research.market_feature_engine import extract_features
from gaon.research.indicator_hypotheses import propose
from gaon.research.indicator_walkforward import evaluate
from gaon.learning.experience_journal import record
from gaon.research.closed_bar_validation import validate_closed_bars

@dataclass(frozen=True)
class OfflineResearchResult:
    run_id: str
    hypothesis_direction: str
    trade_count: int
    estimated_return: float
    journal_inserted: bool
    eligible_for_promotion: bool = False

def research_and_record(connection: sqlite3.Connection, bars, *,
                        market: str, account: str, strategy_version_id: str,
                        timeframe: str, observed_at: str,
                        fee_bps: float = 5.0, slippage_bps: float = 5.0):
    candles=list(bars)
    periods = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800,
               "1h": 3600, "4h": 14400, "1d": 86400, "daily": 86400}
    if timeframe not in periods:
        raise ValueError("unsupported closed-candle timeframe")
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("invalid observed_at") from exc
    if observed.tzinfo is None or observed > datetime.now(timezone.utc):
        raise ValueError("observed_at must be timezone-aware and not in the future")
    validate_closed_bars(candles, as_of=observed, timeframe_seconds=periods[timeframe])
    features=extract_features(candles,market=market,timeframe=timeframe)
    hypothesis=propose(features)
    test=evaluate(candles,market=market,timeframe=timeframe,
                  fee_bps=fee_bps,slippage_bps=slippage_bps)
    def field(b,k): return b[k] if isinstance(b,dict) else getattr(b,k)
    # Deterministic experiment identity, including input candles and costs.
    serialized=json.dumps({
        "bars":[{k:field(b,k) for k in ("symbol","timestamp","open","high","low","close","volume")}
                for b in candles],
        "market":market,"account":account,"strategy":strategy_version_id,
        "timeframe":timeframe,"fee_bps":fee_bps,"slippage_bps":slippage_bps
    },sort_keys=True,allow_nan=False)
    run_id=hashlib.sha256(serialized.encode()).hexdigest()
    evidence={"kind":"offline_walkforward_research_not_real_fills",
              "market":market,"symbol":features.symbol,"timeframe":timeframe,
              "direction":hypothesis.direction,"trades":test.trades,
              "estimated_total_return":test.total_return,
              "win_rate":test.win_rate,
              "fee_bps":fee_bps,"slippage_bps":slippage_bps,
              "evidence":list(hypothesis.evidence),
              "counter_evidence":list(hypothesis.counter_evidence)}
    # Stable timestamp for identical experiments; the digest must not change
    # just because a CLI was invoked again later.
    existing=connection.execute("SELECT observed_at FROM gaon_research_experiences WHERE market=? AND account=? AND strategy_version_id=? AND run_id=?",(market,account,strategy_version_id,run_id)).fetchone() if connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gaon_research_experiences'").fetchone() else None
    if existing:
        observed_at=existing[0]
    # No synthetic trade outcomes enter the actual-trade journal.
    inserted=record(connection,market=market,account=account,
                    strategy_version_id=strategy_version_id,run_id=run_id,
                    observed_at=observed_at,outcome="NO_TRADE",net_pnl=0.0,
                    evidence=evidence)
    return OfflineResearchResult(run_id,hypothesis.direction,test.trades,
                                 test.total_return,inserted)
