"""Independent forward-paper verification for the frozen "48h LONG
cross-sectional momentum" crypto strategy.

Context: offline historical research
(``/opt/binance-trading/research/claude_cross_sectional_momentum_v2_20261019/``)
found a PENDING result (OOS PF 3.112) that could not be promoted - it was
concentrated in one symbol/period and drawn from a single, atypically
bullish historical window with no independent out-of-regime confirmation.
This module collects genuinely NEW market data going forward and tracks
a frozen, versioned strategy definition against it in an isolated virtual
portfolio - never reusing the historical OOS result as new evidence.

Safety boundary, by construction, not by policy comment:
  - Only ever calls Binance's PUBLIC, unauthenticated market-data
    endpoints (klines, funding rate) - no API key is read or required,
    so this module cannot place an order even if asked to; there is no
    authenticated client anywhere in this file.
  - Never imports ``gaon.adapters.binance`` (which reads the LIVE bot's
    own state/research files) or anything under /opt/binance-trading.
  - Writes only to its own dedicated sqlite file, never
    ``/var/lib/strategylab/gaon-runtime.sqlite`` or any binance-trading
    state file.
  - Exposes read-only status only; nothing here is registered as an
    LLM-callable tool.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Sequence

KLINES_URL = "https://fapi.binance.com/fapi/v1/klines"
FUNDING_URL = "https://fapi.binance.com/fapi/v1/fundingRate"

# ---------------------------------------------------------------------------
# Frozen strategy specification (requirements 1, 13: version-hash and freeze
# everything a forward run depends on; a parameter change must register as a
# new version, never silently merged into this one's trade history).
# ---------------------------------------------------------------------------

UNIVERSE: tuple[str, ...] = tuple(sorted((
    "ADAUSDT", "AVAXUSDT", "BNBUSDT", "BRUSDT", "BTCUSDT", "DOGEUSDT", "ENAUSDT",
    "ETHUSDT", "HYPEUSDT", "NEARUSDT", "NMRUSDT", "ORCAUSDT", "PUMPUSDT", "QNTUSDT",
    "RLCUSDT", "SANDUSDT", "SOLUSDT", "SUIUSDT", "TAOUSDT", "UNIUSDT", "WLDUSDT",
    "XRPUSDT", "ZECUSDT",
)))

STRATEGY_SPEC: dict[str, object] = {
    "name": "csm-long-48h",
    "description": "Cross-sectional momentum: LONG the top quartile of UNIVERSE ranked by trailing lookback_bars return; ungated (no BTC-regime filter - that is a separate, not-yet-forward-tested hypothesis); equal-weighted; no rebalance overlap.",
    "universe": list(UNIVERSE),
    "bar_minutes": 5,
    "lookback_bars": 576,
    "hold_bars": 576,
    "liquidity_window_bars": 2016,
    "liquidity_floor_usd": 50_000.0,
    "quartile_rounding": "ceil(n_eligible/4)",
    "min_eligible_for_rebalance": 8,
    "cost_bps_roundtrip": [17, 30, 40],
    "funding_source": "binance_public_fapi_fundingRate",
    "concentration_cap_pct": 40,
    "correlation_cap": 0.70,
}

# Promotion-readiness bar for FORWARD evidence specifically (requirement 10):
# at least this many independent forward trades, spanning at least this many
# non-overlapping rebalance cycles, covering at least this many of the three
# BTC regime buckets with a minimum trade count each - frozen before any
# forward result exists. Clearing this makes the version eligible for a
# human promotion REVIEW; it never auto-promotes anything.
MIN_FORWARD_TRADES = 100
MIN_INDEPENDENT_REBALANCES = 30
MIN_REGIME_BUCKETS_REPRESENTED = 2
MIN_TRADES_PER_REPRESENTED_REGIME = 5


def spec_version_hash(spec: dict[str, object] = STRATEGY_SPEC) -> str:
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


STRATEGY_VERSION = f"{STRATEGY_SPEC['name']}-v1-{spec_version_hash()}"


# ---------------------------------------------------------------------------
# Schema - a dedicated set of tables, isolated from the main runtime schema
# and from anything binance-trading owns.
# ---------------------------------------------------------------------------

def ensure_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS crypto_fv_bars(
            symbol TEXT NOT NULL,
            open_time_ms INTEGER NOT NULL,
            open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
            close REAL NOT NULL, volume REAL NOT NULL,
            PRIMARY KEY (symbol, open_time_ms)
        );
        CREATE TABLE IF NOT EXISTS crypto_fv_versions(
            version TEXT PRIMARY KEY,
            spec_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            version_start_bar_ms INTEGER
        );
        CREATE TABLE IF NOT EXISTS crypto_fv_rebalances(
            version TEXT NOT NULL,
            rebalance_index INTEGER NOT NULL,
            decided_at_ms INTEGER NOT NULL,
            eligible_count INTEGER NOT NULL,
            picked_json TEXT NOT NULL,
            btc_regime TEXT NOT NULL,
            PRIMARY KEY (version, rebalance_index)
        );
        CREATE TABLE IF NOT EXISTS crypto_fv_trades(
            version TEXT NOT NULL,
            rebalance_index INTEGER NOT NULL,
            symbol TEXT NOT NULL,
            entry_time_ms INTEGER NOT NULL,
            exit_time_ms INTEGER NOT NULL,
            entry_price REAL,
            exit_price REAL,
            price_pct REAL,
            funding_pct REAL,
            btc_regime TEXT NOT NULL,
            status TEXT NOT NULL,
            PRIMARY KEY (version, rebalance_index, symbol)
        );
        """
    )


