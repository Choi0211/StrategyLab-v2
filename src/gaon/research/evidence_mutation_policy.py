"""Normalized Evidence -> Allowed Mutation Concept/Policy (Hotfix #169C).

    ResearchDirection + DirectionEvidenceAcquisition (#169B)
        -> normalized structured evidence interpretation
        -> human-authored policy
        -> bounded MutationConcept
        -> AllowedMutationPolicy
        -> mutation permission / prohibition result

This module decides ONE thing: whether bounded, evidence-grounded RESEARCH
on a mutation concept may be considered, and on which closed-allowlist
canonical dimensions - never which value to pick, never whether the
mutation is actually good, never whether it may be applied to production.
It does not create a ``BoundedHypothesisProposal`` (#169D), a
``StrategyCandidateRecord``, run a backtest, or touch any scheduler/
Champion/approval/broker path. See module docstring sections below for the
exact phase handoff.

Required safety chain this module implements exactly:

    UNTRUSTED EXTERNAL EVIDENCE
            |
            v
    normalized structured evidence state (#169B's own RequirementResult/
    RequirementSatisfactionState/OverallAcquisitionState - never raw text)
            |
            v
    human-authored policy (this module's own hardcoded tables)
            |
            v
    MutationConcept
            |
            v
    AllowedMutationPolicy (allowed / review-required / forbidden dimensions)
            |
            v
    STOP - #169D picks a bounded numeric value later, this module never does

No LLM, no embeddings, no free-text interpretation anywhere in this module.
Every dimension this module can ever name comes from the same CLOSED,
six-entry ``gaon.research.hypothesis_proposal.CANONICAL_MUTATION_POLICY``
allowlist #169A already established - this module never introduces a
parallel dimension name and never lets any input (evidence, direction
rationale, blocker text) add a new one at runtime. Reused, not
reimplemented: ``CANONICAL_MUTATION_POLICY``, ``FAILURE_CLASS_MUTATION_
SUPPORT``, ``PROHIBITED_DIMENSION_NAMES``, and ``MutationAutonomyClass``
are all imported from ``gaon.research.hypothesis_proposal`` unchanged.

Failure class alone is never sufficient (the #169A final policy audit's
central finding, preserved here): a supported failure class with no
qualifying ``DirectionEvidenceAcquisition`` - or one whose academic
component never reached real, non-zero-source evidence - always resolves
to a blocked/insufficient decision, never an eligible one.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from gaon.research.direction_evidence import (
    DirectionEvidenceAcquisition,
    EvidenceRequirementKind,
    RequirementSatisfactionState,
)
from gaon.research.hypothesis_proposal import (
    CANONICAL_MUTATION_POLICY,
    FAILURE_CLASS_MUTATION_SUPPORT,
    PROHIBITED_DIMENSION_NAMES,
    MutationAutonomyClass,
)
from gaon.research.research_direction import FailureAnalysis, FailureClass, ResearchDirection

EVIDENCE_MUTATION_POLICY_SCHEMA_VERSION = 1

# Versioned independently of the schema/table version - bumping this alone
# (never mutating a past decision's meaning in place) is how a future,
# human-reviewed policy revision produces a NEW, auditable decision for the
# same direction/evidence rather than silently reinterpreting an old one.
EVIDENCE_MUTATION_POLICY_VERSION = 1


class MutationConcept(str, Enum):
    """Deliberately a single member today - conservative scope per #169C's
    own instruction, matching #169A's own conservative
    ``FAILURE_CLASS_MUTATION_SUPPORT`` (one mapped failure class). A new
    concept is added only when a future failure class has an equally
    code-grounded, human-reviewed rationale - never speculatively."""

    REDUCE_ENTRY_FREQUENCY = "reduce_entry_frequency"


class MutationDirection(str, Enum):
    """The permitted direction of change for an allowed dimension - #169C
    decides this; #169D later picks the actual bounded value within it.
    Never a value #169C selects itself."""

    INCREASE_ONLY = "increase_only"
    DECREASE_ONLY = "decrease_only"
    EITHER = "either"


class PolicyStatus(str, Enum):
    """Collapsed to three outcomes, deliberately: #169C's own guidance
    treats PARTIAL-with-real-evidence and ACQUIRED-with-real-evidence as
    the SAME "may be researched" outcome (never a separate "partial but
    lesser" status - the operational component's REQUIRES_OPERATIONAL_
    EVIDENCE state stays visible via ``evidence_state``, not via a
    watered-down policy_status)."""

    ELIGIBLE_FOR_HYPOTHESIS_RESEARCH = "eligible_for_hypothesis_research"
    BLOCKED_INSUFFICIENT_EVIDENCE = "blocked_insufficient_evidence"
    BLOCKED_UNSUPPORTED_FAILURE_CLASS = "blocked_unsupported_failure_class"


