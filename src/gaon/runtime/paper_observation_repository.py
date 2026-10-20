"""SQLite persistence for Paper-trading strategy observations reported by
an EXTERNAL execution engine (binance-trading's Paper loop) via
``POST /gaon/paper/report``.

Deliberately separate from ``gaon.adapters.paper_revalidation`` /
``champion_registry`` / ``paper_trading_sessions``: that subsystem is
purpose-built for the KR-equities Champion promotion workflow
(fingerprint-matched ``ChampionRegistryEntry``, LIVE_ELIGIBLE/HOLD/KILL
rules) and does not fit a ``StrategyVersionRegistry``-keyed crypto
family. This module is a plain, append-only observation ledger - one row
per reported stage (signal_only / entry_blocked / open / closed / error)
- that a future crypto-specific revalidation rule can read. It performs
no promotion, no ACTIVE mutation, and only ever INSERTs - never UPDATEs
or DELETEs a row, so every reported stage stays in the audit trail.

See the table this backs: ``gaon.runtime.migrations._upgrade_v44_to_v45``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence

_COLUMNS = (
    "id", "family_id", "strategy_version_id", "spec_fingerprint", "direction", "symbol",
    "signal_at", "entry_at", "exit_at", "entry_price", "exit_price", "qty",
    "pnl", "pnl_pct", "fees", "status", "reason", "reported_at", "created_at",
)

_REQUIRED_FIELDS = (
    "family_id", "strategy_version_id", "spec_fingerprint", "direction", "symbol",
    "signal_at", "status",
)

class PaperObservationSQLiteRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, observation: Mapping[str, object], *, created_at: str) -> int:
        """Inserts one observation row. ``reported_at`` defaults to
        ``created_at`` (the server-assigned report time) when the caller's
        body doesn't carry its own - no caller is required to supply it.
        Raises ``KeyError`` if a genuinely required field is missing -
        callers (the HTTP handler) must validate first and turn that into
        a 400, never let it surface as a 500.

        Idempotent on (family_id, symbol, status, entry_at, exit_at) via a
        UNIQUE index (schema v46): a retried report of the exact same trade
        stage - e.g. the reporting client timed out waiting for a response
        this call had already committed, then resent the identical payload -
        returns the EXISTING row's id instead of inserting a second row and
        double-counting it in aggregate_for_family(). A different payload
        that happens to collide on this same identity is not expected and
        is not specially handled - the existing row wins, nothing is
        overwritten."""
        missing = [f for f in _REQUIRED_FIELDS if observation.get(f) in (None, "")]
        if missing:
            raise KeyError(f"missing required observation field(s): {missing}")
        reported_at = _opt_str(observation.get("reported_at")) or created_at
        entry_at = _opt_str(observation.get("entry_at"))
        exit_at = _opt_str(observation.get("exit_at"))
        try:
            cur = self._connection.execute(
                """
                INSERT INTO paper_trade_observations (
                    family_id, strategy_version_id, spec_fingerprint, direction, symbol,
                    signal_at, entry_at, exit_at, entry_price, exit_price, qty,
                    pnl, pnl_pct, fees, status, reason, reported_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(observation["family_id"]),
                    str(observation["strategy_version_id"]),
                    str(observation["spec_fingerprint"]),
                    str(observation["direction"]),
                    str(observation["symbol"]),
                    str(observation["signal_at"]),
                    entry_at,
                    exit_at,
                    _opt_float(observation.get("entry_price")),
                    _opt_float(observation.get("exit_price")),
                    _opt_float(observation.get("qty")),
                    _opt_float(observation.get("pnl")),
                    _opt_float(observation.get("pnl_pct")),
                    _opt_float(observation.get("fees")),
                    str(observation["status"]),
                    _opt_str(observation.get("reason")),
                    reported_at,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError:
            self._connection.rollback()
            existing = self._connection.execute(
                "SELECT id FROM paper_trade_observations "
                "WHERE family_id = ? AND symbol = ? AND status = ? AND entry_at = ? AND exit_at = ?",
                (str(observation["family_id"]), str(observation["symbol"]), str(observation["status"]), entry_at, exit_at),
            ).fetchone()
            if existing is None:
                raise
            return int(existing[0])
        self._connection.commit()
        return int(cur.lastrowid)

    def list_for_family(self, family_id: str, *, limit: int = 50) -> Sequence[Mapping[str, object]]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM paper_trade_observations "
            "WHERE family_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (family_id, int(limit)),
        ).fetchall()
        return [dict(zip(_COLUMNS, row)) for row in rows]

    def aggregate_for_family(self, family_id: str) -> Mapping[str, object]:
        closed_rows = self._connection.execute(
            "SELECT pnl, pnl_pct FROM paper_trade_observations "
            "WHERE family_id = ? AND status = 'closed' AND pnl IS NOT NULL",
            (family_id,),
        ).fetchall()
        pnls = [float(r[0]) for r in closed_rows]
        pnl_pcts = [float(r[1]) for r in closed_rows if r[1] is not None]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gross_profit = sum(wins)
        gross_loss = -sum(losses)
        status_rows = self._connection.execute(
            "SELECT status, COUNT(*) FROM paper_trade_observations WHERE family_id = ? GROUP BY status",
            (family_id,),
        ).fetchall()
        return {
            "family_id": family_id,
            "closed_trade_count": len(pnls),
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": (len(wins) / len(pnls)) if pnls else None,
            # None (undefined), never +inf: a zero-loss profit factor has
            # no finite ratio and +Infinity is not valid strict JSON.
            "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else None,
            "mean_pnl": (sum(pnls) / len(pnls)) if pnls else None,
            "mean_pnl_pct": (sum(pnl_pcts) / len(pnl_pcts)) if pnl_pcts else None,
            "total_pnl": sum(pnls) if pnls else 0.0,
            "status_counts": {str(s): int(c) for s, c in status_rows},
        }


def _opt_str(value: object) -> str | None:
    return str(value) if value is not None else None


def _opt_float(value: object) -> float | None:
    return float(value) if value is not None else None
