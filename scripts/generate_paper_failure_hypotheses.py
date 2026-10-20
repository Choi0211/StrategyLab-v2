#!/usr/bin/env python3
"""Gaon<->Paper failure-analysis job: reads closed `paper_trade_observations`
for a family, runs the deterministic comparisons in
`gaon.research.paper_failure_analysis`, and persists the resulting
hypotheses to `paper_failure_hypotheses` - idempotent via each
hypothesis's own fingerprint (re-running on unchanged evidence is a
no-op). Also writes one companion `research_memories` entry per run (not
per hypothesis) summarizing the findings, purely so they're discoverable
through the existing `research_memory_search` tool Gaon's research/
conversation engine already uses.

This script only reads and appends - it never touches
`strategy_version_registries`, never backtests, never promotes anything.
See `gaon.research.paper_failure_analysis`'s module docstring for what a
later stage (backtest / forward-revalidation / promotion) would add on
top, without needing to change this script.

Meant to be run on a schedule (a systemd timer, installed separately -
this script takes no required args and is safe to invoke repeatedly).

Usage:
    cd /opt/strategylab-v2
    .venv/bin/python scripts/generate_paper_failure_hypotheses.py [--family-id ID] [--db PATH]

Exit codes: 0 on success (including the normal "nothing new" no-op).
Non-zero with a clear stderr message only on a genuine failure.
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

from gaon.research.paper_failure_analysis import collect_trade_records, generate_hypotheses  # noqa: E402
from gaon.research.self_improving import ResearchMemoryEntry, SQLiteResearchMemoryRepository  # noqa: E402
from gaon.runtime.errors import SchemaVersionMismatchError  # noqa: E402
from gaon.runtime.migrations import check_schema_version_compatible  # noqa: E402
from gaon.runtime.paper_failure_hypothesis_repository import PaperFailureHypothesisSQLiteRepository  # noqa: E402
from gaon.runtime.paper_observation_repository import PaperObservationSQLiteRepository  # noqa: E402

DEFAULT_DB_PATH = "/var/lib/strategylab/gaon-runtime.sqlite"
DEFAULT_FAMILY_ID = "csm-48h-long"
STRATEGY_FAMILY_TAG = "csm_48h_long_paper_failure_analysis"
# Large enough to cover every closed trade likely to exist for a single
# forward-verification family for a long time; not unbounded so a
# pathological DB can't make this read unboundedly large.
MAX_OBSERVATIONS_CONSIDERED = 5000


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _run_fingerprint(family_id: str, hypothesis_fingerprints: list[str]) -> str:
    canonical = json.dumps({"family_id": family_id, "hypotheses": sorted(hypothesis_fingerprints)}, sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _memory_summary(hypotheses) -> str:
    if not hypotheses:
        return "No hypotheses generated this run."
    lines = []
    for h in hypotheses:
        tag = "CANDIDATE" if h.status == "candidate" else "insufficient_evidence"
        lines.append(f"[{tag}] ({h.pattern_type}) {h.statement}")
    return " | ".join(lines)


def run(db_path: str, family_id: str) -> int:
    connection = sqlite3.connect(db_path)
    try:
        try:
            check_schema_version_compatible(connection)
        except SchemaVersionMismatchError as exc:
            print(f"[ABORT] {exc}", file=sys.stderr)
            return 2

        observations_repo = PaperObservationSQLiteRepository(connection)
        observations = observations_repo.list_for_family(family_id, limit=MAX_OBSERVATIONS_CONSIDERED)
        records = collect_trade_records(observations)

        now = _now()
        hypotheses = generate_hypotheses(family_id, records, now=now)

        hyp_repo = PaperFailureHypothesisSQLiteRepository(connection)
        inserted, noop = 0, 0
        before_ids = {h["fingerprint"]: h["id"] for h in hyp_repo.list_for_family(family_id, limit=MAX_OBSERVATIONS_CONSIDERED)}
        for h in hypotheses:
            row_id = hyp_repo.insert(h.to_dict(), created_at=now)
            if before_ids.get(h.fingerprint) == row_id:
                noop += 1
            else:
                inserted += 1

        run_fingerprint = _run_fingerprint(family_id, [h.fingerprint for h in hypotheses])
        memory_repo = SQLiteResearchMemoryRepository(connection)
        existing_memory = memory_repo.find_by_fingerprint(run_fingerprint)
        if existing_memory is None:
            candidate_count = sum(1 for h in hypotheses if h.status == "candidate")
            entry = ResearchMemoryEntry(
                memory_id=f"memory:{family_id}:failure-analysis:{uuid4().hex}",
                strategy_family=STRATEGY_FAMILY_TAG,
                market="BINANCE",
                timeframe="5m",
                hypothesis=(
                    "Deterministic failure-analysis over closed csm-48h-long Paper trades - compares "
                    "win vs loss characteristics (symbol concentration, fee drag, early-exit vs "
                    "scheduled-exit) to flag suspicious patterns worth independently verifying."
                ),
                result_summary=_memory_summary(hypotheses),
                critic_summary=(
                    "Rule-based pattern detection, not a statistical significance test - confidence is a "
                    "linear sample-size heuristic only. No hypothesis here has been backtested or "
                    "independently re-validated in Paper; see paper_failure_hypotheses for the full "
                    "structured record (evidence, trade_count, verification_required)."
                ),
                improvement_summary=(
                    f"{candidate_count} candidate hypothesis(es) this run - each lists its own "
                    "verification_required steps. Never auto-apply; never promote."
                ),
                final_status="PENDING_FORWARD_VERIFICATION",
                tags=(family_id, "paper-failure-analysis", "pending"),
                created_at=now,
                source_run_id=f"generate_paper_failure_hypotheses:{now}",
                fingerprint=run_fingerprint,
                source_refs=(f"gaon-web:/gaon/paper/summary?family_id={family_id}",),
            )
            memory_repo.add_memory(entry)
            print(f"[OK] recorded research memory: memory_id={entry.memory_id} fingerprint={run_fingerprint}")
        else:
            print(f"[NO-OP] research memory unchanged since memory_id={existing_memory.memory_id!r}")

        print(f"[OK] hypotheses: {len(hypotheses)} generated ({inserted} new, {noop} unchanged/idempotent)")
        for h in hypotheses:
            print(f"     [{h.status}] ({h.pattern_type}) {h.statement}")
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
        print(f"[ERROR] generate_paper_failure_hypotheses failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
