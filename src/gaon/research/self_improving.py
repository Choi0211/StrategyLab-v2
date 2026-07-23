"""Self-improving autonomous research foundation for Sprint 91-100.

This module is deterministic and advisory. It improves research hypotheses and
candidate parameters only; it never edits source code, changes deployment
state, promotes Champions, or places orders.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
import hashlib
import json
import sqlite3
from uuid import uuid4


RESEARCH_SELF_IMPROVING_SCHEMA_VERSION = 1


class CritiqueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class CritiqueDecision(str, Enum):
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    NEEDS_REVISION = "needs_revision"
    REJECT = "reject"


class ImprovementPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class NoveltyStatus(str, Enum):
    EXACT_DUPLICATE = "exact_duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    SIMILAR_FAMILY = "similar_family"
    NOVEL = "novel"


class ConceptRelationshipType(str, Enum):
    SUPPORTS = "supports"
    WEAKENS = "weakens"
    WORKS_IN = "works_in"
    FAILS_IN = "fails_in"
    CORRELATED_WITH = "correlated_with"
    DERIVED_FROM = "derived_from"


class TournamentStage(str, Enum):
    SCREENING = "screening"
    VALIDATION = "validation"
    FINAL = "final"


@dataclass(frozen=True)
class StrategyCandidate:
    strategy_id: str
    family: str
    market: str
    timeframe: str
    hypothesis: str
    parameters: dict[str, float | int | str | bool]
    metrics: dict[str, float | int]
    features: tuple[str, ...]
    regime_tags: tuple[str, ...]
    source_refs: tuple[str, ...] = ("fixture:self-improving-research",)
    parent_strategy_id: str | None = None
    root_strategy_id: str | None = None
    generation: int = 0
    mutation_reason: str = "original"
    created_from_run_id: str = "manual"

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", dict(sorted(self.parameters.items())))
        object.__setattr__(self, "metrics", dict(sorted(self.metrics.items())))
        object.__setattr__(self, "features", tuple(sorted(self.features)))
        object.__setattr__(self, "regime_tags", tuple(sorted(self.regime_tags)))
        object.__setattr__(self, "source_refs", tuple(self.source_refs))
        if self.root_strategy_id is None:
            object.__setattr__(self, "root_strategy_id", self.strategy_id)

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "family": self.family,
            "market": self.market,
            "timeframe": self.timeframe,
            "hypothesis": self.hypothesis,
            "parameters": dict(self.parameters),
            "metrics": dict(self.metrics),
            "features": list(self.features),
            "regime_tags": list(self.regime_tags),
            "source_refs": list(self.source_refs),
            "parent_strategy_id": self.parent_strategy_id,
            "root_strategy_id": self.root_strategy_id,
            "generation": self.generation,
            "mutation_reason": self.mutation_reason,
            "created_from_run_id": self.created_from_run_id,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "StrategyCandidate":
        _require_schema(payload)
        return cls(
            strategy_id=str(payload["strategy_id"]),
            family=str(payload["family"]),
            market=str(payload["market"]),
            timeframe=str(payload["timeframe"]),
            hypothesis=str(payload["hypothesis"]),
            parameters=dict(payload["parameters"]),  # type: ignore[arg-type]
            metrics=dict(payload["metrics"]),  # type: ignore[arg-type]
            features=tuple(str(item) for item in payload["features"]),  # type: ignore[index]
            regime_tags=tuple(str(item) for item in payload["regime_tags"]),  # type: ignore[index]
            source_refs=tuple(str(item) for item in payload.get("source_refs", ())),  # type: ignore[arg-type]
            parent_strategy_id=str(payload["parent_strategy_id"]) if payload.get("parent_strategy_id") else None,
            root_strategy_id=str(payload["root_strategy_id"]) if payload.get("root_strategy_id") else None,
            generation=int(payload.get("generation", 0)),
            mutation_reason=str(payload.get("mutation_reason", "original")),
            created_from_run_id=str(payload.get("created_from_run_id", "manual")),
        )


@dataclass(frozen=True)
class CritiqueFinding:
    code: str
    severity: CritiqueSeverity
    message: str
    evidence: tuple[str, ...]
    recommended_action: str

    def to_json(self) -> dict[str, object]:
        return {"code": self.code, "severity": self.severity.value, "message": self.message, "evidence": list(self.evidence), "recommended_action": self.recommended_action}


@dataclass(frozen=True)
class ResearchCritique:
    critique_id: str
    strategy_id: str
    decision: CritiqueDecision
    findings: tuple[CritiqueFinding, ...]
    created_at: str
    automatic_promotion: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION,
            "critique_id": self.critique_id,
            "strategy_id": self.strategy_id,
            "decision": self.decision.value,
            "findings": [item.to_json() for item in self.findings],
            "created_at": self.created_at,
            "automatic_promotion": self.automatic_promotion,
        }


@dataclass(frozen=True)
class ImprovementAction:
    action_id: str
    finding_code: str
    priority: ImprovementPriority
    description: str
    parameter_updates: dict[str, float | int | str | bool]
    rationale: str
    supported: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameter_updates", dict(sorted(self.parameter_updates.items())))

    def to_json(self) -> dict[str, object]:
        return {"action_id": self.action_id, "finding_code": self.finding_code, "priority": self.priority.value, "description": self.description, "parameter_updates": dict(self.parameter_updates), "rationale": self.rationale, "supported": self.supported}


@dataclass(frozen=True)
class StrategyImprovementPlan:
    plan_id: str
    strategy_id: str
    critique_id: str
    actions: tuple[ImprovementAction, ...]
    unsupported_mutations: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "strategy_id": self.strategy_id,
            "critique_id": self.critique_id,
            "actions": [item.to_json() for item in self.actions],
            "unsupported_mutations": list(self.unsupported_mutations),
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class StrategyLineageNode:
    strategy_id: str
    parent_strategy_id: str | None
    root_strategy_id: str
    generation: int
    mutation_reason: str
    created_from_run_id: str
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION,
            "strategy_id": self.strategy_id,
            "parent_strategy_id": self.parent_strategy_id,
            "root_strategy_id": self.root_strategy_id,
            "generation": self.generation,
            "mutation_reason": self.mutation_reason,
            "created_from_run_id": self.created_from_run_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchIterationSummary:
    iteration_id: str
    run_id: str
    iteration_index: int
    strategy_id: str
    parent_strategy_id: str | None
    critique_decision: CritiqueDecision
    quality_score: float
    status: str
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION,
            "iteration_id": self.iteration_id,
            "run_id": self.run_id,
            "iteration_index": self.iteration_index,
            "strategy_id": self.strategy_id,
            "parent_strategy_id": self.parent_strategy_id,
            "critique_decision": self.critique_decision.value,
            "quality_score": self.quality_score,
            "status": self.status,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class ResearchMemoryEntry:
    memory_id: str
    strategy_family: str
    market: str
    timeframe: str
    hypothesis: str
    result_summary: str
    critic_summary: str
    improvement_summary: str
    final_status: str
    tags: tuple[str, ...]
    created_at: str
    source_run_id: str
    fingerprint: str
    source_refs: tuple[str, ...] = ("fixture:self-improving-research",)

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION,
            "memory_id": self.memory_id,
            "strategy_family": self.strategy_family,
            "market": self.market,
            "timeframe": self.timeframe,
            "hypothesis": self.hypothesis,
            "result_summary": self.result_summary,
            "critic_summary": self.critic_summary,
            "improvement_summary": self.improvement_summary,
            "final_status": self.final_status,
            "tags": list(self.tags),
            "created_at": self.created_at,
            "source_run_id": self.source_run_id,
            "fingerprint": self.fingerprint,
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "ResearchMemoryEntry":
        _require_schema(payload)
        return cls(
            str(payload["memory_id"]),
            str(payload["strategy_family"]),
            str(payload["market"]),
            str(payload["timeframe"]),
            str(payload["hypothesis"]),
            str(payload["result_summary"]),
            str(payload["critic_summary"]),
            str(payload["improvement_summary"]),
            str(payload["final_status"]),
            tuple(str(item) for item in payload["tags"]),  # type: ignore[index]
            str(payload["created_at"]),
            str(payload["source_run_id"]),
            str(payload["fingerprint"]),
            tuple(str(item) for item in payload.get("source_refs", ())),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ResearchConcept:
    concept_id: str
    name: str
    description: str
    source_refs: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {"schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION, "concept_id": self.concept_id, "name": self.name, "description": self.description, "source_refs": list(self.source_refs), "created_at": self.created_at}


@dataclass(frozen=True)
class ResearchEvidence:
    evidence_id: str
    source_ref: str
    summary: str
    trust: str
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {"schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION, "evidence_id": self.evidence_id, "source_ref": self.source_ref, "summary": self.summary, "trust": self.trust, "created_at": self.created_at}


@dataclass(frozen=True)
class ConceptRelationship:
    relationship_id: str
    source_concept_id: str
    relationship: ConceptRelationshipType
    target_ref: str
    evidence_refs: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {"schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION, "relationship_id": self.relationship_id, "source_concept_id": self.source_concept_id, "relationship": self.relationship.value, "target_ref": self.target_ref, "evidence_refs": list(self.evidence_refs), "created_at": self.created_at}


@dataclass(frozen=True)
class ResearchQualityScore:
    score_id: str
    strategy_id: str
    total: float
    components: dict[str, float]
    weights: dict[str, float]
    hard_failures: tuple[str, ...]
    created_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "components", dict(sorted(self.components.items())))
        object.__setattr__(self, "weights", dict(sorted(self.weights.items())))

    def to_json(self) -> dict[str, object]:
        return {"schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION, "score_id": self.score_id, "strategy_id": self.strategy_id, "total": self.total, "components": dict(self.components), "weights": dict(self.weights), "hard_failures": list(self.hard_failures), "created_at": self.created_at}


@dataclass(frozen=True)
class CandidateRanking:
    strategy_id: str
    rank: int
    score: float
    stage: TournamentStage
    eliminated: bool
    elimination_reason: str | None

    def to_json(self) -> dict[str, object]:
        return {"strategy_id": self.strategy_id, "rank": self.rank, "score": self.score, "stage": self.stage.value, "eliminated": self.eliminated, "elimination_reason": self.elimination_reason}


@dataclass(frozen=True)
class ResearchTournament:
    tournament_id: str
    rankings: tuple[CandidateRanking, ...]
    top_n: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {"schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION, "tournament_id": self.tournament_id, "rankings": [item.to_json() for item in self.rankings], "top_n": list(self.top_n), "created_at": self.created_at}


@dataclass(frozen=True)
class AutonomousResearchRequest:
    request_id: str
    market: str
    timeframe: str
    strategy_family: str
    hypothesis: str
    max_iterations: int = 3
    target_quality: float = 75.0

    def to_json(self) -> dict[str, object]:
        return {"schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION, "request_id": self.request_id, "market": self.market, "timeframe": self.timeframe, "strategy_family": self.strategy_family, "hypothesis": self.hypothesis, "max_iterations": self.max_iterations, "target_quality": self.target_quality}


@dataclass(frozen=True)
class AutonomousResearchResult:
    run_id: str
    request: AutonomousResearchRequest
    initial_strategy_id: str
    final_strategy_id: str
    novelty: NoveltyStatus
    iterations: tuple[ResearchIterationSummary, ...]
    quality: ResearchQualityScore
    critique: ResearchCritique
    improvement_plan: StrategyImprovementPlan
    tournament: ResearchTournament
    memory_id: str | None
    report: str
    warnings: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_SELF_IMPROVING_SCHEMA_VERSION,
            "run_id": self.run_id,
            "request": self.request.to_json(),
            "initial_strategy_id": self.initial_strategy_id,
            "final_strategy_id": self.final_strategy_id,
            "novelty": self.novelty.value,
            "iterations": [item.to_json() for item in self.iterations],
            "quality": self.quality.to_json(),
            "critique": self.critique.to_json(),
            "improvement_plan": self.improvement_plan.to_json(),
            "tournament": self.tournament.to_json(),
            "memory_id": self.memory_id,
            "report": self.report,
            "warnings": list(self.warnings),
            "created_at": self.created_at,
        }


class ResearchCritic:
    def evaluate(self, candidate: StrategyCandidate, *, created_at: str | None = None) -> ResearchCritique:
        findings: list[CritiqueFinding] = []
        m = candidate.metrics
        if float(m.get("in_sample_sharpe", 0.0)) - float(m.get("out_of_sample_sharpe", 0.0)) > 1.0:
            findings.append(_finding("overfit_gap", CritiqueSeverity.CRITICAL, "In-sample performance is much stronger than out-of-sample performance.", "Reduce parameter freedom and require walk-forward confirmation."))
        if int(m.get("sample_size", 0)) < 200 or int(m.get("trade_count", 0)) < 30:
            findings.append(_finding("weak_sample", CritiqueSeverity.ERROR, "Sample size or trade count is too low for reliable validation.", "Extend validation horizon or require more trades before ranking."))
        if float(m.get("walk_forward_stability", 1.0)) < 0.55:
            findings.append(_finding("wf_instability", CritiqueSeverity.ERROR, "Walk-forward stability is below the accepted research threshold.", "Add regime and parameter stability checks."))
        if float(m.get("monte_carlo_robustness", 1.0)) < 0.55:
            findings.append(_finding("mc_fragility", CritiqueSeverity.ERROR, "Monte Carlo robustness is fragile under shuffle/noise tests.", "Reduce sensitivity and add stop/risk filters."))
        if float(m.get("max_drawdown", 0.0)) > 0.22:
            findings.append(_finding("high_mdd", CritiqueSeverity.ERROR, "Maximum drawdown is too high for advisory promotion.", "Tighten risk sizing and drawdown stop assumptions."))
        if float(m.get("parameter_stability", 1.0)) < 0.6:
            findings.append(_finding("unstable_params", CritiqueSeverity.WARNING, "Parameter sensitivity is high.", "Prefer wider robust ranges over narrow optimized values."))
        if float(m.get("regime_dependency", 0.0)) > 0.7:
            findings.append(_finding("regime_dependency", CritiqueSeverity.WARNING, "Result depends heavily on one market regime.", "Tag the strategy as regime-specific and validate failure regimes."))
        if float(m.get("liquidity_score", 1.0)) < 0.55:
            findings.append(_finding("liquidity_assumption", CritiqueSeverity.WARNING, "Liquidity or turnover assumptions are weak.", "Add liquidity and turnover filters."))
        if float(m.get("feature_complexity", 0.0)) > 0.75:
            findings.append(_finding("feature_complexity", CritiqueSeverity.WARNING, "Feature complexity is high relative to evidence quality.", "Remove low-contribution features."))
        if float(m.get("profit_factor", 1.0)) > 3.0 and float(m.get("out_of_sample_sharpe", 0.0)) > 2.5:
            findings.append(_finding("suspicious_performance", CritiqueSeverity.WARNING, "Performance is unusually high and requires leakage checks.", "Verify data leakage, costs, and execution assumptions."))
        if not findings:
            findings.append(_finding("clean", CritiqueSeverity.INFO, "No critical self-critic finding was triggered.", "Proceed to advisory comparison; keep human approval boundary."))
        severities = {item.severity for item in findings}
        decision = CritiqueDecision.REJECT if CritiqueSeverity.CRITICAL in severities else CritiqueDecision.NEEDS_REVISION if CritiqueSeverity.ERROR in severities else CritiqueDecision.PASS_WITH_WARNINGS if CritiqueSeverity.WARNING in severities else CritiqueDecision.PASS
        return ResearchCritique(f"critique:{candidate.strategy_id}:{uuid4().hex}", candidate.strategy_id, decision, tuple(findings), created_at or utc_now())


class StrategyImprovementPlanner:
    def plan(self, candidate: StrategyCandidate, critique: ResearchCritique, *, created_at: str | None = None) -> StrategyImprovementPlan:
        actions: list[ImprovementAction] = []
        for finding in critique.findings:
            updates = _updates_for_finding(finding.code)
            priority = ImprovementPriority.HIGH if finding.severity in {CritiqueSeverity.CRITICAL, CritiqueSeverity.ERROR} else ImprovementPriority.MEDIUM if finding.severity is CritiqueSeverity.WARNING else ImprovementPriority.LOW
            actions.append(ImprovementAction(f"action:{finding.code}", finding.code, priority, finding.recommended_action, updates, f"Traceable response to finding {finding.code}."))
        return StrategyImprovementPlan(f"plan:{candidate.strategy_id}:{uuid4().hex}", candidate.strategy_id, critique.critique_id, tuple(actions), (), created_at or utc_now())


class ResearchQualityScorer:
    DEFAULT_WEIGHTS = {
        "performance": 0.16,
        "robustness": 0.16,
        "risk": 0.14,
        "stability": 0.12,
        "simplicity": 0.10,
        "sample": 0.12,
        "regime": 0.08,
        "explainability": 0.06,
        "novelty": 0.06,
    }

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or self.DEFAULT_WEIGHTS
        if set(self._weights) != set(self.DEFAULT_WEIGHTS) or abs(sum(self._weights.values()) - 1.0) > 0.000001:
            raise ValueError("quality score weights must cover all components and sum to 1.0")

    def score(self, candidate: StrategyCandidate, critique: ResearchCritique | None = None, novelty: NoveltyStatus = NoveltyStatus.NOVEL, *, created_at: str | None = None) -> ResearchQualityScore:
        m = candidate.metrics
        components = {
            "performance": _pct(float(m.get("out_of_sample_sharpe", 0.0)) / 2.0),
            "robustness": _pct(float(m.get("monte_carlo_robustness", 0.0))),
            "risk": _pct(1.0 - float(m.get("max_drawdown", 0.0)) / 0.35),
            "stability": _pct((float(m.get("walk_forward_stability", 0.0)) + float(m.get("parameter_stability", 0.0))) / 2.0),
            "simplicity": _pct(1.0 - float(m.get("feature_complexity", 0.0))),
            "sample": _pct(min(1.0, int(m.get("trade_count", 0)) / 80.0)),
            "regime": _pct(1.0 - float(m.get("regime_dependency", 0.0))),
            "explainability": _pct(1.0 if candidate.hypothesis and candidate.source_refs else 0.5),
            "novelty": {"exact_duplicate": 15.0, "near_duplicate": 40.0, "similar_family": 65.0, "novel": 85.0}[novelty.value],
        }
        hard_failures = tuple(finding.code for finding in critique.findings if finding.severity in {CritiqueSeverity.CRITICAL, CritiqueSeverity.ERROR}) if critique else ()
        total = sum(components[name] * self._weights[name] for name in self._weights)
        if hard_failures:
            total = min(total, 69.0)
        return ResearchQualityScore(f"quality:{candidate.strategy_id}:{uuid4().hex}", candidate.strategy_id, round(total, 3), components, self._weights, hard_failures, created_at or utc_now())


class ResearchNoveltyDetector:
    def detect(self, candidate: StrategyCandidate, memories: tuple[ResearchMemoryEntry, ...]) -> NoveltyStatus:
        fp = candidate_fingerprint(candidate)
        if any(memory.fingerprint == fp for memory in memories):
            return NoveltyStatus.EXACT_DUPLICATE
        if any(memory.strategy_family == candidate.family and memory.market == candidate.market and memory.timeframe == candidate.timeframe for memory in memories):
            return NoveltyStatus.SIMILAR_FAMILY
        if any(memory.strategy_family == candidate.family for memory in memories):
            return NoveltyStatus.NEAR_DUPLICATE
        return NoveltyStatus.NOVEL


class ResearchIterationLoop:
    def __init__(self, critic: ResearchCritic | None = None, planner: StrategyImprovementPlanner | None = None, scorer: ResearchQualityScorer | None = None) -> None:
        self._critic = critic or ResearchCritic()
        self._planner = planner or StrategyImprovementPlanner()
        self._scorer = scorer or ResearchQualityScorer()

    def run(self, candidate: StrategyCandidate, *, run_id: str, max_iterations: int = 3, target_quality: float = 75.0, created_at: str | None = None) -> tuple[StrategyCandidate, ResearchCritique, StrategyImprovementPlan, ResearchQualityScore, tuple[ResearchIterationSummary, ...]]:
        if max_iterations < 1 or max_iterations > 10:
            raise ValueError("max_iterations must be between 1 and 10")
        current = candidate
        summaries: list[ResearchIterationSummary] = []
        last_critique = self._critic.evaluate(current, created_at=created_at)
        last_plan = self._planner.plan(current, last_critique, created_at=created_at)
        last_quality = self._scorer.score(current, last_critique, created_at=created_at)
        previous_score = -1.0
        for index in range(max_iterations):
            last_critique = self._critic.evaluate(current, created_at=created_at)
            last_plan = self._planner.plan(current, last_critique, created_at=created_at)
            last_quality = self._scorer.score(current, last_critique, created_at=created_at)
            status = "target_quality_reached" if last_quality.total >= target_quality and last_critique.decision in {CritiqueDecision.PASS, CritiqueDecision.PASS_WITH_WARNINGS} else "needs_revision"
            summaries.append(ResearchIterationSummary(f"iteration:{run_id}:{index + 1}", run_id, index + 1, current.strategy_id, current.parent_strategy_id, last_critique.decision, last_quality.total, status, created_at or utc_now()))
            if status == "target_quality_reached" or last_critique.decision is CritiqueDecision.PASS:
                break
            if last_quality.total <= previous_score + 0.01 and index > 0:
                summaries[-1] = replace(summaries[-1], status="stopped_no_improvement")
                break
            previous_score = last_quality.total
            current = apply_improvement_plan(current, last_plan, run_id=run_id, generation=current.generation + 1)
        return current, last_critique, last_plan, last_quality, tuple(summaries)


class ResearchTournamentRunner:
    def __init__(self, scorer: ResearchQualityScorer | None = None, critic: ResearchCritic | None = None) -> None:
        self._scorer = scorer or ResearchQualityScorer()
        self._critic = critic or ResearchCritic()

    def run(self, candidates: tuple[StrategyCandidate, ...], *, top_n: int = 3, created_at: str | None = None) -> ResearchTournament:
        scored: list[tuple[StrategyCandidate, ResearchQualityScore, ResearchCritique]] = []
        for candidate in candidates:
            critique = self._critic.evaluate(candidate, created_at=created_at)
            scored.append((candidate, self._scorer.score(candidate, critique, created_at=created_at), critique))
        ranked = sorted(scored, key=lambda item: (item[1].total, -len(item[2].findings), item[0].strategy_id), reverse=True)
        rankings: list[CandidateRanking] = []
        for index, (candidate, quality, critique) in enumerate(ranked, start=1):
            hard = tuple(f.code for f in critique.findings if f.severity in {CritiqueSeverity.CRITICAL, CritiqueSeverity.ERROR})
            eliminated = bool(hard) or index > top_n
            reason = ",".join(hard) if hard else "outside_top_n" if index > top_n else None
            rankings.append(CandidateRanking(candidate.strategy_id, index, quality.total, TournamentStage.FINAL, eliminated, reason))
        return ResearchTournament(f"tournament:{uuid4().hex}", tuple(rankings), tuple(item.strategy_id for item, _, _ in ranked[:top_n]), created_at or utc_now())


class SQLiteResearchMemoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_memory(self, entry: ResearchMemoryEntry) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO research_memories(memory_id, fingerprint, strategy_family, market, timeframe, final_status, payload_json, created_at, source_run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry.memory_id, entry.fingerprint, entry.strategy_family, entry.market, entry.timeframe, entry.final_status, _json(entry.to_json()), entry.created_at, entry.source_run_id),
            )

    def list_memories(self) -> tuple[ResearchMemoryEntry, ...]:
        rows = self._connection.execute("SELECT payload_json FROM research_memories ORDER BY created_at, memory_id").fetchall()
        return tuple(ResearchMemoryEntry.from_json(json.loads(str(row[0]))) for row in rows)

    def search(self, *, strategy_family: str | None = None, market: str | None = None, timeframe: str | None = None, query: str | None = None, tag: str | None = None) -> tuple[ResearchMemoryEntry, ...]:
        rows = self.list_memories()
        q = query.casefold() if query else None
        results: list[ResearchMemoryEntry] = []
        for item in rows:
            if strategy_family and item.strategy_family != strategy_family:
                continue
            if market and item.market != market:
                continue
            if timeframe and item.timeframe != timeframe:
                continue
            if tag and tag not in item.tags:
                continue
            haystack = " ".join((item.hypothesis, item.result_summary, item.critic_summary, item.improvement_summary, " ".join(item.tags))).casefold()
            if q and q not in haystack:
                continue
            results.append(item)
        return tuple(results)

    def find_by_fingerprint(self, fingerprint: str) -> ResearchMemoryEntry | None:
        row = self._connection.execute("SELECT payload_json FROM research_memories WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return ResearchMemoryEntry.from_json(json.loads(str(row[0]))) if row else None

    def put_lineage(self, node: StrategyLineageNode) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO strategy_lineage(strategy_id, parent_strategy_id, root_strategy_id, generation, mutation_reason, created_from_run_id, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (node.strategy_id, node.parent_strategy_id, node.root_strategy_id, node.generation, node.mutation_reason, node.created_from_run_id, _json(node.to_json()), node.created_at),
            )

    def lineage(self, root_strategy_id: str) -> tuple[StrategyLineageNode, ...]:
        rows = self._connection.execute("SELECT payload_json FROM strategy_lineage WHERE root_strategy_id = ? ORDER BY generation, created_at, strategy_id", (root_strategy_id,)).fetchall()
        return tuple(_lineage_from_json(json.loads(str(row[0]))) for row in rows)

    def put_critique(self, critique: ResearchCritique) -> None:
        with self._connection:
            self._connection.execute("INSERT OR IGNORE INTO research_critiques(critique_id, strategy_id, decision, payload_json, created_at) VALUES (?, ?, ?, ?, ?)", (critique.critique_id, critique.strategy_id, critique.decision.value, _json(critique.to_json()), critique.created_at))

    def put_iteration(self, iteration: ResearchIterationSummary) -> None:
        with self._connection:
            self._connection.execute("INSERT OR IGNORE INTO research_iterations(iteration_id, run_id, iteration_index, strategy_id, quality_score, status, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (iteration.iteration_id, iteration.run_id, iteration.iteration_index, iteration.strategy_id, iteration.quality_score, iteration.status, _json(iteration.to_json()), iteration.created_at))

    def put_quality(self, quality: ResearchQualityScore) -> None:
        with self._connection:
            self._connection.execute("INSERT OR IGNORE INTO research_quality_scores(score_id, strategy_id, score, payload_json, created_at) VALUES (?, ?, ?, ?, ?)", (quality.score_id, quality.strategy_id, quality.total, _json(quality.to_json()), quality.created_at))


class ResearchKnowledgeBase:
    def __init__(self) -> None:
        self._concepts: dict[str, ResearchConcept] = {}
        self._relationships: list[ConceptRelationship] = []

    def add_concept(self, concept: ResearchConcept) -> None:
        if not concept.source_refs:
            raise ValueError("concept requires evidence source refs")
        self._concepts[concept.concept_id] = concept

    def add_relationship(self, relationship: ConceptRelationship) -> None:
        if not relationship.evidence_refs:
            raise ValueError("relationship requires evidence refs")
        self._relationships.append(relationship)

    def related(self, concept_id: str) -> tuple[ConceptRelationship, ...]:
        return tuple(item for item in self._relationships if item.source_concept_id == concept_id or item.target_ref == concept_id)


class AutonomousResearchOrchestrator:
    def __init__(self, repository: SQLiteResearchMemoryRepository | None = None) -> None:
        self._repository = repository
        self._critic = ResearchCritic()
        self._planner = StrategyImprovementPlanner()
        self._scorer = ResearchQualityScorer()
        self._loop = ResearchIterationLoop(self._critic, self._planner, self._scorer)
        self._tournament = ResearchTournamentRunner(self._scorer, self._critic)

    def run(self, request: AutonomousResearchRequest, *, run_id: str | None = None, created_at: str | None = None) -> AutonomousResearchResult:
        at = created_at or utc_now()
        rid = run_id or f"autonomous-research:{uuid4().hex}"
        initial = fixture_candidate("balanced", strategy_id=f"{rid}:candidate:0", family=request.strategy_family, market=request.market, timeframe=request.timeframe, hypothesis=request.hypothesis, created_from_run_id=rid)
        memories = self._repository.list_memories() if self._repository else ()
        novelty = ResearchNoveltyDetector().detect(initial, memories)
        final, critique, plan, quality, iterations = self._loop.run(initial, run_id=rid, max_iterations=request.max_iterations, target_quality=request.target_quality, created_at=at)
        variants = (initial, final, fixture_candidate("fragile", strategy_id=f"{rid}:candidate:fragile", family=request.strategy_family, market=request.market, timeframe=request.timeframe, created_from_run_id=rid))
        tournament = self._tournament.run(variants, top_n=2, created_at=at)
        memory = build_memory_entry(final, critique, plan, quality, run_id=rid, created_at=at)
        memory_id: str | None = None
        warnings = ["fixture-backed autonomous research; no code, deployment, order, automatic promotion, automatic Champion promotion, or Champion state was changed"]
        if self._repository:
            if self._repository.find_by_fingerprint(memory.fingerprint) is None:
                self._repository.add_memory(memory)
                memory_id = memory.memory_id
            else:
                warnings.append("duplicate research memory fingerprint detected; existing memory was preserved")
            for strategy in variants:
                self._repository.put_lineage(_lineage_node(strategy, at))
            self._repository.put_critique(critique)
            self._repository.put_quality(quality)
            for iteration in iterations:
                self._repository.put_iteration(iteration)
        report = f"Self-improving research completed for {request.strategy_family}. Final strategy {final.strategy_id} scored {quality.total:.1f}; decision={critique.decision.value}; automatic promotion=false."
        return AutonomousResearchResult(rid, request, initial.strategy_id, final.strategy_id, novelty, iterations, quality, critique, plan, tournament, memory_id, report, tuple(warnings), at)


def apply_improvement_plan(candidate: StrategyCandidate, plan: StrategyImprovementPlan, *, run_id: str, generation: int) -> StrategyCandidate:
    params = dict(candidate.parameters)
    metrics = dict(candidate.metrics)
    features = set(candidate.features)
    reasons: list[str] = []
    for action in plan.actions:
        if not action.supported:
            continue
        params.update(action.parameter_updates)
        reasons.append(action.finding_code)
    if "max_risk_pct" in params:
        metrics["max_drawdown"] = round(max(0.05, float(metrics.get("max_drawdown", 0.1)) * 0.82), 4)
    if "min_trade_count" in params:
        metrics["sample_size"] = max(int(metrics.get("sample_size", 0)), int(params["min_trade_count"]) * 8)
        metrics["trade_count"] = max(int(metrics.get("trade_count", 0)), int(params["min_trade_count"]))
    if "walk_forward_required" in params:
        metrics["walk_forward_stability"] = round(min(1.0, float(metrics.get("walk_forward_stability", 0.0)) + 0.18), 4)
    if "monte_carlo_required" in params:
        metrics["monte_carlo_robustness"] = round(min(1.0, float(metrics.get("monte_carlo_robustness", 0.0)) + 0.18), 4)
    if "feature_pruning" in params:
        metrics["feature_complexity"] = round(max(0.05, float(metrics.get("feature_complexity", 0.0)) - 0.2), 4)
        features.discard("low_contribution_combo")
    metrics["parameter_stability"] = round(min(1.0, float(metrics.get("parameter_stability", 0.5)) + 0.12), 4)
    new_id = f"{candidate.strategy_id}:rev{generation}"
    return StrategyCandidate(
        new_id,
        candidate.family,
        candidate.market,
        candidate.timeframe,
        f"{candidate.hypothesis} Revised with bounded research actions: {', '.join(reasons) or 'none'}.",
        params,
        metrics,
        tuple(features | {"risk_filter"}),
        candidate.regime_tags,
        candidate.source_refs,
        parent_strategy_id=candidate.strategy_id,
        root_strategy_id=candidate.root_strategy_id,
        generation=generation,
        mutation_reason=",".join(reasons) or "no_supported_change",
        created_from_run_id=run_id,
    )


def build_memory_entry(candidate: StrategyCandidate, critique: ResearchCritique, plan: StrategyImprovementPlan, quality: ResearchQualityScore, *, run_id: str, created_at: str | None = None) -> ResearchMemoryEntry:
    final_status = "validated_candidate" if quality.total >= 75.0 and critique.decision in {CritiqueDecision.PASS, CritiqueDecision.PASS_WITH_WARNINGS} else "needs_more_research"
    tags = tuple(sorted(set(candidate.features + candidate.regime_tags + tuple(finding.code for finding in critique.findings))))
    return ResearchMemoryEntry(
        f"memory:{run_id}",
        candidate.family,
        candidate.market,
        candidate.timeframe,
        candidate.hypothesis,
        f"quality={quality.total:.1f}; decision={critique.decision.value}",
        "; ".join(finding.code for finding in critique.findings),
        "; ".join(action.finding_code for action in plan.actions),
        final_status,
        tags,
        created_at or utc_now(),
        run_id,
        candidate_fingerprint(candidate),
        candidate.source_refs,
    )


def fixture_candidate(kind: str = "balanced", *, strategy_id: str | None = None, family: str = "breakout", market: str = "KRX", timeframe: str = "daily", hypothesis: str = "Use volume-confirmed breakout with risk filters.", created_from_run_id: str = "fixture") -> StrategyCandidate:
    metrics: dict[str, float | int] = {
        "in_sample_sharpe": 1.35,
        "out_of_sample_sharpe": 1.05,
        "sample_size": 520,
        "trade_count": 64,
        "walk_forward_stability": 0.72,
        "monte_carlo_robustness": 0.7,
        "max_drawdown": 0.14,
        "parameter_stability": 0.7,
        "regime_dependency": 0.45,
        "liquidity_score": 0.72,
        "feature_complexity": 0.35,
        "profit_factor": 1.45,
    }
    if kind == "overfit":
        metrics.update({"in_sample_sharpe": 3.2, "out_of_sample_sharpe": 0.8, "parameter_stability": 0.35, "feature_complexity": 0.82, "profit_factor": 3.4})
    elif kind == "high_mdd":
        metrics.update({"max_drawdown": 0.31, "monte_carlo_robustness": 0.48})
    elif kind == "low_sample":
        metrics.update({"sample_size": 90, "trade_count": 12})
    elif kind == "unstable_wf":
        metrics.update({"walk_forward_stability": 0.35, "parameter_stability": 0.38})
    elif kind == "fragile":
        metrics.update({"monte_carlo_robustness": 0.32, "liquidity_score": 0.42})
    elif kind == "regime_dependent":
        metrics.update({"regime_dependency": 0.86})
    elif kind == "strong":
        metrics.update({"out_of_sample_sharpe": 1.55, "walk_forward_stability": 0.83, "monte_carlo_robustness": 0.82, "max_drawdown": 0.09, "trade_count": 88, "sample_size": 720})
    sid = strategy_id or f"fixture:{kind}"
    return StrategyCandidate(
        sid,
        family,
        market,
        timeframe,
        hypothesis,
        {"breakout_period": 20, "volume_multiplier": 1.5, "max_risk_pct": 1.0},
        metrics,
        ("relative_strength", "volume_change", "vwap"),
        ("bull", "sideways"),
        ("fixture:self-improving-research",),
        created_from_run_id=created_from_run_id,
    )


def fixture_candidates(count: int = 5) -> tuple[StrategyCandidate, ...]:
    kinds = ("strong", "balanced", "overfit", "high_mdd", "fragile", "low_sample", "unstable_wf", "regime_dependent")
    return tuple(fixture_candidate(kinds[index % len(kinds)], strategy_id=f"fixture:tournament:{index + 1}") for index in range(count))


def candidate_fingerprint(candidate: StrategyCandidate) -> str:
    payload = {
        "family": candidate.family,
        "market": candidate.market,
        "timeframe": candidate.timeframe,
        "hypothesis": candidate.hypothesis.casefold().strip(),
        "parameters": candidate.parameters,
        "features": list(candidate.features),
        "regime_tags": list(candidate.regime_tags),
    }
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def strategy_critique_payload(kind: str = "balanced") -> dict[str, object]:
    candidate = fixture_candidate(kind)
    critique = ResearchCritic().evaluate(candidate)
    plan = StrategyImprovementPlanner().plan(candidate, critique)
    return {"provider": "fixture:self-improving-research", "candidate": candidate.to_json(), "critique": critique.to_json(), "improvement_plan": plan.to_json(), "automatic_promotion": False}


def strategy_quality_payload(kind: str = "balanced") -> dict[str, object]:
    candidate = fixture_candidate(kind)
    critique = ResearchCritic().evaluate(candidate)
    score = ResearchQualityScorer().score(candidate, critique)
    return {"provider": "fixture:self-improving-research", "candidate": candidate.to_json(), "quality": score.to_json(), "automatic_promotion": False}


def research_candidate_compare_payload(top_n: int = 3) -> dict[str, object]:
    tournament = ResearchTournamentRunner().run(fixture_candidates(6), top_n=top_n)
    return {"provider": "fixture:self-improving-research", "tournament": tournament.to_json(), "automatic_promotion": False}


def _finding(code: str, severity: CritiqueSeverity, message: str, action: str) -> CritiqueFinding:
    return CritiqueFinding(code, severity, message, (f"metric:{code}", "fixture:self-improving-research"), action)


def _updates_for_finding(code: str) -> dict[str, float | int | str | bool]:
    mapping: dict[str, dict[str, float | int | str | bool]] = {
        "overfit_gap": {"walk_forward_required": True, "feature_pruning": True},
        "weak_sample": {"min_trade_count": 40},
        "wf_instability": {"walk_forward_required": True, "parameter_band": "wide"},
        "mc_fragility": {"monte_carlo_required": True, "max_risk_pct": 0.75},
        "high_mdd": {"max_risk_pct": 0.5, "drawdown_stop_pct": 8.0},
        "unstable_params": {"parameter_band": "wide"},
        "regime_dependency": {"regime_filter": "explicit"},
        "liquidity_assumption": {"min_liquidity_score": 0.65},
        "feature_complexity": {"feature_pruning": True},
        "suspicious_performance": {"leakage_check_required": True},
    }
    return mapping.get(code, {})


def _lineage_node(candidate: StrategyCandidate, created_at: str) -> StrategyLineageNode:
    return StrategyLineageNode(candidate.strategy_id, candidate.parent_strategy_id, candidate.root_strategy_id or candidate.strategy_id, candidate.generation, candidate.mutation_reason, candidate.created_from_run_id, created_at)


def _lineage_from_json(payload: dict[str, object]) -> StrategyLineageNode:
    _require_schema(payload)
    return StrategyLineageNode(str(payload["strategy_id"]), str(payload["parent_strategy_id"]) if payload.get("parent_strategy_id") else None, str(payload["root_strategy_id"]), int(payload["generation"]), str(payload["mutation_reason"]), str(payload["created_from_run_id"]), str(payload["created_at"]))


def _pct(value: float) -> float:
    return round(max(0.0, min(100.0, value * 100.0)), 3)


def _require_schema(payload: dict[str, object]) -> None:
    if int(payload.get("schema_version", -1)) != RESEARCH_SELF_IMPROVING_SCHEMA_VERSION:
        raise ValueError("unsupported self-improving research schema version")


def _json(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