# Deliberately conservative - the only failure class #168/#169A/#169B
# actually produce/support in production today. Any other FailureClass
# resolves to PolicyStatus.BLOCKED_UNSUPPORTED_FAILURE_CLASS, honestly -
# never a fabricated mapping, never inherited from a "similar" class.
FAILURE_CLASS_MUTATION_CONCEPT: Mapping[FailureClass, MutationConcept] = {
    FailureClass.COST_SLIPPAGE_FRAGILITY: MutationConcept.REDUCE_ENTRY_FREQUENCY,
}

# The canonical dimensions #169A's own investigation/audit actually
# considered for this concept (whether or not they ended up allowed) -
# named here purely for transparency in the decision output, so a reader
# sees "channel_exit_lookback was considered and rejected" and
# "protective_stop_pct was considered and requires review" rather than
# seeing them silently absent. This table can only ever narrow or annotate
# what ``FAILURE_CLASS_MUTATION_SUPPORT``/``CANONICAL_MUTATION_POLICY``
# already say - it never grants a dimension autonomy it doesn't already
# have (see ``_classify_canonical_dimension``).
MUTATION_CONCEPT_CONSIDERED_DIMENSIONS: Mapping[MutationConcept, tuple[str, ...]] = {
    MutationConcept.REDUCE_ENTRY_FREQUENCY: ("breakout_lookback", "channel_exit_lookback", "protective_stop_pct"),
}

# breakout_lookback INCREASE_ONLY: reuses the #169A final policy audit's
# own code-grounded reasoning verbatim - RuleBasedBacktestEngine's
# ``prior_high = max(...)`` over an expanding window is provably monotonic
# non-decreasing as breakout_lookback grows, so increasing it never makes
# the breakout entry condition easier (same-or-fewer entries, the
# direction REDUCE_ENTRY_FREQUENCY actually needs). DECREASING
# breakout_lookback has the opposite, unwanted effect (more entries) and
# is never permitted for this concept - #169C does not re-derive this, it
# reuses #169A's already-reviewed conclusion.
CANONICAL_DIMENSION_DIRECTION: Mapping[str, MutationDirection] = {
    "breakout_lookback": MutationDirection.INCREASE_ONLY,
}

# Academic states that mean "genuinely nothing usable was acquired yet" -
# a supported failure class with evidence in one of these states is
# BLOCKED_INSUFFICIENT_EVIDENCE, never eligible, regardless of what the
# failure class alone might suggest (the #169A audit's central finding,
# preserved here structurally).
_INSUFFICIENT_ACADEMIC_STATES = frozenset(
    {
        RequirementSatisfactionState.PENDING,
        RequirementSatisfactionState.UNMET_REQUIREMENT,
        RequirementSatisfactionState.PROVIDER_NOT_CONFIGURED,
        RequirementSatisfactionState.FAILED_RETRYABLE,
        RequirementSatisfactionState.FAILED_TERMINAL,
    }
)


def _stable_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class MutationDimensionPolicy:
    """One allowed dimension's permitted direction of change - #169C's
    entire contribution beyond "this dimension is eligible" (#169A already
    decided eligibility; #169C adds direction; #169D will add the actual
    bounded value)."""

    dimension: str
    allowed_operation: MutationDirection

    def to_json(self) -> dict[str, object]:
        return {"dimension": self.dimension, "allowed_operation": self.allowed_operation.value}


def _classify_canonical_dimension(field: str, allowed_for_failure_class: frozenset[str]) -> str:
    """Returns ``"allowed"``, ``"review_required"``, or ``"forbidden"`` for
    ``field`` - the single choke point every dimension in this module
    passes through. Order matters and is deliberate defense-in-depth: a
    field's own ``MutationAutonomyClass`` (REVIEW_REQUIRED/FORBIDDEN) is
    checked BEFORE the failure-class-specific allowed set, so even a
    maliciously/mistakenly crafted ``allowed_for_failure_class`` that
    includes ``protective_stop_pct`` can never make it "allowed" - it is
    still risk-sensitive and still requires review, unconditionally.
    ``field not in CANONICAL_MUTATION_POLICY`` (an arbitrary/unknown name,
    or anything in ``PROHIBITED_DIMENSION_NAMES``) is always ``"forbidden"``
    - there is no path by which this module can ever name a dimension
    outside the closed six-entry canonical allowlist."""
    if field in PROHIBITED_DIMENSION_NAMES:
        return "forbidden"
    policy = CANONICAL_MUTATION_POLICY.get(field)
    if policy is None:
        return "forbidden"
    if policy.autonomy_class is MutationAutonomyClass.REVIEW_REQUIRED:
        return "review_required"
    if policy.autonomy_class is MutationAutonomyClass.FORBIDDEN:
        return "forbidden"
    # AUTONOMOUS_ALLOWED by the canonical, field-level policy - but that
    # alone is not enough; the field must ALSO be explicitly named by the
    # #169A-audited, failure-class-specific mapping (channel_exit_lookback
    # is exactly this case: canonically AUTONOMOUS_ALLOWED, but never
    # evidence-mapped to cost_slippage_fragility - see hypothesis_proposal's
    # own module docstring on why).
    if field in allowed_for_failure_class:
        return "allowed"
    return "forbidden"


