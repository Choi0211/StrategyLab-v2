"""Research candidate -> ``StrategyVersionRegistry`` (APPLY_READY) bridge.

``gaon.research.multi_symbol``'s own ``final_recommendation`` field
("candidate_preferred" / "original_preferred" / "no_clear_winner" /
"needs_more_evidence") is a RELATIVE judgement: it only says the tested
candidate beat the baseline it was compared against, including when both
are losing money. A run can be "candidate_preferred" with a negative
median return and most symbols unprofitable. This module adds the missing
ABSOLUTE bar - real, positive, broad-sample profitability - before a
research run is even offered to a human as a registry candidate.

Scope, deliberately narrow (see docs/architecture/GaonStrategyRollbackContract.md):
  - Reads only ``multi_symbol_research_runs`` (via the existing
    ``SQLiteMultiSymbolResearchRepository``, which already excludes
    release-check/demo artifact runs).
  - Writes only ``StrategyVersionRegistry`` entries at status APPLY_READY,
    via the existing ``StrategyVersionSQLiteRepository``. Never calls
    ``mark_active``: APPLY_READY grants no trading power by itself and
    still requires the passkey-signed admin approval flow in
    ``gaon.runtime.web_api`` to become ACTIVE.
  - Never touches ``gaon.adapters.binance``, live order state, or any
    other market's research tables.
  - Idempotent: a research run is never registered twice (deduped by
    ``candidate_id`` == ``run_id`` within the target family).
  - Not wired into any always-on service loop. Call
    ``promote_eligible_candidates`` explicitly (CLI or an admin action).

``direction`` is intentionally left unset (``None``): this research track
(KR equity day-trading candidates) does not yet label LONG/SHORT, and
guessing would misrepresent the strategy. A human reviewing the apply_ready
list assigns direction when/if the strategy is adapted for a directional
family.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Mapping

from gaon.control.strategy_version import StrategyVersionRegistry, StrategyVersion
from gaon.research.multi_symbol import SQLiteMultiSymbolResearchRepository
from gaon.runtime.strategy_version_repository import StrategyVersionSQLiteRepository

# Absolute promotion bar. All must hold; every threshold is deliberately
# strict because the only cost of a false negative is "a human reviews one
# fewer candidate this cycle," while a false positive puts a losing or
# thin-sample strategy in front of the passkey approval flow.
MIN_TRADE_COUNT = 30
MIN_PROFITABLE_SYMBOL_RATIO = 0.5
REQUIRED_SAMPLE_CONFIDENCE = "high"
ALLOWED_CONCENTRATION = frozenset({"broad", "moderately_concentrated"})
REQUIRED_RECOMMENDATION = "candidate_preferred"


@dataclass(frozen=True)
class PromotionDecision:
    run_id: str
    eligible: bool
    reason: str
    family_id: str | None = None
    spec_fingerprint: str | None = None


def _family_id_for_strategy(strategy: Mapping[str, object]) -> str:
    """Group research runs that tune the same strategy shape into one
    family, independent of the specific parameter values tried."""
    entry_keys = sorted((strategy.get("entry") or {}).keys())
    exit_keys = sorted((strategy.get("exit") or {}).keys())
    return "kr-equity-research:" + "-".join(entry_keys) + "__" + "-".join(exit_keys)


def evaluate_run(payload: Mapping[str, object]) -> PromotionDecision:
    """Pure function: apply the absolute promotion bar to one research
    run's full payload (as returned by
    ``SQLiteMultiSymbolResearchRepository.get_payload``)."""
    run_id = str(payload.get("run_id"))
    if payload.get("final_recommendation") != REQUIRED_RECOMMENDATION:
        return PromotionDecision(run_id, False, "recommendation is not candidate_preferred")

    summary = dict(payload.get("summary") or {})
    if summary.get("sample_confidence") != REQUIRED_SAMPLE_CONFIDENCE:
        return PromotionDecision(run_id, False, "sample_confidence is not high")

    if summary.get("concentration_decision") not in ALLOWED_CONCENTRATION:
        return PromotionDecision(run_id, False, "symbol/return concentration too narrow")

    trade_count = summary.get("aggregate_trade_count")
    if not isinstance(trade_count, (int, float)) or isinstance(trade_count, bool) or trade_count < MIN_TRADE_COUNT:
        return PromotionDecision(run_id, False, "insufficient trade sample")

    profitable_ratio = summary.get("profitable_symbol_ratio")
    if not isinstance(profitable_ratio, (int, float)) or isinstance(profitable_ratio, bool) or profitable_ratio < MIN_PROFITABLE_SYMBOL_RATIO:
        return PromotionDecision(run_id, False, "majority of symbols are not profitable")

    median_return = summary.get("median_return")
    if not isinstance(median_return, (int, float)) or isinstance(median_return, bool) or median_return <= 0:
        return PromotionDecision(run_id, False, "median return is not positive")

    strategy = dict(payload.get("strategy") or {})
    fingerprint = strategy.get("fingerprint")
    if not isinstance(fingerprint, str) or not fingerprint:
        return PromotionDecision(run_id, False, "strategy has no fingerprint")

    return PromotionDecision(
        run_id, True, "meets absolute promotion bar: profitable, broad-sample, high-confidence",
        family_id=_family_id_for_strategy(strategy), spec_fingerprint=fingerprint,
    )


def list_promotable_candidates(connection: sqlite3.Connection, *, limit: int = 1000) -> tuple[PromotionDecision, ...]:
    """Read-only: evaluate every genuine (non-artifact) research run and
    return every decision, eligible or not, for admin review/auditing."""
    research_repo = SQLiteMultiSymbolResearchRepository(connection)
    runs = research_repo.list_runs(limit=limit, include_artifacts=False)
    decisions = []
    for row in runs:
        payload = research_repo.get_payload(str(row["run_id"]))
        if payload is None:
            continue
        decisions.append(evaluate_run(payload))
    return tuple(decisions)


def promote_eligible_candidates(connection: sqlite3.Connection, *, now: str, limit: int = 1000) -> tuple[StrategyVersion, ...]:
    """Register every eligible, not-yet-registered research run as an
    APPLY_READY strategy version. Returns the newly registered versions
    (empty if none are eligible or all are already registered). Never
    activates anything and never mutates an existing version."""
    version_repo = StrategyVersionSQLiteRepository(connection)
    research_repo = SQLiteMultiSymbolResearchRepository(connection)
    runs = research_repo.list_runs(limit=limit, include_artifacts=False)
    newly_registered: list[StrategyVersion] = []
    for row in runs:
        run_id = str(row["run_id"])
        payload = research_repo.get_payload(run_id)
        if payload is None:
            continue
        decision = evaluate_run(payload)
        if not decision.eligible or decision.family_id is None:
            continue
        registry = version_repo.get(decision.family_id)
        if any(v.candidate_id == run_id for v in registry.history()):
            continue  # already registered - append-only, never re-register
        strategy = dict(payload.get("strategy") or {})
        version = registry.register_apply_ready(
            family_id=decision.family_id,
            candidate_id=run_id,
            spec_fingerprint=decision.spec_fingerprint or "",
            spec_rules={"entry": strategy.get("entry") or {}, "exit": strategy.get("exit") or {}, "filters": strategy.get("filters") or {}},
            validation_summary=dict(payload.get("summary") or {}),
            at=now,
        )
        version_repo.save(decision.family_id, registry, now=now)
        newly_registered.append(version)
    return tuple(newly_registered)
