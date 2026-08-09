"""Sprint 182 - Autonomous Validation Loop v2.

Attaches authoritative validation evidence to immutable strategy experiments
without executing backtests or approving production use.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Mapping

from .strategy_experiment import (
    StrategyExperimentStatus,
    StrategyResearchExperiment,
    strategy_experiment_builder_release_check,
)


VALIDATION_LOOP_V2_SCHEMA_VERSION = 1


class ValidationLoopV2Status(str, Enum):
    ACCEPTED_FOR_REVIEW = "accepted_for_review"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    BLOCKED = "blocked"


class ValidationLoopV2Blocker(str, Enum):
    EXPERIMENT_NOT_READY = "experiment_not_ready"
    MISSING_EVIDENCE = "missing_evidence"
    EXPERIMENT_MISMATCH = "experiment_mismatch"
    MISSING_AUTHORITATIVE_METRICS = "missing_authoritative_metrics"
    BLOCKING_DATA_QUALITY = "blocking_data_quality"
    FABRICATED_METRIC = "fabricated_metric"


@dataclass(frozen=True)
class AuthoritativeValidationEvidence:
    evidence_id: str
    experiment_id: str
    backtest_result_id: str
    source: str
    fixture_backed: bool
    quality_status: str
    blocking_findings: tuple[str, ...]
    metrics: Mapping[str, float | int | str]
    trade_count: int
    created_at: str
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": VALIDATION_LOOP_V2_SCHEMA_VERSION,
            "evidence_id": self.evidence_id,
            "experiment_id": self.experiment_id,
            "backtest_result_id": self.backtest_result_id,
            "source": self.source,
            "fixture_backed": self.fixture_backed,
            "quality_status": self.quality_status,
            "blocking_findings": list(self.blocking_findings),
            "metrics": dict(self.metrics),
            "trade_count": self.trade_count,
            "created_at": self.created_at,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


@dataclass(frozen=True)
class ValidationLoopV2Result:
    experiment_id: str
    status: ValidationLoopV2Status
    blockers: tuple[ValidationLoopV2Blocker, ...]
    evidence: AuthoritativeValidationEvidence | None
    confidence: str
    warnings: tuple[str, ...]
    backtest_executed: bool = False
    knowledge_validated: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": VALIDATION_LOOP_V2_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "status": self.status.value,
            "blockers": [item.value for item in self.blockers],
            "evidence": self.evidence.to_json() if self.evidence else None,
            "confidence": self.confidence,
            "warnings": list(self.warnings),
            "backtest_executed": self.backtest_executed,
            "knowledge_validated": self.knowledge_validated,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


class AutonomousValidationLoopV2:
    def assess(
        self,
        experiment: StrategyResearchExperiment,
        evidence: AuthoritativeValidationEvidence | None,
    ) -> ValidationLoopV2Result:
        blockers: list[ValidationLoopV2Blocker] = []
        warnings: list[str] = []
        if experiment.status is not StrategyExperimentStatus.READY_FOR_VALIDATION:
            blockers.append(ValidationLoopV2Blocker.EXPERIMENT_NOT_READY)
        if evidence is None:
            blockers.append(ValidationLoopV2Blocker.MISSING_EVIDENCE)
        else:
            blockers.extend(self._evidence_blockers(experiment, evidence))
            if evidence.fixture_backed:
                warnings.append("fixture-backed evidence is allowed only for isolated checks")
            if evidence.trade_count < 30:
                warnings.append("insufficient sample: trade count below research threshold")

        if blockers:
            status = ValidationLoopV2Status.BLOCKED
            confidence = "blocked"
        elif evidence is not None and evidence.trade_count < 30:
            status = ValidationLoopV2Status.NEEDS_MORE_EVIDENCE
            confidence = "low"
        else:
            status = ValidationLoopV2Status.ACCEPTED_FOR_REVIEW
            confidence = "medium" if evidence and evidence.fixture_backed else "high"

        return ValidationLoopV2Result(
            experiment_id=experiment.experiment_id,
            status=status,
            blockers=tuple(dict.fromkeys(blockers)),
            evidence=evidence,
            confidence=confidence,
            warnings=tuple(warnings),
        )

    @staticmethod
    def _evidence_blockers(
        experiment: StrategyResearchExperiment,
        evidence: AuthoritativeValidationEvidence,
    ) -> list[ValidationLoopV2Blocker]:
        blockers: list[ValidationLoopV2Blocker] = []
        if evidence.experiment_id != experiment.experiment_id:
            blockers.append(ValidationLoopV2Blocker.EXPERIMENT_MISMATCH)
        if not evidence.metrics:
            blockers.append(ValidationLoopV2Blocker.MISSING_AUTHORITATIVE_METRICS)
        if evidence.quality_status == "fail" or evidence.blocking_findings:
            blockers.append(ValidationLoopV2Blocker.BLOCKING_DATA_QUALITY)
        for key, value in evidence.metrics.items():
            if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                if key != "profit_factor" or math.isnan(value):
                    blockers.append(ValidationLoopV2Blocker.FABRICATED_METRIC)
        if "trade_count" in evidence.metrics and int(evidence.metrics["trade_count"]) != evidence.trade_count:
            blockers.append(ValidationLoopV2Blocker.FABRICATED_METRIC)
        return blockers


def validation_loop_v2_release_check() -> Mapping[str, object]:
    experiment_payload = strategy_experiment_builder_release_check()
    from .strategy_experiment import StrategyExperimentBuilder
    from .evidence_hypothesis import EvidenceBackedHypothesisGenerator
    from .external_research_memory import ExternalResearchMemoryRecord

    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:validation-release",
        fingerprint="f" * 64,
        topic_key="strategy.validation.robustness",
        loop_id="knowledge-research-loop:validation-release",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a",),
        question_ids=("research-question:a",),
        source_ids=("source:a",),
        created_at="2026-08-08T00:00:00+00:00",
    )
    hypothesis = EvidenceBackedHypothesisGenerator().generate(
        topic_key=memory.topic_key,
        memories=(memory,),
        changed_rules=("require validation evidence before ranking",),
        rationale="Evidence quality should control progression.",
        mechanism="Gate progression on authoritative metrics.",
        falsification_criteria=("Reject if authoritative metrics are missing.",),
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
    evidence = AuthoritativeValidationEvidence(
        evidence_id="validation-evidence:release",
        experiment_id=experiment.experiment_id,
        backtest_result_id="backtest:release",
        source="fixture:validation-loop-v2",
        fixture_backed=True,
        quality_status="pass",
        blocking_findings=(),
        metrics={"trade_count": 42, "total_return": 0.12, "mdd": 0.08},
        trade_count=42,
        created_at="2026-08-08T00:00:00+00:00",
    )
    accepted = AutonomousValidationLoopV2().assess(experiment, evidence)
    blocked = AutonomousValidationLoopV2().assess(
        experiment,
        AuthoritativeValidationEvidence(
            evidence_id="validation-evidence:block",
            experiment_id="different",
            backtest_result_id="backtest:block",
            source="fixture:validation-loop-v2",
            fixture_backed=True,
            quality_status="fail",
            blocking_findings=("invalid_ohlc",),
            metrics={"trade_count": 1},
            trade_count=1,
            created_at="2026-08-08T00:00:00+00:00",
        ),
    )

    checks = {
        "experiment_ready": experiment_payload["status"] == "ready_for_validation",
        "accepted": accepted.status is ValidationLoopV2Status.ACCEPTED_FOR_REVIEW,
        "authoritative": accepted.evidence is not None and accepted.evidence.metrics["trade_count"] == 42,
        "blocked": blocked.status is ValidationLoopV2Status.BLOCKED,
        "no_execution": not accepted.backtest_executed,
        "no_mutation": not accepted.strategy_mutated and not accepted.order_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"validation loop v2 release check failed: {failed}")
    return {
        "schema_version": VALIDATION_LOOP_V2_SCHEMA_VERSION,
        "status": accepted.status.value,
        "confidence": accepted.confidence,
        "trade_count": evidence.trade_count,
        "checks": checks,
        "safety": "pass",
    }