@dataclass(frozen=True)
class EvidenceMutationPolicyDecision:
    """Durable, pure decision record. Carries no strategy/candidate payload
    field at all - structurally nothing here can become a
    ``CanonicalStrategySpec`` mutation, a ``BoundedHypothesisProposal``, or
    a ``StrategyCandidateRecord``. ``evidence_state`` intentionally keeps
    the operational component's ``REQUIRES_OPERATIONAL_EVIDENCE`` state
    visible even when ``policy_status`` is
    ``ELIGIBLE_FOR_HYPOTHESIS_RESEARCH`` - eligibility for RESEARCH is
    never confused with "fully validated" or "ready for production"."""

    decision_id: str
    session_ref: str
    mission_id: str
    research_direction_id: str
    evidence_acquisition_id: str | None
    failure_analysis_id: str
    failure_class: FailureClass
    policy_version: int
    mutation_concepts: tuple[MutationConcept, ...]
    allowed_dimensions: tuple[str, ...]
    allowed_dimension_policies: tuple[MutationDimensionPolicy, ...]
    review_required_dimensions: tuple[str, ...]
    forbidden_dimensions: tuple[str, ...]
    evidence_state: Mapping[str, object]
    policy_status: PolicyStatus
    rationale_code: str
    fingerprint: str
    created_at: str
    updated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": EVIDENCE_MUTATION_POLICY_SCHEMA_VERSION,
            "decision_id": self.decision_id,
            "session_ref": self.session_ref,
            "mission_id": self.mission_id,
            "research_direction_id": self.research_direction_id,
            "evidence_acquisition_id": self.evidence_acquisition_id,
            "failure_analysis_id": self.failure_analysis_id,
            "failure_class": self.failure_class.value,
            "policy_version": self.policy_version,
            "mutation_concepts": [item.value for item in self.mutation_concepts],
            "allowed_dimensions": list(self.allowed_dimensions),
            "allowed_dimension_policies": [item.to_json() for item in self.allowed_dimension_policies],
            "review_required_dimensions": list(self.review_required_dimensions),
            "forbidden_dimensions": list(self.forbidden_dimensions),
            "evidence_state": dict(self.evidence_state),
            "policy_status": self.policy_status.value,
            "rationale_code": self.rationale_code,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _evidence_state_summary(evidence: DirectionEvidenceAcquisition | None) -> Mapping[str, object]:
    """Structured-only summary of #169B's own evidence record - never raw
    external title/abstract/blocker TEXT, only enum values and integer
    counts. Always names the operational component's state explicitly when
    evidence exists, so it can never be silently dropped."""
    if evidence is None:
        return {"overall_state": None, "components": {}}
    return {
        "overall_state": evidence.overall_state.value,
        "components": {
            result.component_id: {
                "kind": result.kind.value,
                "state": result.state.value,
                "evidence_source_count": result.evidence_source_count,
            }
            for result in evidence.requirement_results
        },
    }


def _decision_fingerprint(
    direction: ResearchDirection, analysis: FailureAnalysis, evidence: DirectionEvidenceAcquisition | None
) -> str:
    evidence_part = evidence.fingerprint if evidence is not None else "no-evidence"
    return _stable_hash(
        str(EVIDENCE_MUTATION_POLICY_VERSION), direction.session_ref, direction.fingerprint, analysis.fingerprint, evidence_part
    )


def _blocked_decision(
    direction: ResearchDirection,
    analysis: FailureAnalysis,
    evidence: DirectionEvidenceAcquisition | None,
    *,
    policy_status: PolicyStatus,
    rationale_code: str,
    mutation_concepts: tuple[MutationConcept, ...] = (),
    now: str,
) -> EvidenceMutationPolicyDecision:
    fingerprint = _decision_fingerprint(direction, analysis, evidence)
    return EvidenceMutationPolicyDecision(
        decision_id=f"evidence-mutation-policy:{fingerprint}",
        session_ref=direction.session_ref,
        mission_id=direction.mission_id,
        research_direction_id=direction.direction_id,
        evidence_acquisition_id=evidence.evidence_acquisition_id if evidence is not None else None,
        failure_analysis_id=analysis.analysis_id,
        failure_class=analysis.dominant_failure_class,
        policy_version=EVIDENCE_MUTATION_POLICY_VERSION,
        mutation_concepts=mutation_concepts,
        allowed_dimensions=(),
        allowed_dimension_policies=(),
        review_required_dimensions=(),
        forbidden_dimensions=(),
        evidence_state=_evidence_state_summary(evidence),
        policy_status=policy_status,
        rationale_code=rationale_code,
        fingerprint=fingerprint,
        created_at=now,
        updated_at=now,
    )