def register_version(connection: sqlite3.Connection, *, now_iso: str) -> None:
    """Idempotent: a given spec hash is only ever registered once. A
    parameter change produces a different STRATEGY_VERSION and therefore a
    brand-new row/trade history - never merged with this one's."""
    with connection:
        connection.execute(
            "INSERT OR IGNORE INTO crypto_fv_versions(version, spec_json, started_at, version_start_bar_ms) VALUES (?, ?, ?, NULL)",
            (STRATEGY_VERSION, json.dumps(STRATEGY_SPEC, sort_keys=True), now_iso),
        )


# ---------------------------------------------------------------------------
# Pure helpers (fully unit-testable without real time or network)
# ---------------------------------------------------------------------------

def to_5m_bars(one_minute_rows: Sequence[tuple]) -> list[tuple]:
    """Each row: (open_time_ms, open, high, low, close, volume). Only
    contiguous 1-minute groups of 5 become a 5m bar - matches every prior
    research script's construction exactly."""
    bars = []
    for j in range(0, len(one_minute_rows) - 4, 5):
        q = one_minute_rows[j:j + 5]
        if int(q[-1][0]) - int(q[0][0]) != 240_000:
            continue
        bars.append((
            int(q[-1][0]), float(q[0][1]),
            max(float(r[2]) for r in q), min(float(r[3]) for r in q),
            float(q[-1][4]), sum(float(r[5]) for r in q),
        ))
    return bars


def rolling_mean_dollar_volume(bars: Sequence[tuple], window: int) -> list[float | None]:
    dv = [b[4] * b[5] for b in bars]
    n = len(dv)
    out: list[float | None] = [None] * n
    s = 0.0
    for i in range(n):
        s += dv[i]
        if i >= window:
            s -= dv[i - window]
        if i >= window - 1:
            out[i] = s / window
    return out


@dataclass(frozen=True)
class RebalanceDecision:
    rebalance_index: int
    decided_at_ms: int
    eligible_count: int
    picked: tuple[str, ...]
    btc_regime: str


def classify_btc_regime(btc_trailing_return: float | None) -> str:
    if btc_trailing_return is None:
        return "unknown"
    if btc_trailing_return > 0.01:
        return "up"
    if btc_trailing_return < -0.01:
        return "down"
    return "flat"


