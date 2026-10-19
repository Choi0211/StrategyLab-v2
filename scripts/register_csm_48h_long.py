#!/usr/bin/env python3
"""Standalone promotion script for family_id="csm-48h-long".

Why standalone: ``gaon.runtime.web_api``'s ``POST
/gaon/strategy/version/activate`` is hardcoded to always refuse
("authenticated strategy approval workflow required") - there is, by
design, no live HTTP path to ever write an ACTIVE strategy version. The
only way to populate ``strategy_version_registries`` is this kind of
direct, reviewed, one-off script using ``gaon.control.strategy_version``
and ``gaon.runtime.strategy_version_repository`` directly. This script
is that one-off - run it once, by hand, after a human (or the agent
that wrote it) has reviewed the spec/validation summary below.

What this registers is NOT a validated strategy. The research finding
(``/opt/binance-trading/research/claude_cross_sectional_momentum_v2_20261019/``)
is: a 48h (576x5m-bar) trailing-return cross-sectional rank, top-quartile
long-only book, passed its own automated promotion gate on the OOS fold
(n=130, PF=3.11) - but a due-diligence pass found that OOS fold is a
single, atypical BTC regime (+29.74% over the same 53-day window), with
QNTUSDT alone contributing 28-34% of OOS net profit and the top 3 symbols
60-65%. The research's own conclusion was explicitly PENDING, not
CANDIDATE: "requires independent out-of-regime verification." Its own
stated next step is to run the rule forward in real time (i.e. in Paper)
to see if it holds up outside that one regime. Registering it here as
ACTIVE/LONG for family_id "csm-48h-long" is exactly that: it makes the
rule readable by binance-trading's Paper loop via
``GET /gaon/strategy/version_status?family_id=csm-48h-long`` so results
can accumulate and be judged later - it is NOT a claim that the strategy
is validated, and ``validation_summary.status_note`` says so explicitly
in the registry record itself.

This script never touches family_id "binance-price-action" (Live's
existing canonical-gate family) and never calls anything in
``gaon.adapters.paper_revalidation`` / ``champion_registry`` (wrong fit -
see the module docstring of ``gaon.runtime.paper_observation_repository``).

Usage:
    cd /opt/strategylab-v2
    .venv/bin/python scripts/register_csm_48h_long.py [--db PATH] [--dry-run]

Default --db is /var/lib/strategylab/gaon-runtime.sqlite. Idempotent: if
an ACTIVE LONG version with this exact spec_fingerprint already exists,
this is a no-op (prints that fact, exits 0).

IMPORTANT: this script does NOT run migrations. It calls
``check_schema_version_compatible`` (fail-closed) first - if the schema
hasn't been migrated to this build's SCHEMA_VERSION yet, it refuses to
run rather than race the migration-owner process (``strategylab-gaon.service``
/ ``gaon-web.service``, whichever is started with the new code first).
Deploy + restart those services BEFORE running this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaon.control.strategy_version import StrategyVersionRegistry  # noqa: E402
from gaon.runtime.errors import SchemaVersionMismatchError  # noqa: E402
from gaon.runtime.migrations import check_schema_version_compatible  # noqa: E402
from gaon.runtime.strategy_version_repository import StrategyVersionSQLiteRepository  # noqa: E402

FAMILY_ID = "csm-48h-long"
DEFAULT_DB_PATH = "/var/lib/strategylab/gaon-runtime.sqlite"

SPEC_RULES = {
    "rule": "cross_sectional_momentum",
    "direction": "LONG",
    "bar_interval": "5m",
    "lookback_bars": 576,
    "lookback_hours": 48,
    "holding_period_bars": 576,
    "holding_period_hours": 48,
    "ranking_metric": "trailing_return = close[i] / close[i - 576] - 1",
    "selection": "top_quartile (ceil(n_eligible / 4)) of eligible universe, descending by ranking_metric",
    "universe": "23 symbols with >=7mo local 1m cache (incl. BTC/ETH/SOL)",
    "liquidity_filter": "exclude symbol if trailing 7-day mean 5m dollar-volume < $50,000",
    "entry_timing": "next bar's open after rebalance bar i (no lookahead)",
    "exit_timing": "time-based only, at bar i+1+576's open (= next rebalance's entry, no stop/target)",
    "cost_model": "round-trip 0.17% / 0.30% / 0.40% variants + real historical Binance funding, pro-rated over the hold",
    "source_research_dir": "/opt/binance-trading/research/claude_cross_sectional_momentum_v2_20261019/",
}

VALIDATION_SUMMARY = {
    "status_note": "PENDING - requires independent out-of-regime verification via live Paper forward testing",
    "promotion_gate_result": "numerically passed the automated OOS gate (n>=100, PF>1.2, positive mean%, at all 3 costs, single-symbol<=40% of net profit)",
    "training_folds_pf": [1.228, 1.361, 0.712],
    "training_trade_count": 370,
    "oos_trade_count": 130,
    "oos_profit_factor": 3.11,
    "oos_window": "2026-08-07 to 2026-09-28 (~53 days)",
    "concentration_risk": {
        "single_trade_pct_of_oos_net_profit": "28-34% (QNTUSDT)",
        "top_3_symbols_pct_of_oos_net_profit": "60-65%",
        "regime_note": "entire OOS fold overlaps a single atypical BTC +29.74% run - the automated gate's PF=3.11 pass does not rule out the result being a single-regime artifact",
    },
    "due_diligence_script": "due_diligence_48h_long_oos.py",
    "recommended_next_step": "run the rule in Paper (forward, real-time) across whatever market regime actually occurs next, and judge on that forward evidence - which is exactly what registering this ACTIVE for family_id=csm-48h-long and wiring it into binance-trading's Paper loop accomplishes",
    "registered_as": "forward-verification (Paper-only), NOT a validated/promotable strategy",
}


def _spec_fingerprint() -> str:
    canonical = json.dumps(SPEC_RULES, sort_keys=True)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--dry-run", action="store_true", help="print what would happen, write nothing")
    args = parser.parse_args(argv)

    fingerprint = _spec_fingerprint()
    now = _now()

    connection = sqlite3.connect(args.db)
    try:
        try:
            check_schema_version_compatible(connection)
        except SchemaVersionMismatchError as exc:
            print(f"[ABORT] {exc}", file=sys.stderr)
            print(
                "This database has not been migrated to this build's schema yet. "
                "Deploy the new code and restart strategylab-gaon.service / gaon-web.service "
                "(whichever starts first becomes the migration owner) BEFORE running this script.",
                file=sys.stderr,
            )
            return 2

        repository = StrategyVersionSQLiteRepository(connection)
        registry = repository.get(FAMILY_ID)

        existing_active = registry.active("LONG")
        if existing_active is not None and existing_active.spec_fingerprint == fingerprint:
            print(
                f"[NO-OP] family_id={FAMILY_ID!r} already has ACTIVE LONG "
                f"strategy_version_id={existing_active.strategy_version_id!r} "
                f"with this exact spec_fingerprint ({fingerprint}). Nothing to do."
            )
            return 0

        if args.dry_run:
            print(f"[DRY-RUN] would register_apply_ready + mark_active for family_id={FAMILY_ID!r}")
            print(f"[DRY-RUN] spec_fingerprint={fingerprint}")
            print(f"[DRY-RUN] spec_rules={json.dumps(SPEC_RULES, indent=2, sort_keys=True)}")
            return 0

        candidate_id = f"candidate:{FAMILY_ID}:{fingerprint[:12]}"
        version = registry.register_apply_ready(
            family_id=FAMILY_ID,
            candidate_id=candidate_id,
            spec_fingerprint=fingerprint,
            spec_rules=SPEC_RULES,
            validation_summary=VALIDATION_SUMMARY,
            at=now,
            direction="LONG",
        )
        registry.mark_active(version.strategy_version_id, at=now)
        repository.save(FAMILY_ID, registry, now=now)

        print("[OK] registered and activated:")
        print(f"  family_id            = {FAMILY_ID}")
        print(f"  strategy_version_id  = {version.strategy_version_id}")
        print(f"  display_id           = {version.display_id}")
        print(f"  spec_fingerprint     = {fingerprint}")
        print(f"  status               = ACTIVE (LONG)")
        print(f"  validation status    = {VALIDATION_SUMMARY['status_note']}")
        return 0
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