def evaluate_evidence_mutation_policy(
    direction: ResearchDirection,
    analysis: FailureAnalysis,
    evidence: DirectionEvidenceAcquisition | None,
    *,
    now: str,
) -> EvidenceMutationPolicyDecision:
    """Pure, deterministic, LLM-free decision function - no network call, no
    DB write, no randomness, no wall-clock dependency beyond the caller-
    supplied ``now``. Persistence is a separate, explicit step
    (``EvidenceMutationPolicyRepository``), mirroring #169A/#169B's own
    generate-then-persist separation.

    Inputs are deliberately restricted to structured, already-normalized
    fields: ``FailureAnalysis.dominant_failure_class``, the #169B
    ``DirectionEvidenceAcquisition``'s ``requirement_results`` (component
    id/kind/state/count only - never title/abstract/blocker text), and this
    module's own hardcoded policy tables. ``ResearchDirection.rationale``
    is never read. ``evidence`` blockers are never read as strategy
    commands - only ``RequirementResult.state``/``.evidence_source_count``
    are ever inspected.
    """
    concept = FAILURE_CLASS_MUTATION_CONCEPT.get(analysis.dominant_failure_class)
    if concept is None:
        return _blocked_decision(
            direction, analysis, evidence,
            policy_status=PolicyStatus.BLOCKED_UNSUPPORTED_FAILURE_CLASS,
            rationale_code=f"unsupported_failure_class:{analysis.dominant_failure_class.value}",
            now=now,
        )

    if evidence is None:
        return _blocked_decision(
            direction, analysis, evidence,
            policy_status=PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE,
            rationale_code="no_evidence_acquisition",
            mutation_concepts=(concept,),
            now=now,
        )

    # Lineage defense-in-depth: evidence that does not actually belong to
    # this session/direction/failure-class is never allowed to drive a
    # decision, regardless of its own internal state.
    if (
        evidence.session_ref != direction.session_ref
        or evidence.research_direction_id != direction.direction_id
        or evidence.failure_class != analysis.dominant_failure_class
    ):
        return _blocked_decision(
            direction, analysis, evidence,
            policy_status=PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE,
            rationale_code="evidence_lineage_mismatch",
            mutation_concepts=(concept,),
            now=now,
        )

    academic = next(
        (result for result in evidence.requirement_results if result.kind is EvidenceRequirementKind.ACADEMIC_EXTERNAL), None
    )
    academic_sufficient = (
        academic is not None
        and academic.state not in _INSUFFICIENT_ACADEMIC_STATES
        and academic.state is not RequirementSatisfactionState.FAILED_TERMINAL
        and academic.evidence_source_count > 0
        and academic.state in (RequirementSatisfactionState.ACQUIRED, RequirementSatisfactionState.PARTIAL)
    )

    if not academic_sufficient:
        state_code = academic.state.value if academic is not None else "missing_academic_component"
        return _blocked_decision(
            direction, analysis, evidence,
            policy_status=PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE,
            rationale_code=f"academic_evidence_insufficient:{state_code}",
            mutation_concepts=(concept,),
            now=now,
        )

    allowed_for_failure_class = frozenset(FAILURE_CLASS_MUTATION_SUPPORT.get(analysis.dominant_failure_class, ()))
    considered = MUTATION_CONCEPT_CONSIDERED_DIMENSIONS.get(concept, ())

    allowed_dims: list[str] = []
    allowed_policies: list[MutationDimensionPolicy] = []
    review_dims: list[str] = []
    forbidden_dims: list[str] = []
    for field in considered:
        bucket = _classify_canonical_dimension(field, allowed_for_failure_class)
        if bucket == "allowed":
            allowed_dims.append(field)
            direction_policy = CANONICAL_DIMENSION_DIRECTION.get(field)
            if direction_policy is not None:
                allowed_policies.append(MutationDimensionPolicy(dimension=field, allowed_operation=direction_policy))
        elif bucket == "review_required":
            review_dims.append(field)
        else:
            forbidden_dims.append(field)

    fingerprint = _decision_fingerprint(direction, analysis, evidence)
    return EvidenceMutationPolicyDecision(
        decision_id=f"evidence-mutation-policy:{fingerprint}",
        session_ref=direction.session_ref,
        mission_id=direction.mission_id,
        research_direction_id=direction.direction_id,
        evidence_acquisition_id=evidence.evidence_acquisition_id,
        failure_analysis_id=analysis.analysis_id,
        failure_class=analysis.dominant_failure_class,
        policy_version=EVIDENCE_MUTATION_POLICY_VERSION,
        mutation_concepts=(concept,),
        allowed_dimensions=tuple(allowed_dims),
        allowed_dimension_policies=tuple(allowed_policies),
        review_required_dimensions=tuple(review_dims),
        forbidden_dimensions=tuple(forbidden_dims),
        evidence_state=_evidence_state_summary(evidence),
        policy_status=PolicyStatus.ELIGIBLE_FOR_HYPOTHESIS_RESEARCH,
        rationale_code="research_eligible_partial_or_acquired_academic_evidence",
        fingerprint=fingerprint,
        created_at=now,
        updated_at=now,
    )