def decide_rebalance(
    bars_by_symbol: dict[str, Sequence[tuple]],
    *,
    decision_idx: int,
    spec: dict[str, object] = STRATEGY_SPEC,
) -> RebalanceDecision | None:
    """Pure: given 5m bars already collected for every symbol, decide the
    top-quartile LONG basket at bar index ``decision_idx`` (BTCUSDT's own
    bar list is the reference clock). Returns None if warmup/liquidity data
    is insufficient - never fabricates a decision from partial data."""
    lookback = int(spec["lookback_bars"])
    liq_window = int(spec["liquidity_window_bars"])
    floor_usd = float(spec["liquidity_floor_usd"])
    btc_bars = bars_by_symbol.get("BTCUSDT")
    if btc_bars is None or decision_idx >= len(btc_bars) or decision_idx - lookback < 0:
        return None
    btc_ret = btc_bars[decision_idx][4] / btc_bars[decision_idx - lookback][4] - 1 if btc_bars[decision_idx - lookback][4] else None

    scored: list[tuple[float, str]] = []
    for sym in spec["universe"]:
        bars = bars_by_symbol.get(sym)
        if bars is None or decision_idx >= len(bars) or decision_idx - lookback < 0:
            continue
        liq = rolling_mean_dollar_volume(bars[: decision_idx + 1], liq_window)
        if decision_idx >= len(liq) or liq[decision_idx] is None or liq[decision_idx] < floor_usd:
            continue
        prev_close = bars[decision_idx - lookback][4]
        if not prev_close:
            continue
        ret = bars[decision_idx][4] / prev_close - 1
        scored.append((ret, sym))
    if len(scored) < int(spec["min_eligible_for_rebalance"]):
        return None
    scored.sort(reverse=True)
    q = max(1, -(-len(scored) // 4))
    picked = tuple(sym for _, sym in scored[:q])
    return RebalanceDecision(
        rebalance_index=-1,  # filled in by the caller, which knows the running counter
        decided_at_ms=btc_bars[decision_idx][0],
        eligible_count=len(scored),
        picked=picked,
        btc_regime=classify_btc_regime(btc_ret),
    )


def funding_cost_pct(funding_events: Sequence[tuple[int, float]], start_ms: int, end_ms: int) -> float:
    """``funding_events``: sorted (funding_time_ms, rate) pairs. A LONG
    position pays when the historical rate was positive."""
    total = 0.0
    for t, rate in funding_events:
        if start_ms <= t < end_ms:
            total += -(rate * 100)
    return total


def metric(net_pcts: Sequence[float]) -> dict[str, object]:
    p = list(net_pcts)
    if not p:
        return {"n": 0, "pf": None, "mean_pct": None, "net_sum_pct": 0.0, "wins": 0, "mdd_pct": 0.0}
    gp = sum(x for x in p if x > 0)
    gl = -sum(x for x in p if x < 0)
    equity = peak = mdd = 0.0
    for x in p:
        equity += x
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return {
        "n": len(p), "pf": round(gp / gl, 3) if gl else None,
        "mean_pct": round(sum(p) / len(p), 4), "net_sum_pct": round(sum(p), 3),
        "wins": sum(1 for x in p if x > 0), "mdd_pct": round(mdd, 3),
    }


def promotion_readiness(trades: Sequence[dict]) -> dict[str, object]:
    """Requirement 10, 14: never claims promotion-review-eligibility until
    all three bars clear. Returns the reasons blocking it when they don't."""
    n = len(trades)
    rebalances = len({t["rebalance_index"] for t in trades})
    by_regime: dict[str, int] = {}
    for t in trades:
        by_regime[t["btc_regime"]] = by_regime.get(t["btc_regime"], 0) + 1
    regimes_represented = sum(1 for r, c in by_regime.items() if r in ("up", "down", "flat") and c >= MIN_TRADES_PER_REPRESENTED_REGIME)
    blockers = []
    if n < MIN_FORWARD_TRADES:
        blockers.append(f"forward trades {n} < required {MIN_FORWARD_TRADES}")
    if rebalances < MIN_INDEPENDENT_REBALANCES:
        blockers.append(f"independent rebalances {rebalances} < required {MIN_INDEPENDENT_REBALANCES}")
    if regimes_represented < MIN_REGIME_BUCKETS_REPRESENTED:
        blockers.append(
            f"BTC regime buckets with >={MIN_TRADES_PER_REPRESENTED_REGIME} trades: {regimes_represented} < required {MIN_REGIME_BUCKETS_REPRESENTED}"
        )
    return {
        "forward_trades": n, "independent_rebalances": rebalances,
        "trades_by_regime": by_regime, "regimes_represented": regimes_represented,
        "eligible_for_promotion_review": not blockers,
        "blockers": blockers if blockers else ["none - eligible for a human promotion review (this is NOT a promotion)"],
    }


# ---------------------------------------------------------------------------
# Repository (DB-touching, thin)
# ---------------------------------------------------------------------------

class CryptoForwardVerificationRepository:
    def __init__(self, connection: sqlite3.Connection, *, ensure_schema_: bool = True) -> None:
        # ``ensure_schema_=False`` is for a read-only (mode=ro) connection -
        # e.g. the Gaon admin page reading this DB - where even a no-op
        # "CREATE TABLE IF NOT EXISTS" would raise against a read-only
        # sqlite handle. Only the live verification service itself (which
        # opens the DB read-write) needs to actually create the schema.
        if ensure_schema_:
            ensure_schema(connection)
        self._connection = connection

    def upsert_bars(self, symbol: str, one_minute_rows: Sequence[tuple]) -> None:
        with self._connection:
            self._connection.executemany(
                "INSERT OR IGNORE INTO crypto_fv_bars(symbol, open_time_ms, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(symbol, int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in one_minute_rows],
            )

    def load_1m_rows(self, symbol: str) -> list[tuple]:
        rows = self._connection.execute(
            "SELECT open_time_ms, open, high, low, close, volume FROM crypto_fv_bars WHERE symbol = ? ORDER BY open_time_ms", (symbol,)
        ).fetchall()
        return [tuple(r) for r in rows]

    def next_rebalance_index(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(rebalance_index), -1) FROM crypto_fv_rebalances WHERE version = ?", (STRATEGY_VERSION,)
        ).fetchone()
        return row[0] + 1

    def record_rebalance(self, decision: RebalanceDecision) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO crypto_fv_rebalances(version, rebalance_index, decided_at_ms, eligible_count, picked_json, btc_regime) VALUES (?, ?, ?, ?, ?, ?)",
                (STRATEGY_VERSION, decision.rebalance_index, decision.decided_at_ms, decision.eligible_count, json.dumps(list(decision.picked)), decision.btc_regime),
            )

    def open_trade(self, *, rebalance_index: int, symbol: str, entry_time_ms: int, exit_time_ms: int, entry_price: float, btc_regime: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO crypto_fv_trades(version, rebalance_index, symbol, entry_time_ms, exit_time_ms, entry_price, exit_price, price_pct, funding_pct, btc_regime, status) "
                "VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, NULL, ?, 'open')",
                (STRATEGY_VERSION, rebalance_index, symbol, entry_time_ms, exit_time_ms, entry_price, btc_regime),
            )

    def close_trade(self, *, rebalance_index: int, symbol: str, exit_price: float, price_pct: float, funding_pct: float) -> None:
        with self._connection:
            self._connection.execute(
                "UPDATE crypto_fv_trades SET exit_price = ?, price_pct = ?, funding_pct = ?, status = 'closed' "
                "WHERE version = ? AND rebalance_index = ? AND symbol = ? AND status = 'open'",
                (exit_price, price_pct, funding_pct, STRATEGY_VERSION, rebalance_index, symbol),
            )

    def open_trades_due(self, *, as_of_ms: int) -> list[sqlite3.Row]:
        self._connection.row_factory = sqlite3.Row
        rows = self._connection.execute(
            "SELECT rebalance_index, symbol, entry_time_ms, exit_time_ms, entry_price, btc_regime FROM crypto_fv_trades "
            "WHERE version = ? AND status = 'open' AND exit_time_ms <= ?",
            (STRATEGY_VERSION, as_of_ms),
        ).fetchall()
        self._connection.row_factory = None
        return rows

    def all_trades(self) -> list[dict]:
        self._connection.row_factory = sqlite3.Row
        rows = self._connection.execute(
            "SELECT rebalance_index, symbol, entry_time_ms, exit_time_ms, entry_price, exit_price, price_pct, funding_pct, btc_regime, status "
            "FROM crypto_fv_trades WHERE version = ? ORDER BY entry_time_ms", (STRATEGY_VERSION,)
        ).fetchall()
        self._connection.row_factory = None
        return [dict(r) for r in rows]

    def version_started_at(self) -> str | None:
        row = self._connection.execute("SELECT started_at FROM crypto_fv_versions WHERE version = ?", (STRATEGY_VERSION,)).fetchone()
        return row[0] if row else None


