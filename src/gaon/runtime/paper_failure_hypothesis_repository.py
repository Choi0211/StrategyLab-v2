"""SQLite persistence for deterministic failure-analysis hypotheses
generated from closed ``paper_trade_observations`` rows (see
``gaon.research.paper_failure_analysis`` for the pure logic that produces
these, and ``scripts/generate_paper_failure_hypotheses.py`` for the
orchestration that reads observations, calls that logic, and writes here).

Deliberately a separate, typed table from ``research_memories``: a future
backtest/revalidation module needs to query by ``status``/``confidence``/
``trade_count``, not parse a free-text memory blob. This table has no
foreign key into any order/deploy/promotion table and no trigger - it
cannot mutate a strategy, promote a Champion, or place an order.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence

_COLUMNS = (
    "id", "family_id", "hypothesis_id", "fingerprint", "pattern_type", "status",
    "statement", "trade_count", "confidence", "evidence_json", "expected_improvement",
    "verification_required_json", "generated_at", "created_at",
)

_REQUIRED_FIELDS = (
    "family_id", "hypothesis_id", "fingerprint", "pattern_type", "status",
    "statement", "trade_count", "evidence", "verification_required", "generated_at",
)


class PaperFailureHypothesisSQLiteRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert(self, hypothesis: Mapping[str, object], *, created_at: str) -> int:
        """Inserts one hypothesis row. Idempotent on (family_id, fingerprint)
        via a UNIQUE index (schema v47): re-running the generator against
        unchanged evidence returns the EXISTING row's id instead of
        inserting a duplicate - the same pattern as
        ``paper_observation_repository.insert()``. Raises ``KeyError`` if a
        required field is missing."""
        missing = [f for f in _REQUIRED_FIELDS if hypothesis.get(f) in (None, "")]
        if missing:
            raise KeyError(f"missing required hypothesis field(s): {missing}")
        family_id = str(hypothesis["family_id"])
        fingerprint = str(hypothesis["fingerprint"])
        try:
            cur = self._connection.execute(
                """
                INSERT INTO paper_failure_hypotheses (
                    family_id, hypothesis_id, fingerprint, pattern_type, status,
                    statement, trade_count, confidence, evidence_json, expected_improvement,
                    verification_required_json, generated_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    family_id,
                    str(hypothesis["hypothesis_id"]),
                    fingerprint,
                    str(hypothesis["pattern_type"]),
                    str(hypothesis["status"]),
                    str(hypothesis["statement"]),
                    int(hypothesis["trade_count"]),
                    _opt_float(hypothesis.get("confidence")),
                    json.dumps(hypothesis["evidence"], sort_keys=True),
                    _opt_str(hypothesis.get("expected_improvement")),
                    json.dumps(list(hypothesis["verification_required"])),
                    str(hypothesis["generated_at"]),
                    created_at,
                ),
            )
        except sqlite3.IntegrityError:
            self._connection.rollback()
            existing = self._connection.execute(
                "SELECT id FROM paper_failure_hypotheses WHERE family_id = ? AND fingerprint = ?",
                (family_id, fingerprint),
            ).fetchone()
            if existing is None:
                raise
            return int(existing[0])
        self._connection.commit()
        return int(cur.lastrowid)

    def list_for_family(self, family_id: str, *, limit: int = 50) -> Sequence[Mapping[str, object]]:
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM paper_failure_hypotheses "
            "WHERE family_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (family_id, int(limit)),
        ).fetchall()
        return [_to_dict(row) for row in rows]

    def list_candidates_for_family(self, family_id: str, *, limit: int = 50) -> Sequence[Mapping[str, object]]:
        """Only ``status='candidate'`` rows - what a future backtest module
        would actually consume (an 'insufficient_evidence' row is not
        actionable yet)."""
        rows = self._connection.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM paper_failure_hypotheses "
            "WHERE family_id = ? AND status = 'candidate' ORDER BY created_at DESC, id DESC LIMIT ?",
            (family_id, int(limit)),
        ).fetchall()
        return [_to_dict(row) for row in rows]


def _to_dict(row: Sequence[object]) -> dict[str, object]:
    d = dict(zip(_COLUMNS, row))
    d["evidence"] = json.loads(d.pop("evidence_json"))
    d["verification_required"] = json.loads(d.pop("verification_required_json"))
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
