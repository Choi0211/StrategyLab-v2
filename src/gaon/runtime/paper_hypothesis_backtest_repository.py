"""SQLite persistence for backtest results against a
``paper_failure_hypotheses`` row (see ``gaon_hypothesis_backtest.py`` in
the binance-trading repo for the resource-limited job that produces
these, reading candidates via ``GET /gaon/paper/failure_hypotheses`` and
reporting here via ``POST /gaon/paper/hypothesis_backtest_result``).

Records data provenance (source, period, fee assumption, whether a
genuine out-of-sample fold was used) alongside the verdict, so a result
built on thin or stale assumptions is visibly distinguishable from a
properly validated one. This table has no foreign key into
``strategy_version_registries`` and no trigger - it cannot promote or
activate a strategy by itself. Only ``verdict='pass'`` rows are eligible
for ``list_passed_for_family()`` - the human-reviewed Paper-revalidation
queue; nothing in this module ever activates anything automatically.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence

_COLUMNS = (
    "id", "family_id", "hypothesis_id", "hypothesis_fingerprint", "backtest_fingerprint",
    "verdict", "metrics_json", "data_source", "data_period_start", "data_period_end",
    "symbols_processed", "fee_assumption_pct", "slippage_note", "oos_validated",
    "tested_at", "created_at",
)

_REQUIRED_FIELDS = (
    "family_id", "hypothesis_id", "hypothesis_fingerprint", "backtest_fingerprint",
    "verdict", "metrics", "data_source", "tested_at",
)

VALID_VERDICTS = ("pass", "fail", "insufficient_data", "needs_revalidation")


class PaperHypothesisBacktestSQLiteRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, result: Mapping[str, object], *, created_at: str) -> int:
        """Inserts one backtest-result row. Idempotent on
        (family_id, backtest_fingerprint) via a UNIQUE index (schema v48):
        re-reporting an unchanged result returns the EXISTING row's id,
        same pattern as the observation/hypothesis repositories. Raises
        ``KeyError`` for a missing required field, ``ValueError`` for an
        unrecognized ``verdict``."""
        missing = [f for f in _REQUIRED_FIELDS if result.get(f) in (None, "")]
        if missing:
            raise KeyError(f"missing required backtest result field(s): {missing}")
        verdict = str(result["verdict"])
        if verdict not in VALID_VERDICTS:
            raise ValueError(f"verdict must be one of {VALID_VERDICTS}, got {verdict!r}")
        family_id = str(result["family_id"])
        backtest_fingerprint = str(result["backtest_fingerprint"])
        try:
            cur = self._connection.execute(
                """
                INSERT INTO paper_hypothesis_backtests (
                    family_id, hypothesis_id, hypothesis_fingerprint, backtest_fingerprint,
                    verdict, metrics_json, data_source, data_period_start, data_period_end,
                    symbols_processed, fee_assumption_pct, slippage_note, oos_validated,
                    tested_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    family_id,
                    str(result["hypothesis_id"]),
                    str(result["hypothesis_fingerprint"]),
                    backtest_fingerprint,
                    verdict,
                    json.dumps(result["metrics"], sort_keys=True),
                    str(result["data_source"]),
                    _opt_str(result.get("data_period_start")),
                    _opt_str(result.get("data_period_end")),
                    _opt_int(result.get("symbols_processed")),
                    _opt_float(result.get("fee_assumption_pct")),
                    _opt_str(result.get("slippage_note")),
                    1 if result.get("oos_validated") else 0,
                    str(result["tested_at"]),
                    created_at,
                ),
            )
        except sqlite3.IntegrityError:
            self._connection.rollback()
            existing = self._connection.execute(
                "SELECT id FROM paper_hypothesis_backtests WHERE family_id = ? AND backtest_fingerprint = ?",
                (family_id, backtest_fingerprint),
            ).fetchone()
            if existing is None:
                raise
            return int(existing[0])
        self._connection.commit()
        return int(cur.lastrowid)

    def list_for_family(self, family_id: str, *, limit: int = 50) -> Sequence[Mapping[str, object]]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM paper_hypothesis_backtests "
            "WHERE family_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (family_id, int(limit)),
        ).fetchall()
        return [_to_dict(row) for row in rows]

    def list_for_hypothesis(self, family_id: str, hypothesis_fingerprint: str, *, limit: int = 20) -> Sequence[Mapping[str, object]]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM paper_hypothesis_backtests "
            "WHERE family_id = ? AND hypothesis_fingerprint = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (family_id, hypothesis_fingerprint, int(limit)),
        ).fetchall()
        return [_to_dict(row) for row in rows]

    def list_passed_for_family(self, family_id: str, *, limit: int = 50) -> Sequence[Mapping[str, object]]:
        """Only `verdict='pass'` rows - candidates eligible for a human to
        manually wire into a fresh Paper forward-revalidation run (same
        reviewed, one-off-script convention as
        `scripts/register_csm_48h_long.py`). Nothing reads this and
        auto-activates anything."""
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM paper_hypothesis_backtests "
            "WHERE family_id = ? AND verdict = 'pass' ORDER BY created_at DESC, id DESC LIMIT ?",
            (family_id, int(limit)),
        ).fetchall()
        return [_to_dict(row) for row in rows]

    def get_by_backtest_fingerprint(self, family_id: str, backtest_fingerprint: str) -> Mapping[str, object] | None:
        """Looks up one exact, already-recorded backtest row by its own
        (family_id, backtest_fingerprint) - the same unique pair `insert`
        upserts on. Used by `register_hypothesis_candidate` (see
        `gaon.runtime.web_api`) to require that a strategy-version
        candidate can ONLY be derived from a real, already-stored verdict
        - never from a caller-supplied claim - so that writer can't be
        used to assert its own spec_rules/validation_summary out of thin
        air."""
        row = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM paper_hypothesis_backtests "
            "WHERE family_id = ? AND backtest_fingerprint = ?",
            (family_id, backtest_fingerprint),
        ).fetchone()
        return _to_dict(row) if row else None


def _to_dict(row: Sequence[object]) -> dict[str, object]:
    d = dict(zip(_COLUMNS, row))
    d["metrics"] = json.loads(d.pop("metrics_json"))
    d["oos_validated"] = bool(d["oos_validated"])
    return d


def _opt_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.strip() else None


def _opt_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _opt_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