# ---------------------------------------------------------------------------
# Status (read-only aggregation; requirements 7, 8, 9, 10, 12)
# ---------------------------------------------------------------------------

def status(repo: CryptoForwardVerificationRepository, *, cost_bps: float = 30.0) -> dict[str, object]:
    trades = [t for t in repo.all_trades() if t["status"] == "closed"]
    cost_pct = cost_bps / 100
    net = [t["price_pct"] + t["funding_pct"] - cost_pct for t in trades]
    all_cost_metrics = {
        str(bps / 100): metric([t["price_pct"] + t["funding_pct"] - bps / 100 for t in trades])
        for bps in STRATEGY_SPEC["cost_bps_roundtrip"]
    }
    by_symbol: dict[str, float] = {}
    for t, n in zip(trades, net):
        by_symbol[t["symbol"]] = by_symbol.get(t["symbol"], 0.0) + n
    total_net = sum(by_symbol.values())
    top_symbol_share = (max(by_symbol.values(), key=abs) / total_net) if total_net and by_symbol else None
    largest_symbol = max(by_symbol, key=lambda s: abs(by_symbol[s])) if by_symbol else None
    excl_largest = [n for t, n in zip(trades, net) if t["symbol"] != largest_symbol]
    by_regime: dict[str, list[float]] = {}
    for t, n in zip(trades, net):
        by_regime.setdefault(t["btc_regime"], []).append(n)
    return {
        "strategy_version": STRATEGY_VERSION,
        "spec": STRATEGY_SPEC,
        "started_at": repo.version_started_at(),
        "data_status": "VERIFICATION_IN_PROGRESS" if len(trades) < MIN_FORWARD_TRADES else "SUFFICIENT_TRADE_COUNT_SEE_PROMOTION_READINESS",
        "closed_trades": len(trades),
        "open_trades": sum(1 for t in repo.all_trades() if t["status"] == "open"),
        "metric_at_cost": all_cost_metrics,
        "including_largest_contributor": metric(net),
        "excluding_largest_contributor": {"largest_symbol": largest_symbol, **metric(excl_largest)},
        "top_symbol_net_share": round(top_symbol_share, 3) if top_symbol_share is not None else None,
        "concentration_check_passes": (abs(top_symbol_share) <= STRATEGY_SPEC["concentration_cap_pct"] / 100) if top_symbol_share is not None else None,
        "performance_by_btc_regime": {regime: metric(vals) for regime, vals in by_regime.items()},
        "promotion_readiness": promotion_readiness(trades),
        "note": "This status reflects ONLY newly-collected forward data since this version started; the historical PENDING OOS result (PF 3.112) is never counted toward any number here.",
    }