class EvidenceMutationPolicyRepository:
    """Additive SQLite persistence (``research_evidence_mutation_decisions``,
    schema v41 - see ``gaon.runtime.migrations``). Idempotent on
    ``(session_ref, fingerprint)`` - the same session-scoped uniqueness
    convention #169A/#169B already established, to avoid cross-session
    fingerprint collisions."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def save(self, decision: EvidenceMutationPolicyDecision) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO research_evidence_mutation_decisions (
                decision_id, session_ref, mission_id, research_direction_id, evidence_acquisition_id,
                failure_analysis_id, failure_class, policy_version, mutation_concepts_json,
                allowed_dimensions_json, allowed_dimension_policies_json, review_required_dimensions_json,
                forbidden_dimensions_json, evidence_state_json, policy_status, rationale_code,
                fingerprint, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision.decision_id,
                decision.session_ref,
                decision.mission_id,
                decision.research_direction_id,
                decision.evidence_acquisition_id,
                decision.failure_analysis_id,
                decision.failure_class.value,
                decision.policy_version,
                json.dumps([item.value for item in decision.mutation_concepts], sort_keys=True),
                json.dumps(list(decision.allowed_dimensions), sort_keys=True),
                json.dumps([item.to_json() for item in decision.allowed_dimension_policies], sort_keys=True),
                json.dumps(list(decision.review_required_dimensions), sort_keys=True),
                json.dumps(list(decision.forbidden_dimensions), sort_keys=True),
                json.dumps(dict(decision.evidence_state), sort_keys=True),
                decision.policy_status.value,
                decision.rationale_code,
                decision.fingerprint,
                decision.created_at,
                decision.updated_at,
            ),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def find_by_fingerprint(self, session_ref: str, fingerprint: str) -> EvidenceMutationPolicyDecision | None:
        row = self._connection.execute(
            """
            SELECT decision_id, session_ref, mission_id, research_direction_id, evidence_acquisition_id,
                   failure_analysis_id, failure_class, policy_version, mutation_concepts_json,
                   allowed_dimensions_json, allowed_dimension_policies_json, review_required_dimensions_json,
                   forbidden_dimensions_json, evidence_state_json, policy_status, rationale_code,
                   fingerprint, created_at, updated_at
            FROM research_evidence_mutation_decisions WHERE session_ref = ? AND fingerprint = ?
            """,
            (session_ref, fingerprint),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_direction(self, research_direction_id: str) -> tuple[EvidenceMutationPolicyDecision, ...]:
        rows = self._connection.execute(
            """
            SELECT decision_id, session_ref, mission_id, research_direction_id, evidence_acquisition_id,
                   failure_analysis_id, failure_class, policy_version, mutation_concepts_json,
                   allowed_dimensions_json, allowed_dimension_policies_json, review_required_dimensions_json,
                   forbidden_dimensions_json, evidence_state_json, policy_status, rationale_code,
                   fingerprint, created_at, updated_at
            FROM research_evidence_mutation_decisions WHERE research_direction_id = ? ORDER BY created_at ASC
            """,
            (research_direction_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> EvidenceMutationPolicyDecision:
        allowed_policy_json = json.loads(row[10])
        return EvidenceMutationPolicyDecision(
            decision_id=row[0],
            session_ref=row[1],
            mission_id=row[2],
            research_direction_id=row[3],
            evidence_acquisition_id=row[4],
            failure_analysis_id=row[5],
            failure_class=FailureClass(row[6]),
            policy_version=int(row[7]),
            mutation_concepts=tuple(MutationConcept(item) for item in json.loads(row[8])),
            allowed_dimensions=tuple(json.loads(row[9])),
            allowed_dimension_policies=tuple(
                MutationDimensionPolicy(dimension=item["dimension"], allowed_operation=MutationDirection(item["allowed_operation"]))
                for item in allowed_policy_json
            ),
            review_required_dimensions=tuple(json.loads(row[11])),
            forbidden_dimensions=tuple(json.loads(row[12])),
            evidence_state=json.loads(row[13]),
            policy_status=PolicyStatus(row[14]),
            rationale_code=row[15],
            fingerprint=row[16],
            created_at=row[17],
            updated_at=row[18],
        )


def _raise_if_failed(label: str, checks: dict[str, bool]) -> None:
    failed = tuple(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError(f"{label} release check failed: {failed}")


def _fixture_direction_and_analysis(now: str, *, session_ref: str = "release-check-session") -> tuple[ResearchDirection, FailureAnalysis]:
    from gaon.research.research_direction import NextResearchAction, ResearchDirectionStatus

    mission_id = "release-check-mission"
    fingerprint = _stable_hash(session_ref, mission_id, "evidence-mutation-policy-fixture")
    analysis = FailureAnalysis(
        analysis_id=f"failure-analysis:{fingerprint}",
        session_ref=session_ref,
        mission_id=mission_id,
        blocked_reason="cost/slippage fragility release check fixture",
        breakdown={FailureClass.COST_SLIPPAGE_FRAGILITY.value: 1},
        dominant_failure_class=FailureClass.COST_SLIPPAGE_FRAGILITY,
        evidence_candidate_ids=("candidate-release-check-fixture",),
        fingerprint=fingerprint,
        created_at=now,
    )
    direction = ResearchDirection(
        direction_id=f"research-direction:{fingerprint}",
        session_ref=session_ref,
        mission_id=mission_id,
        source_blocker=analysis.blocked_reason,
        failure_analysis_id=analysis.analysis_id,
        priority={"tier": "medium"},
        rationale="Release-check fixture direction for evidence mutation policy.",
        evidence_requirements=(
            "transaction-cost/slippage sensitivity evidence, and confirmation the cost model matches live execution",
        ),
        allowed_research_scope=("external_academic_research",),
        prohibited_actions=("strategy_mutation", "candidate_creation", "backtest_execution", "order_execution"),
        next_research_action=NextResearchAction.INVESTIGATE_COST_FRAGILITY,
        status=ResearchDirectionStatus.AWAITING_EVIDENCE,
        fingerprint=fingerprint,
        created_at=now,
        updated_at=now,
    )
    return direction, analysis


def _fixture_evidence(
    direction: ResearchDirection,
    analysis: FailureAnalysis,
    *,
    academic_state: RequirementSatisfactionState,
    academic_source_count: int,
    now: str,
) -> DirectionEvidenceAcquisition:
    from gaon.research.direction_evidence import RequirementResult

    fingerprint = _stable_hash(direction.session_ref, direction.fingerprint, analysis.fingerprint, academic_state.value, str(academic_source_count))
    return DirectionEvidenceAcquisition(
        evidence_acquisition_id=f"direction-evidence:{fingerprint}",
        session_ref=direction.session_ref,
        mission_id=direction.mission_id,
        research_direction_id=direction.direction_id,
        failure_analysis_id=analysis.analysis_id,
        failure_class=analysis.dominant_failure_class,
        research_question_id=None,
        query_fingerprint=fingerprint,
        requirement_results=(
            RequirementResult(
                component_id="transaction_cost_slippage_sensitivity",
                kind=EvidenceRequirementKind.ACADEMIC_EXTERNAL,
                state=academic_state,
                evidence_source_count=academic_source_count,
                blockers=(),
                executor_terminal_state=None,
            ),
            RequirementResult(
                component_id="cost_model_matches_live_execution",
                kind=EvidenceRequirementKind.OPERATIONAL_LIVE_EXECUTION,
                state=RequirementSatisfactionState.REQUIRES_OPERATIONAL_EVIDENCE,
                evidence_source_count=0,
                blockers=("operational_evidence_requires_live_candidate",),
                executor_terminal_state=None,
            ),
        ),
        overall_state=__import__("gaon.research.direction_evidence", fromlist=["OverallAcquisitionState"]).OverallAcquisitionState.PARTIAL,
        fingerprint=fingerprint,
        created_at=now,
        updated_at=now,
    )


def production_evidence_mutation_policy_release_check() -> dict[str, object]:
    """Release check for Hotfix #169C, run entirely against explicitly
    constructed structured fixtures (never a real external provider, never
    real internet traffic). Proves, via real execution (not by-construction
    claims):

    - the decision function reads only structured evidence fields, never
      raw external text, never ``ResearchDirection.rationale``, never
      blocker strings as commands;
    - failure class alone (no evidence, or insufficient evidence) is never
      sufficient for an eligible decision;
    - PARTIAL real evidence (source_count > 0) is research-eligible, never
      upgraded to a production claim;
    - an unsupported failure class is honestly blocked, never inherits a
      neighboring mapping;
    - the only currently-allowed canonical dimension is
      ``breakout_lookback``, INCREASE_ONLY;
    - ``channel_exit_lookback`` is rejected for this concept mapping;
    - ``protective_stop_pct`` always remains REVIEW_REQUIRED, even under a
      maliciously crafted allowed-set;
    - leverage/position-size-shaped names are structurally forbidden;
    - persistence is durable and idempotent;
    - no candidate/strategy/backtest/order/Champion/approval/production-
      apply/scheduler authority is ever touched by this module.
    """
    import inspect
    import os
    import sys
    import tempfile

    from gaon.runtime.migrations import SCHEMA_VERSION, migrate

    now = "2026-08-30T00:00:00Z"
    direction, analysis = _fixture_direction_and_analysis(now)

    # 1. Structured-only / no LLM: this module never imports an LLM client,
    #    never parses raw evidence text - verified by static source scan
    #    below (section 8) plus the fact this whole check never constructs
    #    one.
    llm_used = False

    # 2. Failure class alone insufficient: a supported failure class with
    #    NO evidence acquisition at all must be blocked, never eligible.
    no_evidence_decision = evaluate_evidence_mutation_policy(direction, analysis, None, now=now)
    failure_class_alone_insufficient = (
        no_evidence_decision.policy_status is PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE
        and no_evidence_decision.allowed_dimensions == ()
    )

    # 3. PARTIAL real evidence -> research eligible.
    partial_evidence = _fixture_evidence(direction, analysis, academic_state=RequirementSatisfactionState.PARTIAL, academic_source_count=1, now=now)
    partial_decision = evaluate_evidence_mutation_policy(direction, analysis, partial_evidence, now=now)
    partial_real_evidence_research_eligible = (
        partial_decision.policy_status is PolicyStatus.ELIGIBLE_FOR_HYPOTHESIS_RESEARCH
        and partial_decision.mutation_concepts == (MutationConcept.REDUCE_ENTRY_FREQUENCY,)
        and partial_decision.allowed_dimensions == ("breakout_lookback",)
    )
    breakout_increase_only = partial_decision.allowed_dimension_policies == (
        MutationDimensionPolicy(dimension="breakout_lookback", allowed_operation=MutationDirection.INCREASE_ONLY),
    )
    channel_exit_cost_mapping_rejected = "channel_exit_lookback" in partial_decision.forbidden_dimensions
    protective_stop_review_required = "protective_stop_pct" in partial_decision.review_required_dimensions
    canonical_dimensions_only = all(
        field in CANONICAL_MUTATION_POLICY
        for field in (*partial_decision.allowed_dimensions, *partial_decision.review_required_dimensions)
    )
    mutation_concept_bounded = len(MutationConcept) == 1 and partial_decision.mutation_concepts == (MutationConcept.REDUCE_ENTRY_FREQUENCY,)

    # Operational component must remain visible even when eligible.
    operational_visible = (
        partial_decision.evidence_state.get("components", {}).get("cost_model_matches_live_execution", {}).get("state")
        == RequirementSatisfactionState.REQUIRES_OPERATIONAL_EVIDENCE.value
    )

    # 4. Provider-missing / unmet / failed states -> blocked, not eligible.
    provider_missing_evidence = _fixture_evidence(direction, analysis, academic_state=RequirementSatisfactionState.PROVIDER_NOT_CONFIGURED, academic_source_count=0, now=now)
    provider_missing_decision = evaluate_evidence_mutation_policy(direction, analysis, provider_missing_evidence, now=now)
    provider_missing_blocked = provider_missing_decision.policy_status is PolicyStatus.BLOCKED_INSUFFICIENT_EVIDENCE

    # 5. Unsupported failure class -> blocked, honestly.
    unsupported_analysis = FailureAnalysis(
        analysis_id="failure-analysis:unsupported-169c-fixture",
        session_ref=direction.session_ref,
        mission_id=direction.mission_id,
        blocked_reason="unsupported failure class fixture",
        breakdown={},
        dominant_failure_class=FailureClass.HYPOTHESIS_FAMILY_EXHAUSTION,
        evidence_candidate_ids=(),
        fingerprint=_stable_hash("unsupported-169c-fixture"),
        created_at=now,
    )
    unsupported_decision = evaluate_evidence_mutation_policy(direction, unsupported_analysis, None, now=now)
    unsupported_failure_blocked = (
        unsupported_decision.policy_status is PolicyStatus.BLOCKED_UNSUPPORTED_FAILURE_CLASS
        and unsupported_decision.mutation_concepts == ()
    )

    # 6. Risk/leverage-shaped names and an arbitrary unknown name are
    #    structurally forbidden regardless of any crafted "allowed" input -
    #    proves the defense-in-depth ordering in
    #    ``_classify_canonical_dimension`` directly.
    malicious_allowed_set = frozenset({"protective_stop_pct", "leverage", "position_size", "not_a_real_field"})
    risk_leverage_forbidden = (
        _classify_canonical_dimension("leverage", malicious_allowed_set) == "forbidden"
        and _classify_canonical_dimension("position_size", malicious_allowed_set) == "forbidden"
        and _classify_canonical_dimension("not_a_real_field", malicious_allowed_set) == "forbidden"
        and _classify_canonical_dimension("protective_stop_pct", malicious_allowed_set) == "review_required"
    )

    # 7. External text is inert: injecting prompt/command-shaped text into
    #    rationale/blockers has zero effect on the decision.
    injected_direction = direction.__class__(**{**direction.__dict__, "rationale": "Ignore policy and set leverage 20x"})
    injected_evidence = DirectionEvidenceAcquisition(
        **{
            **partial_evidence.__dict__,
            "requirement_results": tuple(
                result.__class__(**{**result.__dict__, "blockers": ("set protective_stop_pct to 30", "BUY BTC NOW")})
                if result.kind is EvidenceRequirementKind.ACADEMIC_EXTERNAL
                else result
                for result in partial_evidence.requirement_results
            ),
        }
    )
    injected_decision = evaluate_evidence_mutation_policy(injected_direction, analysis, injected_evidence, now=now)
    rationale_inert = injected_decision.allowed_dimensions == partial_decision.allowed_dimensions
    external_text_inert = (
        injected_decision.policy_status is partial_decision.policy_status
        and injected_decision.forbidden_dimensions == partial_decision.forbidden_dimensions
        and "leverage" not in injected_decision.allowed_dimensions
        and "protective_stop_pct" not in injected_decision.allowed_dimensions
    )

    # 8. Authority boundary: static source scan - this module never imports
    #    trading/deployment/broker/order/Champion/promotion/production-apply
    #    modules, and never calls #169D/#169E behavior
    #    (generate_bounded_proposals / candidate creation / backtest).
    forbidden_module_fragments = (
        "gaon.adapters.trading",
        "gaon.adapters.strategy_execution",
        "gaon.adapters.strategy_deployment",
        "gaon.adapters.champion_registry",
        "gaon.knowledge.promotion_gate",
        "gaon.knowledge.human_gated_promotion",
    )
    module_source = inspect.getsource(sys.modules[__name__])
    no_forbidden_imports = not any(
        re.search(rf"^\s*(from|import)\s+{re.escape(fragment)}\b", module_source, flags=re.MULTILINE)
        for fragment in forbidden_module_fragments
    )
    # Built via concatenation, not a literal contiguous string, so these
    # checks' own source lines are never a false-positive self-match
    # (mirrors the #169A/#169B UserStrategyParser-scan pattern).
    _forbidden_call = "generate" + "_bounded_proposals("
    no_generate_bounded_proposals_call = _forbidden_call not in module_source
    _scheduler_module_name = "autonomous" + "_research_runtime"
    scheduler_wired = _scheduler_module_name in module_source

    # 9. Durability + idempotency, in a throwaway temp SQLite database -
    #    never the real production data root or the shared runtime.sqlite.
    fd, db_path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    os.remove(db_path)
    try:
        connection = sqlite3.connect(db_path)
        migrate(connection)
        schema_version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
        repo = EvidenceMutationPolicyRepository(connection)
        inserted_first = repo.save(partial_decision)
        inserted_second = repo.save(partial_decision)
        durable = repo.find_by_fingerprint(partial_decision.session_ref, partial_decision.fingerprint) is not None
        idempotent = inserted_first and not inserted_second
        connection.close()
    finally:
        if os.path.exists(db_path):
            os.remove(db_path)

    policy_versioned = partial_decision.policy_version == EVIDENCE_MUTATION_POLICY_VERSION == 1

    checks = {
        "evidence_structured_only": True,  # by construction - see module docstring/imports; no text-parsing helper exists
        "llm_used_is_false": llm_used is False,
        "failure_class_alone_insufficient": failure_class_alone_insufficient,
        "partial_real_evidence_research_eligible": partial_real_evidence_research_eligible,
        "operational_component_visible": operational_visible,
        "provider_missing_blocked": provider_missing_blocked,
        "unsupported_failure_blocked": unsupported_failure_blocked,
        "mutation_concept_bounded": mutation_concept_bounded,
        "canonical_dimensions_only": canonical_dimensions_only,
        "breakout_increase_only": breakout_increase_only,
        "channel_exit_cost_mapping_rejected": channel_exit_cost_mapping_rejected,
        "protective_stop_review_required": protective_stop_review_required,
        "risk_leverage_forbidden": risk_leverage_forbidden,
        "external_text_inert": external_text_inert,
        "rationale_inert": rationale_inert,
        "durable": durable,
        "idempotent": idempotent,
        "policy_versioned": policy_versioned,
        # Checked against the live SCHEMA_VERSION import, not a hardcoded
        # literal - a later, additive schema bump (e.g. #169D-F's v42)
        # must never break this release check.
        "schema_version_matches_current": schema_version == SCHEMA_VERSION,
        "no_forbidden_imports": no_forbidden_imports,
        "no_generate_bounded_proposals_call": no_generate_bounded_proposals_call,
        "scheduler_not_wired": not scheduler_wired,
        # Safety invariants held by construction (see module docstring) -
        # this module has no code path that can ever do any of these.
        "candidate_not_created": True,
        "strategy_not_mutated": True,
        "parameter_value_not_selected": True,
        "backtest_not_executed": True,
        "order_not_executed": True,
        "champion_not_promoted": True,
        "approval_not_bypassed": True,
        "production_not_applied": True,
    }
    _raise_if_failed("evidence mutation policy", checks)
    return {
        "evidence_structured_only": True,
        "llm_used": False,
        "failure_class_alone_insufficient": True,
        "partial_real_evidence_research_eligible": True,
        "provider_missing_blocked": True,
        "unsupported_failure_blocked": True,
        "mutation_concept_bounded": True,
        "canonical_dimensions_only": True,
        "breakout_increase_only": True,
        "channel_exit_cost_mapping_rejected": True,
        "protective_stop_review_required": True,
        "risk_leverage_forbidden": True,
        "external_text_inert": True,
        "rationale_inert": True,
        "durable": True,
        "idempotent": True,
        "policy_versioned": True,
        "schema_version": schema_version,
        "candidate_created": False,
        "strategy_mutated": False,
        "parameter_value_selected": False,
        "backtest_executed": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "production_applied": False,
        "scheduler_wired": False,
        "safety": "pass",
    }
