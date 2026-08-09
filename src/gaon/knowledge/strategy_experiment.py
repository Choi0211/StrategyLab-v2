"""Sprint 181 - Strategy Experiment Builder.

Builds validation-ready strategy experiment contracts from proposed
evidence-backed hypotheses.

Safety invariants:
- experiment creation does not execute a backtest
- hypothesis must be proposed and untested
- baseline strategy and assumptions fingerprints are immutable inputs
- no production approval, strategy mutation, Champion promotion, or trading
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Mapping

from .evidence_hypothesis import (
    EvidenceBackedStrategyHypothesis,
    StrategyHypothesisStatus,
)


STRATEGY_EXPERIMENT_SCHEMA_VERSION = 1


class StrategyExperimentStatus(str, Enum):
    READY_FOR_VALIDATION = "ready_for_validation"
    BLOCKED = "blocked"


class StrategyExperimentBlocker(str, Enum):
    HYPOTHESIS_NOT_PROPOSED = "hypothesis_not_proposed"
    MISSING_BASELINE = "missing_baseline"
    MISSING_ASSUMPTIONS = "missing_assumptions"
    MISSING_UNIVERSE = "missing_universe"
    INVALID_PERIOD = "invalid_period"
    HYPOTHESIS_ALREADY_TESTED = "hypothesis_already_tested"


@dataclass(frozen=True)
class StrategyResearchExperiment:
    experiment_id: str
    hypothesis_id: str
    baseline_strategy_id: str
    baseline_strategy_fingerprint: str
    assumptions_fingerprint: str
    changed_rules: tuple[str, ...]
    universe_symbols: tuple[str, ...]
    start: str
    end: str
    cost_model: str
    status: StrategyExperimentStatus
    blockers: tuple[StrategyExperimentBlocker, ...] = ()
    backtest_executed: bool = False
    tested: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": STRATEGY_EXPERIMENT_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "hypothesis_id": self.hypothesis_id,
            "baseline_strategy_id": self.baseline_strategy_id,
            "baseline_strategy_fingerprint": self.baseline_strategy_fingerprint,
            "assumptions_fingerprint": self.assumptions_fingerprint,
            "changed_rules": list(self.changed_rules),
            "universe_symbols": list(self.universe_symbols),
            "start": self.start,
            "end": self.end,
            "cost_model": self.cost_model,
            "status": self.status.value,
            "blockers": [item.value for item in self.blockers],
            "backtest_executed": self.backtest_executed,
            "tested": self.tested,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


def canonical_experiment_id(
    *,
    hypothesis_id: str,
    baseline_strategy_fingerprint: str,
    assumptions_fingerprint: str,
    universe_symbols: tuple[str, ...],
    start: str,
    end: str,
    changed_rules: tuple[str, ...],
) -> str:
    encoded = json.dumps(
        {
            "hypothesis_id": hypothesis_id,
            "baseline_strategy_fingerprint": baseline_strategy_fingerprint,
            "assumptions_fingerprint": assumptions_fingerprint,
            "universe_symbols": sorted(universe_symbols),
            "start": start,
            "end": end,
            "changed_rules": sorted(changed_rules),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"strategy-experiment:{hashlib.sha256(encoded).hexdigest()}"


class StrategyExperimentBuilder:
    def build(
        self,
        *,
        hypothesis: EvidenceBackedStrategyHypothesis,
        baseline_strategy_id: str,
        baseline_strategy_fingerprint: str,
        assumptions_fingerprint: str,
        universe_symbols: tuple[str, ...],
        start: str,
        end: str,
        cost_model: str = "default_research_costs",
    ) -> StrategyResearchExperiment:
        blockers = self._blockers(
            hypothesis,
            baseline_strategy_id,
            baseline_strategy_fingerprint,
            assumptions_fingerprint,
            universe_symbols,
            start,
            end,
        )
        experiment_id = canonical_experiment_id(
            hypothesis_id=hypothesis.hypothesis_id,
            baseline_strategy_fingerprint=baseline_strategy_fingerprint,
            assumptions_fingerprint=assumptions_fingerprint,
            universe_symbols=universe_symbols,
            start=start,
            end=end,
            changed_rules=hypothesis.changed_rules,
        )
        return StrategyResearchExperiment(
            experiment_id=experiment_id,
            hypothesis_id=hypothesis.hypothesis_id,
            baseline_strategy_id=baseline_strategy_id,
            baseline_strategy_fingerprint=baseline_strategy_fingerprint,
            assumptions_fingerprint=assumptions_fingerprint,
            changed_rules=hypothesis.changed_rules,
            universe_symbols=tuple(sorted(universe_symbols)),
            start=start,
            end=end,
            cost_model=cost_model,
            status=(
                StrategyExperimentStatus.BLOCKED
                if blockers
                else StrategyExperimentStatus.READY_FOR_VALIDATION
            ),
            blockers=tuple(blockers),
        )

    @staticmethod
    def _blockers(
        hypothesis: EvidenceBackedStrategyHypothesis,
        baseline_strategy_id: str,
        baseline_strategy_fingerprint: str,
        assumptions_fingerprint: str,
        universe_symbols: tuple[str, ...],
        start: str,
        end: str,
    ) -> list[StrategyExperimentBlocker]:
        blockers: list[StrategyExperimentBlocker] = []
        if hypothesis.status is not StrategyHypothesisStatus.PROPOSED:
            blockers.append(StrategyExperimentBlocker.HYPOTHESIS_NOT_PROPOSED)
        if hypothesis.tested:
            blockers.append(StrategyExperimentBlocker.HYPOTHESIS_ALREADY_TESTED)
        if not baseline_strategy_id.strip() or not baseline_strategy_fingerprint.strip():
            blockers.append(StrategyExperimentBlocker.MISSING_BASELINE)
        if not assumptions_fingerprint.strip():
            blockers.append(StrategyExperimentBlocker.MISSING_ASSUMPTIONS)
        if not universe_symbols:
            blockers.append(StrategyExperimentBlocker.MISSING_UNIVERSE)
        if not start.strip() or not end.strip() or start > end:
            blockers.append(StrategyExperimentBlocker.INVALID_PERIOD)
        return blockers


def strategy_experiment_builder_release_check() -> Mapping[str, object]:
    from .evidence_hypothesis import EvidenceBackedHypothesisGenerator
    from .external_research_memory import ExternalResearchMemoryRecord

    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:experiment-release",
        fingerprint="e" * 64,
        topic_key="strategy.breakout.robustness",
        loop_id="knowledge-research-loop:experiment-release",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a", "claim:b"),
        question_ids=("research-question:a",),
        source_ids=("source:a", "source:b"),
        created_at="2026-08-08T00:00:00+00:00",
    )
    hypothesis = EvidenceBackedHypothesisGenerator().generate(
        topic_key="strategy.breakout.robustness",
        memories=(memory,),
        changed_rules=("add regime filter before breakout entries",),
        rationale="Evidence suggests regime context matters.",
        mechanism="Filter entries before breakout execution.",
        falsification_criteria=("Reject if validation evidence does not improve robustness.",),
    )
    experiment = StrategyExperimentBuilder().build(
        hypothesis=hypothesis,
        baseline_strategy_id="strategy:baseline",
        baseline_strategy_fingerprint="baseline-fingerprint",
        assumptions_fingerprint="assumptions-fingerprint",
        universe_symbols=("005930", "000660"),
        start="2021-07-25",
        end="2026-07-24",
    )
    blocked = StrategyExperimentBuilder().build(
        hypothesis=hypothesis,
        baseline_strategy_id="strategy:baseline",
        baseline_strategy_fingerprint="baseline-fingerprint",
        assumptions_fingerprint="assumptions-fingerprint",
        universe_symbols=(),
        start="2026-07-24",
        end="2021-07-25",
    )

    checks = {
        "ready": experiment.status is StrategyExperimentStatus.READY_FOR_VALIDATION,
        "fingerprint_stable": experiment.experiment_id
        == StrategyExperimentBuilder().build(
            hypothesis=hypothesis,
            baseline_strategy_id="strategy:baseline",
            baseline_strategy_fingerprint="baseline-fingerprint",
            assumptions_fingerprint="assumptions-fingerprint",
            universe_symbols=("000660", "005930"),
            start="2021-07-25",
            end="2026-07-24",
        ).experiment_id,
        "not_executed": not experiment.backtest_executed and not experiment.tested,
        "not_validated": not experiment.knowledge_validated,
        "no_mutation": not experiment.strategy_mutated
        and not experiment.order_executed,
        "blocked_invalid":
            blocked.status is StrategyExperimentStatus.BLOCKED
            and StrategyExperimentBlocker.MISSING_UNIVERSE in blocked.blockers
            and StrategyExperimentBlocker.INVALID_PERIOD in blocked.blockers,
    }

    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(
            f"strategy experiment builder release check failed: {failed}"
        )

    return {
        "schema_version": STRATEGY_EXPERIMENT_SCHEMA_VERSION,
        "status": experiment.status.value,
        "symbols": len(experiment.universe_symbols),
        "checks": checks,
        "safety": "pass",
    }