# ---------------------------------------------------------------------------
# Live network fetchers (public, unauthenticated - the ONLY network calls
# this module makes; injected as callables everywhere else so every other
# function above stays testable without real network access).
# ---------------------------------------------------------------------------

def fetch_klines_live(symbol: str, *, limit: int = 60, opener: Callable = urllib.request.urlopen) -> list[tuple]:
    url = KLINES_URL + "?" + urllib.parse.urlencode({"symbol": symbol, "interval": "1m", "limit": limit})
    req = urllib.request.Request(url, headers={"User-Agent": "gaon-crypto-forward-verification/1.0"})
    with opener(req, timeout=15) as resp:
        raw = json.loads(resp.read())
    now_ms = int(time.time() * 1000)
    return [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in raw if int(r[6]) <= now_ms - 30_000]


def fetch_funding_live(symbol: str, *, start_ms: int, opener: Callable = urllib.request.urlopen) -> list[tuple[int, float]]:
    url = FUNDING_URL + "?" + urllib.parse.urlencode({"symbol": symbol, "startTime": start_ms, "limit": 1000})
    req = urllib.request.Request(url, headers={"User-Agent": "gaon-crypto-forward-verification/1.0"})
    with opener(req, timeout=15) as resp:
        raw = json.loads(resp.read())
    return [(int(r["fundingTime"]), float(r["fundingRate"])) for r in raw]


# ---------------------------------------------------------------------------
# The live loop - thin orchestration only; every decision it makes is one
# of the pure functions above, so the loop itself needs no behavioral tests
# beyond "does it call the right pure function and persist the result",
# which the injected-fetcher tests below cover.
# ---------------------------------------------------------------------------

