#!/usr/bin/env python3
"""Gaon<->Paper feedback job: summarizes ``paper_trade_observations`` for a
family_id into a ``research_memories`` row, closing the research loop
(Paper results become something the next research cycle can read back via
``gaon.research.self_improving.SQLiteResearchMemoryRepository.search(...)``
/ ``gaon.runtime.llm_tools``'s ``research_memory_search`` tool).

Deliberately reuses the existing ``ResearchMemoryEntry`` /
``SQLiteResearchMemoryRepository`` contract rather than inventing a new
format other readers don't understand.

Idempotent by construction: the memory's ``fingerprint`` is derived from
(family_id, aggregate snapshot). If nothing changed since the last run
(no new closed trades), the fingerprint is identical and
``find_by_fingerprint`` makes this a no-op - never an error, never a
duplicate row. A new fingerprint (because the aggregate changed) appends
a NEW memory row; existing rows are never edited or deleted, preserving
the full history the research loop can compare across.

Meant to be run on a schedule (a systemd timer, installed separately -
this script takes no required args and is safe to invoke repeatedly).

Usage:
    cd /opt/strategylab-v2
    .venv/bin/python scripts/summarize_paper_observations.py [--family-id ID] [--db PATH]

Exit codes: 0 on success (including the normal "no new observations"
no-op). Non-zero with a clear stderr message only on a genuine failure
(bad DB path, schema not migrated, etc.) - this must never raise on the
ordinary "nothing changed" case, since a timer treats any non-zero exit
as a job failure worth alerting on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaon.research.self_improving import ResearchMemoryEntry, SQLiteResearchMemoryRepository  # noqa: E402
from gaon.runtime.errors import SchemaVersionMismatchError  # noqa: E402
from gaon.runtime.migrations import check_schema_version_compatible  # noqa: E402
from gaon.runtime.paper_observation_repository import PaperObservationSQLiteRepository  # noqa: E402

DEFAULT_DB_PATH = "/var/lib/strategylab/gaon-runtime.sqlite"
DEFAULT_FAMILY_ID = "csm-48h-long"
STRATEGY_FAMILY_TAG = "csm_48h_long_paper_forward"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _fingerprint(family_id: str, aggregate: dict) -> str:
    canonical = json.dumps({"family_id": family_id, "aggregate": aggregate}, sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _summarize(aggregate: dict) -> str:
    if aggregate["closed_trade_count"] == 0:
        return "No closed Paper trades reported yet for this family."
    pf = aggregate["profit_factor"]
    pf_text = f"{pf:.3f}" if pf is not None else "undefined (no losing trades yet)"
    return (
        f"{aggregate['closed_trade_count']} closed Paper trades so far: "
        f"win_rate={aggregate['win_rate']:.3f}, profit_factor={pf_text}, "
        f"mean_pnl_pct={aggregate['mean_pnl_pct']}, total_pnl={aggregate['total_pnl']}. "
        f"Status breakdown: {aggregate['status_counts']}."
    )


def run(db_path: str, family_id: str) -> int:
    connection = sqlite3.connect(db_path)
    try:
        try:
            check_schema_version_compatible(connection)
        except SchemaVersionMismatchError as exc:
            print(f"[ABORT] {exc}", file=sys.stderr)
            return 2

        observations = PaperObservationSQLiteRepository(connection)
        aggregate = dict(observations.aggregate_for_family(family_id))

        memory_repo = SQLiteResearchMemoryRepository(connection)
        fingerprint = _fingerprint(family_id, aggregate)
        existing = memory_repo.find_by_fingerprint(fingerprint)
        if existing is not None:
            print(
                f"[NO-OP] family_id={family_id!r}: aggregate unchanged since memory_id={existing.memory_id!r} "
                f"(fingerprint={fingerprint}). Nothing new to record."
            )
            return 0

        now = _now()
        entry = ResearchMemoryEntry(
            memory_id=f"memory:{family_id}:{uuid4().hex}",
            strategy_family=STRATEGY_FAMILY_TAG,
            market="BINANCE",
            timeframe="5m",
            hypothesis=(
                "48h cross-sectional momentum LONG (family_id=csm-48h-long) was registered PENDING "
                "(single-regime OOS concentration risk) for forward verification in Paper - this memory "
                "tracks its live forward performance so the next research cycle can judge whether it "
                "holds up outside the original OOS regime."
            ),
            result_summary=_summarize(aggregate),
            critic_summary=(
                "Not yet independently re-validated; this is raw forward-Paper evidence accumulating "
                "over time, not a promotion decision. See spec_fingerprint-linked strategy_version_registries "
                "entry for the original due-diligence concentration-risk finding."
            ),
            improvement_summary=(
                "Accumulate more closed trades across varied regimes before any promotion decision; "
                "watch for the same single-symbol/top-3 concentration pattern found in the original OOS fold."
            ),
            final_status="PENDING_FORWARD_VERIFICATION",
            tags=("csm-48h-long", "paper-forward", "pending"),
            created_at=now,
            source_run_id=f"summarize_paper_observations:{now}",
            fingerprint=fingerprint,
            source_refs=(f"gaon-web:/gaon/paper/summary?family_id={family_id}",),
        )
        memory_repo.add_memory(entry)
        print(f"[OK] recorded new research memory: memory_id={entry.memory_id} fingerprint={fingerprint}")
        print(f"     {entry.result_summary}")
        return 0
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--family-id", default=DEFAULT_FAMILY_ID)
    args = parser.parse_args(argv)
    try:
        return run(args.db, args.family_id)
    except Exception as exc:  # noqa: BLE001 - last-resort guard for a timer job
        print(f"[ERROR] summarize_paper_observations failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
