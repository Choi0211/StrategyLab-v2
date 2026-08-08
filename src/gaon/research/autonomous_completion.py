"""Autonomous research completion contracts for Sprints 156-163.

The module is deterministic and advisory. It does not place orders, promote a
Champion, mutate production strategy configuration, or validate Learning Memory
knowledge without explicit approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

AUTONOMOUS_COMPLETION_SCHEMA_VERSION = 1


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