def poll_once(
    repo: CryptoForwardVerificationRepository,
    *,
    fetch_klines: Callable[[str], Sequence[tuple]],
    fetch_funding: Callable[[str, int], Sequence[tuple[int, float]]],
    now_iso: str,
) -> dict[str, object]:
    register_version(repo._connection, now_iso=now_iso)
    for sym in STRATEGY_SPEC["universe"]:
        rows = fetch_klines(sym)
        if rows:
            repo.upsert_bars(sym, rows)

    bars_by_symbol = {sym: to_5m_bars(repo.load_1m_rows(sym)) for sym in STRATEGY_SPEC["universe"]}
    btc_bars = bars_by_symbol.get("BTCUSDT", [])
    hold = int(STRATEGY_SPEC["hold_bars"])
    lookback = int(STRATEGY_SPEC["lookback_bars"])
    liq_window = int(STRATEGY_SPEC["liquidity_window_bars"])
    warmup_needed = lookback + liq_window

    opened, closed = 0, 0
    if len(btc_bars) >= warmup_needed + 1:
        next_idx = repo.next_rebalance_index()
        decision_idx = warmup_needed - 1 + next_idx * hold
        if decision_idx < len(btc_bars) and decision_idx + 1 < len(btc_bars):
            decision = decide_rebalance(bars_by_symbol, decision_idx=decision_idx)
            if decision is not None:
                decision = RebalanceDecision(next_idx, decision.decided_at_ms, decision.eligible_count, decision.picked, decision.btc_regime)
                repo.record_rebalance(decision)
                entry_bar_idx = decision_idx + 1
                exit_bar_idx = entry_bar_idx + hold
                for sym in decision.picked:
                    bars = bars_by_symbol.get(sym, [])
                    if entry_bar_idx >= len(bars):
                        continue
                    repo.open_trade(
                        rebalance_index=next_idx, symbol=sym,
                        entry_time_ms=bars[entry_bar_idx][0], exit_time_ms=btc_bars[exit_bar_idx][0] if exit_bar_idx < len(btc_bars) else bars[entry_bar_idx][0] + hold * 5 * 60_000,
                        entry_price=bars[entry_bar_idx][1], btc_regime=decision.btc_regime,
                    )
                    opened += 1

    latest_ms = btc_bars[-1][0] if btc_bars else int(time.time() * 1000)
    for row in repo.open_trades_due(as_of_ms=latest_ms):
        sym = row["symbol"]
        bars = bars_by_symbol.get(sym, [])
        exit_bar = next((b for b in bars if b[0] >= row["exit_time_ms"]), None)
        if exit_bar is None or row["entry_price"] in (None, 0):
            continue
        price_pct = 100 * (exit_bar[1] / row["entry_price"] - 1)
        funding_events = fetch_funding(sym, row["entry_time_ms"])
        fcost = funding_cost_pct(funding_events, row["entry_time_ms"], row["exit_time_ms"])
        repo.close_trade(rebalance_index=row["rebalance_index"], symbol=sym, exit_price=exit_bar[1], price_pct=price_pct, funding_pct=fcost)
        closed += 1

    return {"opened": opened, "closed": closed, "bars_collected_btc": len(btc_bars), "warmup_needed": warmup_needed}


def run_forever(
    repo: CryptoForwardVerificationRepository,
    *,
    fetch_klines: Callable[[str], Sequence[tuple]] | None = None,
    fetch_funding: Callable[[str, int], Sequence[tuple[int, float]]] | None = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep_fn: Callable[[float], None] = time.sleep,
    sleep_seconds: float = 300.0,
    max_iterations: int | None = None,
) -> None:
    fetch_klines = fetch_klines or (lambda sym: fetch_klines_live(sym))
    fetch_funding = fetch_funding or (lambda sym, start_ms: fetch_funding_live(sym, start_ms=start_ms))
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        try:
            poll_once(repo, fetch_klines=fetch_klines, fetch_funding=fetch_funding, now_iso=now_fn().isoformat())
        except Exception as exc:  # noqa: BLE001 - a transient fetch failure must never crash the service.
            print(f"crypto_forward_verification poll error: {exc.__class__.__name__}: {exc}", flush=True)
        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break
        sleep_fn(sleep_seconds)
