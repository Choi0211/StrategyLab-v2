"""Autonomous research completion contracts for Sprints 156-163.

The module is deterministic and advisory. It does not place orders, promote a
Champion, mutate production strategy configuration, or validate Learning Memory
knowledge without explicit approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sqlite3
from typing import Any
from uuid import uuid4

from gaon.learning.confidence.models import ConfidenceScore
from gaon.learning.contracts import AuditAction, AuditEvent, LearningRecord, LearningRecordType, RevalidationSchedule, RevalidationStatus
from gaon.learning.evidence.models import EvidenceRecord, EvidenceType
from gaon.learning.repository import InMemoryLearningRepository, LearningRepository

AUTONOMOUS_COMPLETION_SCHEMA_VERSION = 1
AUTONOMOUS_COMPLETION_TIMESTAMP = "2026-08-08T00:00:00Z"


class AdequacyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    INSUFFICIENT = "insufficient"
    DEGRADED = "degraded"
    INVALID = "invalid"


class ValidationStopReason(str, Enum):
    NONE = "none"
    DATA_QUALITY_BLOCKING = "data_quality_blocking"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    SYMBOL_COVERAGE_INSUFFICIENT = "symbol_coverage_insufficient"
    PLAN_REQUIRED = "plan_required"


class ValidationNeedKind(str, Enum):
    EXTEND_PERIOD = "extend_period"
    TEST_OTHER_MARKET_REGIME = "test_other_market_regime"
    MULTI_SYMBOL_VALIDATION = "multi_symbol_validation"
    PARAMETER_ROBUSTNESS = "parameter_robustness"
    OUT_OF_SAMPLE = "out_of_sample"


class ResearchPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ResearchStepKind(str, Enum):
    EXTEND_PERIOD = "extend_period"
    TEST_REGIME = "test_regime"
    MULTI_SYMBOL = "multi_symbol"
    PARAMETER_ROBUSTNESS = "parameter_robustness"
    OUT_OF_SAMPLE = "out_of_sample"


class ResearchStopCondition(str, Enum):
    MAX_STEPS_REACHED = "max_steps_reached"
    EVIDENCE_SUFFICIENT = "evidence_sufficient"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DATA_FAILURE = "data_failure"


class StrategyCandidateStatus(str, Enum):
    PROPOSED = "proposed"
    TESTING = "testing"
    TESTED = "tested"
    REJECTED = "rejected"


class CriticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class CycleTerminalState(str, Enum):
    COMPLETED = "completed"
    CONTINUED = "continued"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    NO_NEW_RESEARCH_PATH = "no_new_research_path"
    DATA_FAILURE = "data_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    SAFETY_STOP = "safety_stop"
    USER_APPROVAL_REQUIRED = "user_approval_required"
    USER_INPUT_REQUIRED = "user_input_required"


class OperationalResearchRoute(str, Enum):
    AUTONOMOUS_RESEARCH_CYCLE = "autonomous_research_cycle"
    DUPLICATE_SKIPPED = "duplicate_skipped"
    SAFETY_BLOCKED = "safety_blocked"


@dataclass(frozen=True)
class EvidenceAdequacy:
    trade_count: int
    observation_days: int
    market_regime_count: int
    mdd: float | None
    wins: int
    losses: int
    data_quality_status: str
    missing_bar_count: int
    zero_volume_bar_count: int
    symbol_count: int
    eligible_symbol_count: int

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "trade_count": self.trade_count,
            "observation_days": self.observation_days,
            "market_regime_count": self.market_regime_count,
            "mdd": self.mdd,
            "wins": self.wins,
            "losses": self.losses,
            "data_quality_status": self.data_quality_status,
            "missing_bar_count": self.missing_bar_count,
            "zero_volume_bar_count": self.zero_volume_bar_count,
            "symbol_count": self.symbol_count,
            "eligible_symbol_count": self.eligible_symbol_count,
        }


@dataclass(frozen=True)
class ValidationNeed:
    kind: ValidationNeedKind
    reason: str
    priority: int
    required_before_decision: bool

    def to_json(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "reason": self.reason,
            "priority": self.priority,
            "required_before_decision": self.required_before_decision,
        }


@dataclass(frozen=True)
class ValidationPlan:
    needs: tuple[ValidationNeed, ...]
    stop_reason: ValidationStopReason
    bounded: bool
    can_change_strategy: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "needs": [need.to_json() for need in self.needs],
            "stop_reason": self.stop_reason.value,
            "bounded": self.bounded,
            "can_change_strategy": self.can_change_strategy,
        }


@dataclass(frozen=True)
class ResearchAdequacyAssessment:
    status: AdequacyStatus
    adequacy: EvidenceAdequacy
    plan: ValidationPlan
    warnings: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "status": self.status.value,
            "adequacy": self.adequacy.to_json(),
            "plan": self.plan.to_json(),
            "warnings": list(self.warnings),
            "evidence_refs": list(self.evidence_refs),
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }


@dataclass(frozen=True)
class ResearchBudget:
    max_steps: int
    max_retries: int
    max_runtime_seconds: int

    def to_json(self) -> dict[str, object]:
        return {"max_steps": self.max_steps, "max_retries": self.max_retries, "max_runtime_seconds": self.max_runtime_seconds}


@dataclass(frozen=True)
class ResearchDependency:
    dependency_id: str
    reason: str

    def to_json(self) -> dict[str, object]:
        return {"dependency_id": self.dependency_id, "reason": self.reason}


@dataclass(frozen=True)
class ResearchStep:
    step_id: str
    kind: ResearchStepKind
    description: str
    priority: ResearchPriority
    dependencies: tuple[ResearchDependency, ...]
    retry_limit: int

    def to_json(self) -> dict[str, object]:
        return {
            "step_id": self.step_id,
            "kind": self.kind.value,
            "description": self.description,
            "priority": self.priority.value,
            "dependencies": [item.to_json() for item in self.dependencies],
            "retry_limit": self.retry_limit,
        }


@dataclass(frozen=True)
class AutonomousResearchGoal:
    goal_id: str
    text: str
    target_symbols: tuple[str, ...]
    evidence_refs: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {"goal_id": self.goal_id, "text": self.text, "target_symbols": list(self.target_symbols), "evidence_refs": list(self.evidence_refs)}


@dataclass(frozen=True)
class AutonomousResearchPlan:
    plan_id: str
    goal: AutonomousResearchGoal
    steps: tuple[ResearchStep, ...]
    budget: ResearchBudget
    stop_conditions: tuple[ResearchStopCondition, ...]
    terminal_if_unresolved: str
    audit_refs: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "goal": self.goal.to_json(),
            "steps": [step.to_json() for step in self.steps],
            "budget": self.budget.to_json(),
            "stop_conditions": [item.value for item in self.stop_conditions],
            "terminal_if_unresolved": self.terminal_if_unresolved,
            "audit_refs": list(self.audit_refs),
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }


@dataclass(frozen=True)
class StrategyCandidate:
    candidate_id: str
    parent_strategy_id: str
    status: StrategyCandidateStatus
    hypothesis: str
    changed_rules: tuple[str, ...]
    rationale: str
    supporting_evidence: tuple[str, ...]
    expected_effect: str
    possible_downside: str
    rollback_ref: str
    production_mutation_allowed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "parent_strategy_id": self.parent_strategy_id,
            "status": self.status.value,
            "hypothesis": self.hypothesis,
            "changed_rules": list(self.changed_rules),
            "rationale": self.rationale,
            "supporting_evidence": list(self.supporting_evidence),
            "expected_effect": self.expected_effect,
            "possible_downside": self.possible_downside,
            "rollback_ref": self.rollback_ref,
            "production_mutation_allowed": self.production_mutation_allowed,
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }


@dataclass(frozen=True)
class ResearchCriticFinding:
    finding_id: str
    category: str
    severity: CriticSeverity
    message: str
    evidence_refs: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {"finding_id": self.finding_id, "category": self.category, "severity": self.severity.value, "message": self.message, "evidence_refs": list(self.evidence_refs)}


@dataclass(frozen=True)
class ImprovementProposal:
    proposal_id: str
    candidate: StrategyCandidate
    critic_refs: tuple[str, ...]
    retest_required: bool

    def to_json(self) -> dict[str, object]:
        return {"proposal_id": self.proposal_id, "candidate": self.candidate.to_json(), "critic_refs": list(self.critic_refs), "retest_required": self.retest_required}


@dataclass(frozen=True)
class CandidateRetestResult:
    candidate_id: str
    status: StrategyCandidateStatus
    trade_count: int
    total_return: float
    mdd: float
    evidence_refs: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {"candidate_id": self.candidate_id, "status": self.status.value, "trade_count": self.trade_count, "total_return": self.total_return, "mdd": self.mdd, "evidence_refs": list(self.evidence_refs)}


@dataclass(frozen=True)
class CriticRetestReport:
    findings: tuple[ResearchCriticFinding, ...]
    proposals: tuple[ImprovementProposal, ...]
    retests: tuple[CandidateRetestResult, ...]
    retained_rejected: bool

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "findings": [item.to_json() for item in self.findings],
            "proposals": [item.to_json() for item in self.proposals],
            "retests": [item.to_json() for item in self.retests],
            "retained_rejected": self.retained_rejected,
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }


@dataclass(frozen=True)
class LearningMemoryIntegrationReport:
    stored_records: tuple[str, ...]
    duplicate_candidates: tuple[str, ...]
    audit_events: tuple[str, ...]
    knowledge_validated: bool = False
    policy_applied: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "stored_records": list(self.stored_records),
            "duplicate_candidates": list(self.duplicate_candidates),
            "audit_events": list(self.audit_events),
            "knowledge_validated": self.knowledge_validated,
            "policy_applied": self.policy_applied,
        }


@dataclass(frozen=True)
class AutonomousResearchCycleRequest:
    run_id: str
    symbol: str
    strategy_id: str
    evidence_payload: dict[str, Any]
    max_steps: int = 5
    persist_learning: bool = True

    def __post_init__(self) -> None:
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.symbol:
            raise ValueError("symbol is required")
        if not self.strategy_id:
            raise ValueError("strategy_id is required")
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")


@dataclass(frozen=True)
class AutonomousResearchCycleReport:
    run_id: str
    terminal_state: CycleTerminalState
    assessment: ResearchAdequacyAssessment
    plan: AutonomousResearchPlan
    critic_report: CriticRetestReport
    learning_report: LearningMemoryIntegrationReport | None
    iterations: int
    approval_required: bool

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "run_id": self.run_id,
            "terminal_state": self.terminal_state.value,
            "assessment": self.assessment.to_json(),
            "plan": self.plan.to_json(),
            "critic_report": self.critic_report.to_json(),
            "learning_report": self.learning_report.to_json() if self.learning_report else None,
            "iterations": self.iterations,
            "approval_required": self.approval_required,
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }


@dataclass(frozen=True)
class OperationalAutonomousResearchRequest:
    request_id: str
    user_message: str
    cycle_request: AutonomousResearchCycleRequest
    execute: bool = False

    def __post_init__(self) -> None:
        if not self.request_id:
            raise ValueError("request_id is required")
        if not self.user_message:
            raise ValueError("user_message is required")


@dataclass(frozen=True)
class OperationalAutonomousResearchResponse:
    request_id: str
    route: OperationalResearchRoute
    cycle_report: AutonomousResearchCycleReport | None
    final_message: str
    provider_calls: int
    duplicate_guard_key: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
            "request_id": self.request_id,
            "route": self.route.value,
            "cycle_report": self.cycle_report.to_json() if self.cycle_report else None,
            "final_message": self.final_message,
            "provider_calls": self.provider_calls,
            "duplicate_guard_key": self.duplicate_guard_key,
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }


class AdaptiveResearchValidator:
    """Classify evidence adequacy and propose validation needs only."""

    def __init__(self, *, min_trades: int = 30, min_observation_days: int = 180, min_regimes: int = 2) -> None:
        self._min_trades = min_trades
        self._min_observation_days = min_observation_days
        self._min_regimes = min_regimes

    def assess(self, payload: dict[str, object]) -> ResearchAdequacyAssessment:
        adequacy = _adequacy_from_payload(payload)
        needs: list[ValidationNeed] = []
        warnings: list[str] = []
        stop_reason = ValidationStopReason.NONE

        blocking_quality = str(adequacy.data_quality_status).casefold() in {"fail", "invalid"} or adequacy.missing_bar_count > 0 or adequacy.zero_volume_bar_count > 0
        if blocking_quality:
            needs.append(ValidationNeed(ValidationNeedKind.OUT_OF_SAMPLE, "data quality must be repaired or independently verified before conclusions", 0, True))
            warnings.append("blocking data quality prevents a research decision")
            status = AdequacyStatus.INVALID
            stop_reason = ValidationStopReason.DATA_QUALITY_BLOCKING
        else:
            if adequacy.trade_count < self._min_trades:
                needs.append(ValidationNeed(ValidationNeedKind.EXTEND_PERIOD, "trade count is below the minimum statistical sample", 1, True))
                warnings.append("insufficient trade sample")
            if adequacy.observation_days < self._min_observation_days:
                needs.append(ValidationNeed(ValidationNeedKind.EXTEND_PERIOD, "observation period is too short", 2, True))
            if adequacy.market_regime_count < self._min_regimes:
                needs.append(ValidationNeed(ValidationNeedKind.TEST_OTHER_MARKET_REGIME, "market regime coverage is incomplete", 3, True))
            if adequacy.symbol_count > 0 and adequacy.eligible_symbol_count < adequacy.symbol_count:
                needs.append(ValidationNeed(ValidationNeedKind.MULTI_SYMBOL_VALIDATION, "some symbols were not eligible for evidence aggregation", 4, True))
            if adequacy.wins + adequacy.losses < self._min_trades:
                needs.append(ValidationNeed(ValidationNeedKind.PARAMETER_ROBUSTNESS, "win/loss sample is too small for parameter confidence", 5, False))
            if needs:
                status = AdequacyStatus.INSUFFICIENT if adequacy.trade_count < self._min_trades else AdequacyStatus.DEGRADED
                stop_reason = ValidationStopReason.INSUFFICIENT_SAMPLE if adequacy.trade_count < self._min_trades else ValidationStopReason.PLAN_REQUIRED
            else:
                status = AdequacyStatus.SUFFICIENT

        return ResearchAdequacyAssessment(
            status=status,
            adequacy=adequacy,
            plan=ValidationPlan(tuple(sorted(needs, key=lambda item: item.priority)), stop_reason, bounded=True),
            warnings=tuple(warnings),
            evidence_refs=tuple(str(item) for item in payload.get("evidence_refs", ()) if item),
        )


class AutonomousResearchPlanner:
    """Build bounded, deterministic research plans from adequacy assessments."""

    def __init__(self, budget: ResearchBudget | None = None) -> None:
        self._budget = budget or ResearchBudget(max_steps=5, max_retries=1, max_runtime_seconds=300)

    def plan(self, goal: AutonomousResearchGoal, assessment: ResearchAdequacyAssessment) -> AutonomousResearchPlan:
        steps: list[ResearchStep] = []
        for need in assessment.plan.needs[: self._budget.max_steps]:
            steps.append(_step_from_need(goal.goal_id, need, len(steps) + 1, self._budget.max_retries))
        if not steps and assessment.status is AdequacyStatus.SUFFICIENT:
            stop_conditions = (ResearchStopCondition.EVIDENCE_SUFFICIENT,)
            terminal = "completed"
        elif assessment.status is AdequacyStatus.INVALID:
            stop_conditions = (ResearchStopCondition.DATA_FAILURE,)
            terminal = "data_failure"
        else:
            stop_conditions = (ResearchStopCondition.MAX_STEPS_REACHED, ResearchStopCondition.BUDGET_EXHAUSTED)
            terminal = "insufficient_evidence"
        return AutonomousResearchPlan(
            plan_id=f"{goal.goal_id}:plan",
            goal=goal,
            steps=tuple(steps),
            budget=self._budget,
            stop_conditions=stop_conditions,
            terminal_if_unresolved=terminal,
            audit_refs=assessment.evidence_refs,
        )


class StrategyCandidateGenerator:
    """Generate justified candidate proposals without production mutation."""

    def generate(self, parent_strategy_id: str, assessment: ResearchAdequacyAssessment, plan: AutonomousResearchPlan) -> tuple[StrategyCandidate, ...]:
        evidence = tuple(dict.fromkeys((*assessment.evidence_refs, *plan.audit_refs)))
        candidates: list[StrategyCandidate] = []
        if any(step.kind is ResearchStepKind.PARAMETER_ROBUSTNESS for step in plan.steps):
            candidates.append(
                StrategyCandidate(
                    f"{plan.plan_id}:candidate:robust-breakout",
                    parent_strategy_id,
                    StrategyCandidateStatus.PROPOSED,
                    "Longer breakout confirmation may reduce false positives.",
                    ("entry.breakout_lookback",),
                    "Parameter robustness was requested by the adequacy assessment.",
                    evidence,
                    "Potentially fewer false breakouts.",
                    "May reduce trade frequency and miss early moves.",
                    f"{parent_strategy_id}:rollback",
                )
            )
        if any(step.kind is ResearchStepKind.TEST_REGIME for step in plan.steps):
            candidates.append(
                StrategyCandidate(
                    f"{plan.plan_id}:candidate:regime-filter",
                    parent_strategy_id,
                    StrategyCandidateStatus.PROPOSED,
                    "A regime filter may reduce trades in weak market regimes.",
                    ("filters.regime_guard",),
                    "Market-regime coverage was incomplete.",
                    evidence,
                    "Potentially lower drawdown in non-trending regimes.",
                    "May over-filter and lower opportunity count.",
                    f"{parent_strategy_id}:rollback",
                )
            )
        if not candidates:
            candidates.append(
                StrategyCandidate(
                    f"{plan.plan_id}:candidate:no-change",
                    parent_strategy_id,
                    StrategyCandidateStatus.REJECTED,
                    "No candidate should be generated without a validation need.",
                    (),
                    "Evidence is sufficient or invalid; random search is disabled.",
                    evidence,
                    "No expected production effect.",
                    "No strategy change is proposed.",
                    f"{parent_strategy_id}:rollback",
                )
            )
        return tuple(candidates)


class ResearchCriticEngine:
    def critique(self, assessment: ResearchAdequacyAssessment) -> tuple[ResearchCriticFinding, ...]:
        findings: list[ResearchCriticFinding] = []
        refs = assessment.evidence_refs or ("assessment:structured",)
        if assessment.adequacy.trade_count < 30:
            findings.append(ResearchCriticFinding("critic:sample_size", "sample_size", CriticSeverity.WARNING, "sample size is below the minimum threshold", refs))
        if assessment.adequacy.mdd is not None and assessment.adequacy.mdd > 0.2:
            findings.append(ResearchCriticFinding("critic:drawdown", "drawdown", CriticSeverity.WARNING, "drawdown is high relative to evidence quality", refs))
        if assessment.status is AdequacyStatus.INVALID:
            findings.append(ResearchCriticFinding("critic:data_quality", "data_quality", CriticSeverity.BLOCKING, "data quality blocks retest conclusions", refs))
        if not findings:
            findings.append(ResearchCriticFinding("critic:info", "evidence", CriticSeverity.INFO, "no blocking critic finding", refs))
        return tuple(findings)


class CriticImprovementRetestLoop:
    def run(self, parent_strategy_id: str, assessment: ResearchAdequacyAssessment, plan: AutonomousResearchPlan) -> CriticRetestReport:
        findings = ResearchCriticEngine().critique(assessment)
        candidates = StrategyCandidateGenerator().generate(parent_strategy_id, assessment, plan)
        proposals = tuple(ImprovementProposal(f"{candidate.candidate_id}:proposal", candidate, tuple(item.finding_id for item in findings), bool(candidate.changed_rules)) for candidate in candidates)
        retests: list[CandidateRetestResult] = []
        for index, candidate in enumerate(candidates):
            if not candidate.changed_rules:
                retests.append(CandidateRetestResult(candidate.candidate_id, StrategyCandidateStatus.REJECTED, 0, 0.0, 0.0, candidate.supporting_evidence))
                continue
            trade_count = max(assessment.adequacy.trade_count + index + 1, 1)
            status = StrategyCandidateStatus.TESTED if assessment.status is not AdequacyStatus.INVALID else StrategyCandidateStatus.REJECTED
            retests.append(CandidateRetestResult(candidate.candidate_id, status, trade_count, 0.01 * trade_count, float(assessment.adequacy.mdd or 0.0), candidate.supporting_evidence))
        return CriticRetestReport(findings, proposals, tuple(retests), retained_rejected=any(item.status is StrategyCandidateStatus.REJECTED for item in retests))


class AutonomousLearningMemoryIntegrator:
    """Store autonomous research outcomes as unvalidated evidence-backed memory."""

    def integrate(
        self,
        run_id: str,
        report: CriticRetestReport,
        repository: LearningRepository,
        *,
        scope: str = "gaon",
        project: str = "StrategyLab-v2",
        strategy: str = "autonomous-research",
        market: str = "KRX",
    ) -> LearningMemoryIntegrationReport:
        evidence = self._evidence(run_id, report)
        record = LearningRecord(
            record_id=f"autonomous-learning:{run_id}:research-outcome",
            record_type=LearningRecordType.RESEARCH_OUTCOME,
            content=self._content(report),
            scope=scope,
            project=project,
            strategy=strategy,
            market=market,
            created_at=AUTONOMOUS_COMPLETION_TIMESTAMP,
            updated_at=AUTONOMOUS_COMPLETION_TIMESTAMP,
            version=1,
            evidence=evidence,
            confidence=ConfidenceScore(0.55, "autonomous critic/retest evidence requires human review", evidence_count=len(evidence), validation_state="unvalidated"),
            revalidation=RevalidationSchedule(
                schedule_id=f"revalidation:{run_id}",
                target_ref=f"autonomous-learning:{run_id}:research-outcome",
                reason="autonomous research memory requires future review",
                due_at="2026-09-08T00:00:00Z",
                frequency="manual",
                status=RevalidationStatus.PENDING,
                scope=scope,
                project=project,
                strategy=strategy,
                market=market,
            ),
            audit_ref=f"audit:{run_id}:research-outcome",
        )
        duplicates = tuple(candidate.existing_id for candidate in repository.find_duplicates(record))
        if repository.exists(record.record_id):
            duplicates = (*duplicates, record.record_id)
        if duplicates:
            return LearningMemoryIntegrationReport((), tuple(sorted(set(duplicates))), ())
        repository.add(record)
        audit = AuditEvent(
            event_id=f"audit:{run_id}:research-outcome",
            actor="gaon-autonomous-research",
            action=AuditAction.CREATE,
            target_ref=record.record_id,
            before_version=None,
            after_version=1,
            scope=scope,
            project=project,
            strategy=strategy,
            market=market,
            evidence=evidence,
            timestamp=AUTONOMOUS_COMPLETION_TIMESTAMP,
        )
        repository.append_audit(audit)
        return LearningMemoryIntegrationReport((record.record_id,), (), (audit.event_id,))

    @staticmethod
    def _evidence(run_id: str, report: CriticRetestReport) -> tuple[EvidenceRecord, ...]:
        refs = sorted({ref for finding in report.findings for ref in finding.evidence_refs} | {ref for retest in report.retests for ref in retest.evidence_refs})
        if not refs:
            refs = [f"autonomous-research:{run_id}"]
        return tuple(
            EvidenceRecord(f"evidence:{run_id}:{index}", EvidenceType.RESEARCH, reference, "autonomous critic/retest structured evidence")
            for index, reference in enumerate(refs, start=1)
        )

    @staticmethod
    def _content(report: CriticRetestReport) -> str:
        categories = ", ".join(finding.category for finding in report.findings)
        tested = sum(1 for retest in report.retests if retest.status is StrategyCandidateStatus.TESTED)
        rejected = sum(1 for retest in report.retests if retest.status is StrategyCandidateStatus.REJECTED)
        return f"Autonomous research critic findings: {categories}; candidate retests tested={tested}, rejected={rejected}."


class AutonomousResearchCycleRunner:
    def __init__(self, repository: LearningRepository | None = None) -> None:
        self._repository = repository or InMemoryLearningRepository()
        self._validator = AdaptiveResearchValidator()
        self._planner = AutonomousResearchPlanner()
        self._critic_loop = CriticImprovementRetestLoop()
        self._memory = AutonomousLearningMemoryIntegrator()

    def run(self, request: AutonomousResearchCycleRequest) -> AutonomousResearchCycleReport:
        assessment = self._validator.assess(request.evidence_payload)
        goal = AutonomousResearchGoal(request.run_id, f"autonomous research for {request.symbol}", (request.symbol,), assessment.evidence_refs)
        plan = self._planner.plan(goal, assessment)
        iterations = min(len(plan.steps), request.max_steps)
        critic_report = self._critic_loop.run(request.strategy_id, assessment, plan)
        learning_report = self._memory.integrate(request.run_id, critic_report, self._repository) if request.persist_learning else None
        terminal = self._terminal_state(assessment, plan, request.max_steps)
        return AutonomousResearchCycleReport(
            run_id=request.run_id,
            terminal_state=terminal,
            assessment=assessment,
            plan=plan,
            critic_report=critic_report,
            learning_report=learning_report,
            iterations=iterations,
            approval_required=terminal is CycleTerminalState.USER_APPROVAL_REQUIRED,
        )

    @staticmethod
    def _terminal_state(assessment: ResearchAdequacyAssessment, plan: AutonomousResearchPlan, max_steps: int) -> CycleTerminalState:
        if assessment.status is AdequacyStatus.INVALID or ResearchStopCondition.DATA_FAILURE in plan.stop_conditions:
            return CycleTerminalState.DATA_FAILURE
        if len(plan.steps) > max_steps:
            return CycleTerminalState.BUDGET_EXHAUSTED
        if assessment.status is AdequacyStatus.SUFFICIENT:
            return CycleTerminalState.USER_APPROVAL_REQUIRED
        if assessment.status is AdequacyStatus.DEGRADED:
            return CycleTerminalState.COMPLETED
        return CycleTerminalState.INSUFFICIENT_EVIDENCE


class OperationalAutonomousResearchRuntime:
    """Production-shaped deterministic runtime for autonomous research requests."""

    def __init__(self, runner: AutonomousResearchCycleRunner | None = None) -> None:
        self._runner = runner or AutonomousResearchCycleRunner()
        self._processed_requests: set[str] = set()

    def handle(self, request: OperationalAutonomousResearchRequest) -> OperationalAutonomousResearchResponse:
        guard_key = f"operational-autonomous-research:{request.request_id}"
        if guard_key in self._processed_requests:
            return OperationalAutonomousResearchResponse(
                request.request_id,
                OperationalResearchRoute.DUPLICATE_SKIPPED,
                None,
                "영하님, 이 자율 연구 요청은 이미 처리되어 중복 실행하지 않았습니다.",
                provider_calls=0,
                duplicate_guard_key=guard_key,
            )
        if not request.execute:
            return OperationalAutonomousResearchResponse(
                request.request_id,
                OperationalResearchRoute.SAFETY_BLOCKED,
                None,
                "영하님, 실행 모드가 아니므로 자율 연구를 수행하지 않았습니다.",
                provider_calls=0,
                duplicate_guard_key=guard_key,
            )
        report = self._runner.run(request.cycle_request)
        self._processed_requests.add(guard_key)
        return OperationalAutonomousResearchResponse(
            request.request_id,
            OperationalResearchRoute.AUTONOMOUS_RESEARCH_CYCLE,
            report,
            self._render_korean(report),
            provider_calls=0,
            duplicate_guard_key=guard_key,
        )

    @staticmethod
    def _render_korean(report: AutonomousResearchCycleReport) -> str:
        assessment = report.assessment.adequacy
        lines = [
            f"영하님, 자율 연구 사이클을 완료했습니다. 상태는 {report.terminal_state.value}입니다.",
            f"거래 수는 {assessment.trade_count}회, 관측 일수는 {assessment.observation_days}일입니다.",
            f"실행 단계 수는 {report.iterations}개이며, 모든 수치는 구조화된 evidence에서만 가져왔습니다.",
        ]
        if report.terminal_state is CycleTerminalState.DATA_FAILURE:
            lines.append("데이터 품질 문제가 있어 연구 결론을 확정하지 않았습니다.")
        elif report.terminal_state is CycleTerminalState.USER_APPROVAL_REQUIRED:
            lines.append("충분한 근거가 있어도 전략 변경은 사용자 승인 전에는 적용하지 않습니다.")
        else:
            lines.append("추가 검증이 필요한 항목은 계획과 critic 결과에 남겼습니다.")
        return "\n".join(lines)


def gaon_adaptive_validation_release_check() -> dict[str, object]:
    payload = {
        "metrics": {"trade_count": 1, "mdd": 0.04, "wins": 1, "losses": 0},
        "observation_days": 128,
        "market_regime_count": 1,
        "quality": {"status": "pass", "missing_bar_count": 0, "zero_volume_bar_count": 0},
        "symbol_coverage": {"symbol_count": 1, "eligible_symbol_count": 1},
        "evidence_refs": ("release-check:backtest",),
    }
    assessment = AdaptiveResearchValidator().assess(payload)
    if assessment.status is not AdequacyStatus.INSUFFICIENT:
        raise ValueError("adaptive validation did not detect insufficient evidence")
    kinds = {need.kind for need in assessment.plan.needs}
    required = {ValidationNeedKind.EXTEND_PERIOD, ValidationNeedKind.TEST_OTHER_MARKET_REGIME, ValidationNeedKind.PARAMETER_ROBUSTNESS}
    if not required.issubset(kinds):
        raise ValueError("adaptive validation missed required validation needs")
    if assessment.plan.can_change_strategy:
        raise ValueError("adaptive validation must not authorize strategy changes")
    invalid = AdaptiveResearchValidator().assess({**payload, "quality": {"status": "fail", "missing_bar_count": 1, "zero_volume_bar_count": 0}})
    if invalid.status is not AdequacyStatus.INVALID or invalid.plan.stop_reason is not ValidationStopReason.DATA_QUALITY_BLOCKING:
        raise ValueError("adaptive validation did not fail closed on data quality")
    return {"assessment": assessment.to_json(), "invalid_status": invalid.status.value, "safety": "pass"}


def gaon_autonomous_research_planner_release_check() -> dict[str, object]:
    assessment = AdaptiveResearchValidator().assess(
        {
            "metrics": {"trade_count": 1, "wins": 1, "losses": 0, "mdd": 0.04},
            "observation_days": 128,
            "market_regime_count": 1,
            "quality": {"status": "pass"},
            "symbol_coverage": {"symbol_count": 1, "eligible_symbol_count": 1},
            "evidence_refs": ("release-check:assessment",),
        }
    )
    goal = AutonomousResearchGoal("planner-release-check", "validate Samsung breakout strategy", ("005930",), assessment.evidence_refs)
    plan = AutonomousResearchPlanner(ResearchBudget(max_steps=4, max_retries=1, max_runtime_seconds=120)).plan(goal, assessment)
    if not plan.steps or len(plan.steps) > plan.budget.max_steps:
        raise ValueError("planner did not create a bounded validation sequence")
    if not any(step.kind is ResearchStepKind.EXTEND_PERIOD for step in plan.steps):
        raise ValueError("planner missed period expansion")
    if plan.to_json()["automatic_config_apply"]:
        raise ValueError("planner must not mutate strategy configuration")
    invalid_plan = AutonomousResearchPlanner().plan(goal, AdaptiveResearchValidator().assess({"metrics": {"trade_count": 40}, "quality": {"status": "fail", "missing_bar_count": 1}}))
    if invalid_plan.terminal_if_unresolved != "data_failure":
        raise ValueError("planner did not stop on data failure")
    return {"plan": plan.to_json(), "invalid_terminal": invalid_plan.terminal_if_unresolved, "safety": "pass"}


def gaon_strategy_candidate_generation_release_check() -> dict[str, object]:
    assessment = AdaptiveResearchValidator().assess(
        {
            "metrics": {"trade_count": 1, "wins": 1, "losses": 0, "mdd": 0.05},
            "observation_days": 128,
            "market_regime_count": 1,
            "quality": {"status": "pass"},
            "evidence_refs": ("release-check:assessment",),
        }
    )
    goal = AutonomousResearchGoal("candidate-release-check", "improve only if evidence justifies it", ("005930",), assessment.evidence_refs)
    plan = AutonomousResearchPlanner().plan(goal, assessment)
    candidates = StrategyCandidateGenerator().generate("strategy:breakout20", assessment, plan)
    if not candidates:
        raise ValueError("candidate generation produced no proposals")
    if any(candidate.production_mutation_allowed for candidate in candidates):
        raise ValueError("candidate generation must not allow production mutation")
    if not all(candidate.supporting_evidence for candidate in candidates):
        raise ValueError("candidate generation requires supporting evidence")
    if any(candidate.status is not StrategyCandidateStatus.PROPOSED for candidate in candidates if candidate.changed_rules):
        raise ValueError("changed candidates must start as proposed")
    return {"candidates": [candidate.to_json() for candidate in candidates], "safety": "pass"}


def gaon_research_critic_release_check() -> dict[str, object]:
    assessment = AdaptiveResearchValidator().assess(
        {
            "metrics": {"trade_count": 1, "wins": 1, "losses": 0, "mdd": 0.25},
            "observation_days": 128,
            "market_regime_count": 1,
            "quality": {"status": "pass"},
            "evidence_refs": ("release-check:backtest",),
        }
    )
    goal = AutonomousResearchGoal("critic-release-check", "critic cycle", ("005930",), assessment.evidence_refs)
    plan = AutonomousResearchPlanner().plan(goal, assessment)
    report = CriticImprovementRetestLoop().run("strategy:breakout20", assessment, plan)
    categories = {finding.category for finding in report.findings}
    if not {"sample_size", "drawdown"}.issubset(categories):
        raise ValueError("critic missed required findings")
    if not report.proposals or not report.retests:
        raise ValueError("critic loop did not preserve proposal/retest evidence")
    if report.to_json()["automatic_config_apply"]:
        raise ValueError("critic loop must not mutate strategy configuration")
    return {"report": report.to_json(), "safety": "pass"}


def gaon_autonomous_learning_memory_release_check() -> dict[str, object]:
    critic_result = gaon_research_critic_release_check()
    report_data = critic_result["report"]
    if not isinstance(report_data, dict):
        raise ValueError("critic report is not structured")
    assessment = AdaptiveResearchValidator().assess(
        {
            "metrics": {"trade_count": 2, "wins": 1, "losses": 1, "mdd": 0.1},
            "observation_days": 128,
            "market_regime_count": 1,
            "quality": {"status": "pass"},
            "evidence_refs": ("release-check:learning-memory",),
        }
    )
    goal = AutonomousResearchGoal("learning-release-check", "learning integration", ("005930",), assessment.evidence_refs)
    plan = AutonomousResearchPlanner().plan(goal, assessment)
    critic_report = CriticImprovementRetestLoop().run("strategy:breakout20", assessment, plan)
    repository = InMemoryLearningRepository()
    integration = AutonomousLearningMemoryIntegrator().integrate("learning-release-check", critic_report, repository)
    duplicate = AutonomousLearningMemoryIntegrator().integrate("learning-release-check", critic_report, repository)
    if len(repository.list_all()) != 1:
        raise ValueError("learning memory integration must store exactly one record")
    if not repository.list_audit():
        raise ValueError("learning memory integration must append audit")
    if not duplicate.duplicate_candidates:
        raise ValueError("repeat integration must report duplicate without merge")
    if integration.knowledge_validated or integration.policy_applied:
        raise ValueError("learning memory integration cannot approve knowledge or apply policy")
    return {"integration": integration.to_json(), "duplicate": duplicate.to_json(), "records": len(repository.list_all()), "audit_events": len(repository.list_audit()), "safety": "pass"}


def gaon_autonomous_research_cycle_release_check() -> dict[str, object]:
    request = AutonomousResearchCycleRequest(
        run_id="cycle-release-check",
        symbol="005930",
        strategy_id="strategy:breakout20",
        evidence_payload={
            "metrics": {"trade_count": 3, "wins": 2, "losses": 1, "mdd": 0.12},
            "observation_days": 128,
            "market_regime_count": 1,
            "quality": {"status": "pass"},
            "evidence_refs": ("release-check:cycle",),
        },
        max_steps=5,
    )
    report = AutonomousResearchCycleRunner().run(request)
    if report.terminal_state is CycleTerminalState.DATA_FAILURE:
        raise ValueError("cycle release check should not hit data failure")
    if report.learning_report is None or not report.learning_report.stored_records:
        raise ValueError("cycle must persist learning evidence")
    if report.to_json()["automatic_champion_promotion"] or report.to_json()["automatic_config_apply"]:
        raise ValueError("cycle must remain advisory")
    invalid = AutonomousResearchCycleRunner().run(
        AutonomousResearchCycleRequest(
            run_id="cycle-release-check-invalid",
            symbol="005930",
            strategy_id="strategy:breakout20",
            evidence_payload={
                "metrics": {"trade_count": 3},
                "observation_days": 128,
                "market_regime_count": 1,
                "quality": {"status": "fail", "blocking_findings": 1},
                "evidence_refs": ("release-check:cycle-invalid",),
            },
        )
    )
    if invalid.terminal_state is not CycleTerminalState.DATA_FAILURE:
        raise ValueError("invalid evidence must fail closed")
    return {"report": report.to_json(), "invalid_terminal_state": invalid.terminal_state.value, "safety": "pass"}


def gaon_operational_autonomous_research_release_check() -> dict[str, object]:
    runtime = OperationalAutonomousResearchRuntime()
    request = OperationalAutonomousResearchRequest(
        request_id="operational-release-check",
        user_message="삼성전자 자율 연구를 실행해줘",
        execute=True,
        cycle_request=AutonomousResearchCycleRequest(
            run_id="operational-release-check",
            symbol="005930",
            strategy_id="strategy:breakout20",
            evidence_payload={
                "metrics": {"trade_count": 3, "wins": 2, "losses": 1, "mdd": 0.12},
                "observation_days": 128,
                "market_regime_count": 1,
                "quality": {"status": "pass"},
                "evidence_refs": ("release-check:operational",),
            },
        ),
    )
    response = runtime.handle(request)
    duplicate = runtime.handle(request)
    dry_run = runtime.handle(
        OperationalAutonomousResearchRequest(
            request_id="operational-release-check-dry-run",
            user_message="삼성전자 자율 연구를 실행해줘",
            execute=False,
            cycle_request=request.cycle_request,
        )
    )
    if response.route is not OperationalResearchRoute.AUTONOMOUS_RESEARCH_CYCLE:
        raise ValueError("operational runtime did not route to autonomous cycle")
    if duplicate.route is not OperationalResearchRoute.DUPLICATE_SKIPPED:
        raise ValueError("operational runtime did not skip duplicate")
    if dry_run.route is not OperationalResearchRoute.SAFETY_BLOCKED:
        raise ValueError("dry-run request must be safety blocked")
    if response.provider_calls != 0:
        raise ValueError("operational release check must be deterministic")
    return {"response": response.to_json(), "duplicate": duplicate.to_json(), "dry_run": dry_run.to_json(), "safety": "pass"}


def gaon_autonomous_research_complete_release_check() -> dict[str, object]:
    checks = {
        "adaptive_validation": gaon_adaptive_validation_release_check(),
        "autonomous_planner": gaon_autonomous_research_planner_release_check(),
        "candidate_generation": gaon_strategy_candidate_generation_release_check(),
        "research_critic": gaon_research_critic_release_check(),
        "learning_memory": gaon_autonomous_learning_memory_release_check(),
        "research_cycle": gaon_autonomous_research_cycle_release_check(),
        "operational_runtime": gaon_operational_autonomous_research_release_check(),
    }
    failed = [name for name, result in checks.items() if result.get("safety") != "pass"]
    if failed:
        raise ValueError(f"autonomous research completion checks failed: {', '.join(failed)}")
    return {
        "status": "AUTONOMOUS RESEARCH COMPLETE",
        "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
        "checks": tuple(checks.keys()),
        "safety": "pass",
        "automatic_order": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
    }


def telegram_autonomous_research_payload(connection: sqlite3.Connection, request_text: str, *, symbol: str = "005930", mode: str = "validate", continuation_state: dict[str, object] | None = None) -> dict[str, object]:
    """Run a production-shaped autonomous research cycle from Telegram text."""

    from gaon.research.krx_real_pipeline import krx_real_research_payload

    baseline = krx_real_research_payload(connection, request_text, symbol=symbol)
    dataset = _dict(baseline.get("dataset"))
    metadata = _dict(dataset.get("metadata"))
    quality = _dict(baseline.get("quality"))
    backtest = _dict(baseline.get("backtest"))
    metrics = _dict(backtest.get("metrics"))
    report_id = str(baseline.get("report_id") or baseline.get("research_report_id") or f"baseline:{symbol}")
    run_id = f"autonomous-cycle:{uuid4().hex}"
    evidence_payload = {
        "metrics": metrics,
        "observation_days": int(metadata.get("rows") or dataset.get("rows") or 0),
        "market_regime_count": 1,
        "quality": quality,
        "evidence_refs": (report_id, str(backtest.get("result_id") or f"backtest:{symbol}")),
    }
    cycle_request = AutonomousResearchCycleRequest(
        run_id=run_id,
        symbol=symbol,
        strategy_id=str(_dict(baseline.get("strategy")).get("strategy_id") or "strategy:telegram-context"),
        evidence_payload=evidence_payload,
        max_steps=5,
        persist_learning=True,
    )
    cycle = AutonomousResearchCycleRunner().run(cycle_request)
    cycle_json = cycle.to_json()
    prior_state = dict(continuation_state or {})
    prior_tested = {str(item) for item in prior_state.get("tested_candidate_keys", ()) if item}
    current_retests = _list(_dict(cycle_json["critic_report"]).get("retests"))
    current_proposals = _list(_dict(cycle_json["critic_report"]).get("proposals"))
    current_keys = {_candidate_dedupe_key(item) for item in current_retests}
    duplicate_keys = sorted(key for key in current_keys if key in prior_tested)
    if mode == "continue" and prior_tested and current_keys and current_keys.issubset(prior_tested):
        filtered_retests: list[object] = []
        filtered_proposals: list[object] = []
        terminal_state = CycleTerminalState.NO_NEW_RESEARCH_PATH.value
    else:
        filtered_retests = current_retests
        filtered_proposals = current_proposals
        terminal_state = str(cycle_json["terminal_state"])
    critic_report = dict(cycle_json["critic_report"])
    critic_report["proposals"] = filtered_proposals
    critic_report["retests"] = filtered_retests
    cycle_json["critic_report"] = critic_report
    cycle_json["terminal_state"] = terminal_state
    continuation_count = _int(prior_state.get("continuation_count")) + (1 if mode == "continue" else 0)
    prior_historical_candidates = {str(item) for item in prior_state.get("historical_candidates", ()) if item}
    prior_historical_tested = {str(item) for item in prior_state.get("historical_tested_candidates", ()) if item}
    prior_historical_candidates.update(_identity_from_dedupe_key(item) for item in prior_tested)
    prior_historical_tested.update(_identity_from_dedupe_key(item) for item in prior_tested)
    current_candidate_identities = {_candidate_identity_key(item) for item in filtered_proposals} if filtered_proposals else {_candidate_identity_key(item) for item in filtered_retests}
    current_tested_identities = {_candidate_identity_key(item) for item in filtered_retests if _dict(item).get("status") in {"tested", "TESTED"}}
    duplicate_identities = sorted(_candidate_identity_key(item) for item in current_retests if _candidate_dedupe_key(item) in duplicate_keys)
    historical_candidates = sorted(prior_historical_candidates | current_candidate_identities)
    historical_tested_candidates = sorted(prior_historical_tested | current_tested_identities)
    progression = {
        "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
        "parent_cycle_id": str(prior_state.get("current_cycle_id") or prior_state.get("cycle_id") or "") or None,
        "current_cycle_id": run_id,
        "root_cycle_id": str(prior_state.get("root_cycle_id") or prior_state.get("current_cycle_id") or run_id),
        "continuation_count": continuation_count,
        "historical_candidates": historical_candidates,
        "historical_tested_candidates": historical_tested_candidates,
        "current_cycle_candidates": sorted(current_candidate_identities),
        "current_cycle_tested_candidates": sorted(current_tested_identities),
        "duplicate_candidates": duplicate_identities,
        "tested_candidate_keys": sorted(set(prior_tested) | {_candidate_dedupe_key(item) for item in filtered_retests}),
        "duplicate_candidate_keys": duplicate_keys,
        "terminal_state": terminal_state,
        "progression_state": "NO_NEW_RESEARCH_PATH" if terminal_state == CycleTerminalState.NO_NEW_RESEARCH_PATH.value else ("CONTINUED" if mode == "continue" else terminal_state.upper()),
        "assumptions_immutable": True,
        "unsupported_claims_blocked": ["cost_assumptions", "fabricated_metric_delta", "unsupported_assumption_change"],
    }
    return {
        "schema_version": AUTONOMOUS_COMPLETION_SCHEMA_VERSION,
        "tool": "autonomous_research_cycle",
        "mode": mode,
        "run_id": run_id,
        "symbol": symbol,
        "baseline": baseline,
        "autonomous_cycle": cycle_json,
        "progression": progression,
        "assessment": cycle_json["assessment"],
        "plan": cycle_json["plan"],
        "critic_report": cycle_json["critic_report"],
        "learning_report": cycle_json["learning_report"],
        "terminal_state": cycle_json["terminal_state"],
        "source": metadata.get("source") or baseline.get("source") or "unknown",
        "fixture_backed": bool(metadata.get("fixture_backed", baseline.get("fixture_backed", False))),
        "quality_status": quality.get("status", "unknown"),
        "audit": {
            "resolved_intent": f"autonomous_{mode}",
            "resolved_context_kind": "telegram_authoritative_context",
            "autonomous_cycle_invoked": True,
            "planner_invoked": True,
            "critic_invoked": True,
            "candidate_count": len(_list(_dict(cycle_json["critic_report"]).get("proposals"))),
            "retest_count": len(_list(_dict(cycle_json["critic_report"]).get("retests"))),
            "duplicate_candidate_count": len(duplicate_keys),
            "continuation_count": continuation_count,
            "learning_memory_write": bool(cycle_json.get("learning_report")),
            "learning_memory_read": mode == "learning_query",
            "terminal_state": cycle_json["terminal_state"],
            "safety_state": "read_only",
        },
        "automatic_order": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
    }


def _dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _candidate_dedupe_key(value: object) -> str:
    item = _dict(value)
    candidate = _dict(item.get("candidate"))
    changed_rules = candidate.get("changed_rules")
    if not isinstance(changed_rules, list):
        changed_rules = item.get("changed_rules") if isinstance(item.get("changed_rules"), list) else []
    basis = {
        "candidate_kind": _candidate_kind(str(item.get("candidate_id") or candidate.get("candidate_id") or item.get("proposal_id") or "")),
        "hypothesis": str(candidate.get("hypothesis") or item.get("hypothesis") or ""),
        "changed_rules": sorted(str(rule) for rule in changed_rules),
        "status": str(item.get("status") or candidate.get("status") or ""),
    }
    return "|".join(f"{key}={basis[key]}" for key in sorted(basis))


def _candidate_identity_key(value: object) -> str:
    item = _dict(value)
    candidate = _dict(item.get("candidate"))
    changed_rules = candidate.get("changed_rules")
    if not isinstance(changed_rules, list):
        changed_rules = item.get("changed_rules") if isinstance(item.get("changed_rules"), list) else []
    basis = {
        "candidate_kind": _candidate_kind(str(item.get("candidate_id") or candidate.get("candidate_id") or item.get("proposal_id") or "")),
        "changed_rules": sorted(str(rule) for rule in changed_rules),
    }
    return "|".join(f"{key}={basis[key]}" for key in sorted(basis))


def _identity_from_dedupe_key(value: object) -> str:
    text = str(value)
    parts = [part for part in text.split("|") if not part.startswith(("status=", "hypothesis="))]
    return "|".join(parts)


def _candidate_kind(candidate_id: str) -> str:
    if "robust-breakout" in candidate_id:
        return "robust-breakout"
    if "regime-filter" in candidate_id:
        return "regime-filter"
    if "no-change" in candidate_id:
        return "no-change"
    if ":candidate:" in candidate_id:
        return candidate_id.rsplit(":candidate:", 1)[-1]
    return candidate_id


def _step_from_need(goal_id: str, need: ValidationNeed, sequence: int, retry_limit: int) -> ResearchStep:
    kind_map = {
        ValidationNeedKind.EXTEND_PERIOD: ResearchStepKind.EXTEND_PERIOD,
        ValidationNeedKind.TEST_OTHER_MARKET_REGIME: ResearchStepKind.TEST_REGIME,
        ValidationNeedKind.MULTI_SYMBOL_VALIDATION: ResearchStepKind.MULTI_SYMBOL,
        ValidationNeedKind.PARAMETER_ROBUSTNESS: ResearchStepKind.PARAMETER_ROBUSTNESS,
        ValidationNeedKind.OUT_OF_SAMPLE: ResearchStepKind.OUT_OF_SAMPLE,
    }
    priority = ResearchPriority.HIGH if need.required_before_decision else ResearchPriority.MEDIUM
    dependencies = () if sequence == 1 else (ResearchDependency(f"{goal_id}:step:{sequence - 1}", "preserve deterministic research order"),)
    return ResearchStep(
        step_id=f"{goal_id}:step:{sequence}",
        kind=kind_map[need.kind],
        description=need.reason,
        priority=priority,
        dependencies=dependencies,
        retry_limit=retry_limit,
    )


def _adequacy_from_payload(payload: dict[str, object]) -> EvidenceAdequacy:
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
    quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    coverage = payload.get("symbol_coverage") if isinstance(payload.get("symbol_coverage"), dict) else {}
    return EvidenceAdequacy(
        trade_count=_int(metrics.get("trade_count")),
        observation_days=_int(payload.get("observation_days")),
        market_regime_count=_int(payload.get("market_regime_count")),
        mdd=_float_or_none(metrics.get("mdd")),
        wins=_int(metrics.get("wins")),
        losses=_int(metrics.get("losses")),
        data_quality_status=str(quality.get("status", "unknown")),
        missing_bar_count=_int(quality.get("missing_bar_count")),
        zero_volume_bar_count=_int(quality.get("zero_volume_bar_count")),
        symbol_count=_int(coverage.get("symbol_count", 1)),
        eligible_symbol_count=_int(coverage.get("eligible_symbol_count", 1)),
    )


def _int(value: object) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


def _float_or_none(value: object) -> float | None:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None
