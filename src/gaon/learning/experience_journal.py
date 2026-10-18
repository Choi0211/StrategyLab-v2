"""Durable research experience journal. Advisory only; never authorizes orders.

Evidence is immutable per (market, account, strategy, run_id). A conflicting
replay is rejected, preventing retrospective rewriting of failed experiments.
"""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone

MARKETS = frozenset({"KR_STOCK", "US_STOCK", "BINANCE"})
OUTCOMES = frozenset({"WIN", "LOSS", "FLAT", "NO_TRADE"})

def initialize(connection: sqlite3.Connection) -> None:
    connection.execute("""CREATE TABLE IF NOT EXISTS gaon_research_experiences (
        market TEXT NOT NULL, account TEXT NOT NULL,
        strategy_version_id TEXT NOT NULL, run_id TEXT NOT NULL,
        observed_at TEXT NOT NULL, outcome TEXT NOT NULL,
        net_pnl REAL NOT NULL, evidence_json TEXT NOT NULL,
        digest TEXT NOT NULL,
        PRIMARY KEY (market, account, strategy_version_id, run_id)
    )""")

def record(connection, *, market, account, strategy_version_id, run_id,
           observed_at, outcome, net_pnl, evidence):
    if market not in MARKETS or not all(isinstance(x,str) and x.strip()
             for x in (account,strategy_version_id,run_id)):
        raise ValueError("invalid identity")
    if outcome not in OUTCOMES:
        raise ValueError("invalid outcome")
    from math import isfinite
    if isinstance(net_pnl,bool) or not isinstance(net_pnl,(int,float)) or not isfinite(net_pnl):
        raise ValueError("invalid pnl")
    try:
        stamp=datetime.fromisoformat(observed_at.replace("Z","+00:00"))
        if stamp.tzinfo is None: raise ValueError("timezone required")
    except (AttributeError,ValueError) as exc:
        raise ValueError("invalid observed_at") from exc
    if not isinstance(evidence,dict) or not evidence:
        raise ValueError("evidence required")
    data=json.dumps(evidence,sort_keys=True,ensure_ascii=False,allow_nan=False)
    digest=hashlib.sha256(json.dumps([market,account,strategy_version_id,run_id,observed_at,
        outcome,float(net_pnl),data],ensure_ascii=False).encode()).hexdigest()
    initialize(connection)
    row=connection.execute("""SELECT digest FROM gaon_research_experiences
      WHERE market=? AND account=? AND strategy_version_id=? AND run_id=?""",
      (market,account,strategy_version_id,run_id)).fetchone()
    if row:
        if row[0]!=digest: raise ValueError("conflicting experience replay")
        return False
    connection.execute("""INSERT INTO gaon_research_experiences VALUES (?,?,?,?,?,?,?,?,?)""",
        (market,account,strategy_version_id,run_id,observed_at,outcome,float(net_pnl),data,digest))
    connection.commit()
    return True

def summary(connection, *, market, account, strategy_version_id):
    initialize(connection)
    rows=connection.execute("""SELECT outcome,net_pnl FROM gaon_research_experiences
        WHERE market=? AND account=? AND strategy_version_id=?""",
        (market,account,strategy_version_id)).fetchall()
    traded=[(outcome,pnl) for outcome,pnl in rows if outcome!="NO_TRADE"]
    return {"experiments":len(rows),"trades":len(traded),
            "wins":sum(outcome=="WIN" for outcome,_ in traded),
            "net_pnl":sum(pnl for _,pnl in traded),
            "promotion_allowed":False}
