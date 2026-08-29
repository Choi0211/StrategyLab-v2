"""Evidence-grounded research-direction planning for a mission BLOCKED on
``strategy_hypothesis_space_exhausted`` (Hotfix #168).

Context: ``gaon.runtime.autonomous_research_runtime.attempt_bounded_stagnation_
recovery`` only reopens a STAGNANT candidate that stagnated purely on the
progress-stall bookkeeping threshold (``validation_cycle_exhausted_without_
progress``); every other terminal rejection reason - a decisive economic-
viability FAIL, a genuinely exhausted sample pool, a provider limitation -
is deliberately left alone, by design, because blindly reopening those would
re-run research the state machine already decided was a dead end. Once the
bounded 9-family declarative grammar (``STRATEGY_FAMILY_TEMPLATES`` +
``STRATEGY_SPACE_EXPANSION_TEMPLATES``) is fully represented in a mission's
candidate history with no such recoverable candidate, that narrow recovery
correctly reports ``blocked_no_recovery`` forever - which is honest, but
opaque: it degenerates into an unexplained repeating no-op with no durable
record of *why*, and (per production investigation) leaves no path for a
human operator to see what evidence would actually unblock the mission.

This module adds exactly one new stage, reachable only from that specific
dead end: EXHAUSTED -> FAILURE ANALYSIS -> RESEARCH PRIORITY -> RESEARCH
DIRECTION -> (EVIDENCE REQUIREMENTS surfaced) -> honest WAITING/terminal
state. It is research-space *planning*, not a new research engine:

- It never fabricates a 10th/11th/... declarative strategy family. The
  bounded grammar in ``gaon.knowledge.strategy_candidate`` is unchanged and
  untouched by this module.
- It never mutates strategy config, creates/promotes a candidate, creates an
  approval, or reaches any order/broker/champion-promotion code path -
  ``ResearchDirection`` creation writes only to the two tables this module
  owns (``research_failure_analyses``, ``research_directions``).
- It never calls ``LLMConversationBrain.respond()`` - it is a pure,
  deterministic read/plan/persist function over already-persisted
  ``ResearchMission``/``StrategyCandidateRecord`` state, so it can never
  contaminate conversation history or Cognitive Core feedback (the #164-#166
  system-turn isolation is preserved by construction: this module never
  produces a conversation turn at all).
- Idempotent by construction: both records are stored under a deterministic
  id derived from a fingerprint of the mission's terminal candidate history,
  and both writes are ``INSERT OR IGNORE`` - re-observing the exact same
  blocked state on a later tick is a cheap no-op read, never a duplicate
  row, even though ``attempt_bounded_stagnation_recovery`` (and therefore
  this module) is re-evaluated statelessly on every tick.

Research autonomy is never trading/capital authority: every
``ResearchDirection`` this module can produce is explicitly bounded to
``NextResearchAction`` values that this module itself never executes - it
only classifies, prioritizes, and records. Whether/how to act on a
``ResearchDirection`` (e.g. reviewing whether the bounded strategy grammar
should be extended) remains a human/developer decision.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from gaon.cognitive.sustainability import FORBIDDEN_JUSTIFICATIONS, SUSTAINABILITY_DIMENSIONS
from gaon.knowledge.research_mission import ResearchMission, candidate_records
from gaon.knowledge.strategy_candidate import (
    PASS_LIKE_STAGE_STATUSES,
    PROMOTION_MIN_TRADE_SAMPLE,
    StrategyCandidateRecord,
    StrategyCandidateStatus,
)
from gaon.research.research_priority import ResearchPriorityProposal


class NextResearchAction(str, Enum):
    """Actions this module may ever *record* as a direction's next step.
    This module never executes any of them itself - see module docstring."""

    GATHER_MORE_EVIDENCE = "gather_more_evidence"
    DIVERSIFY_EVIDENCE_SOURCE = "diversify_evidence_source"
    INVESTIGATE_COST_FRAGILITY = "investigate_cost_fragility"
    INVESTIGATE_REGIME_DEPENDENCY = "investigate_regime_dependency"
    EXPAND_HYPOTHESIS_FAMILY = "expand_hypothesis_family"
    REASSESS_MARKET_SCOPE = "reassess_market_scope"
    RUN_ROBUSTNESS_RESEARCH = "run_robustness_research"
    WAIT_FOR_REQUIRED_DATA = "wait_for_required_data"


class ResearchDirectionStatus(str, Enum):
    PROPOSED = "proposed"
    AWAITING_EVIDENCE = "awaiting_evidence"
    RETAINED = "retained"
    REJECTED = "rejected"


class FailureClass(str, Enum):
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    ECONOMIC_VIABILITY_FAILURE = "economic_viability_failure"
    COST_SLIPPAGE_FRAGILITY = "cost_slippage_fragility"
    ROBUSTNESS_FAILURE = "robustness_failure"
    REGIME_SENSITIVITY = "regime_sensitivity"
    EVIDENCE_INSUFFICIENCY = "evidence_insufficiency"
    DATA_PROVIDER_LIMITATION = "data_provider_limitation"
    VALIDATION_STAGNATION = "repeated_validation_stagnation"
    HYPOTHESIS_FAMILY_EXHAUSTION = "hypothesis_family_exhaustion"
    UNKNOWN = "unknown_unsupported_reason"


# Every structural (non-research-quality) reason a candidate can end up
# terminal (STAGNANT/REJECTED) with no genuine research obstacle behind it -
# excluded from failure-class evidence because it says nothing about *why*
# research stalled.
_NON_EVIDENCE_TERMINAL_REASONS = frozenset({"user_requested_different_strategy_family", "candidate_terminal"})

_INSUFFICIENT_SAMPLE_REASONS = frozenset(
    {
        "sample_pool_exhausted_without_sufficient_evidence",
        "sample_pool_exhausted_no_untried_robustness_symbol",
        "sample_pool_exhausted_below_monte_carlo_sample",
        "sample_pool_exhausted_after_attempted_validation_dimensions",
        "sample_pool_exhausted_insufficient_economic_evidence",
        "selected_symbol_universe_exhausted",
    }
)


def classify_candidate_failure(candidate: StrategyCandidateRecord) -> FailureClass | None:
    """Classifies why a terminal (STAGNANT/REJECTED) candidate stopped,
    reusing only real, already-persisted structured state - never a fresh
    guess. Returns ``None`` for a candidate that is not terminal (nothing to
    classify) or terminal purely by user request (not a research obstacle).
    """
    if candidate.status not in (StrategyCandidateStatus.STAGNANT, StrategyCandidateStatus.REJECTED):
        return None
    reason = candidate.rejected_reason or ""
    if not reason or reason in _NON_EVIDENCE_TERMINAL_REASONS:
        return None
    if reason.startswith("economic_viability_failed"):
        return FailureClass.ECONOMIC_VIABILITY_FAILURE
    if reason == "validation_cycle_exhausted_without_progress":
        return FailureClass.VALIDATION_STAGNATION
    if reason.startswith("provider_unavailable") or "provider" in reason:
        return FailureClass.DATA_PROVIDER_LIMITATION
    if reason in _INSUFFICIENT_SAMPLE_REASONS or reason.startswith("sample_pool_exhausted"):
        return FailureClass.INSUFFICIENT_SAMPLE
    stage_status = dict(candidate.validation_stage_status)

    def _attempted_and_failed(stage: str) -> bool:
        status = str(stage_status.get(stage, "not_run"))
        return status != "not_run" and status not in PASS_LIKE_STAGE_STATUSES

    if _attempted_and_failed("transaction_cost_stress"):
        return FailureClass.COST_SLIPPAGE_FRAGILITY
    if _attempted_and_failed("regime_validation"):
        return FailureClass.REGIME_SENSITIVITY
    if any(_attempted_and_failed(stage) for stage in ("out_of_sample", "walk_forward", "parameter_sensitivity", "monte_carlo")):
        return FailureClass.ROBUSTNESS_FAILURE
    if candidate.trade_count < PROMOTION_MIN_TRADE_SAMPLE or not candidate.has_sufficient_universe_evidence:
        return FailureClass.EVIDENCE_INSUFFICIENCY
    return FailureClass.UNKNOWN


# Fixed evidence-requirement text per failure class - reused verbatim by
# every direction of that class rather than freshly worded per call, so the
# rationale is reproducible and auditable, never freshly invented text.
_EVIDENCE_REQUIREMENTS: dict[FailureClass, tuple[str, ...]] = {
    FailureClass.INSUFFICIENT_SAMPLE: (
        "more independent evidence symbols beyond the mission's already-attempted universe",
    ),
    FailureClass.ECONOMIC_VIABILITY_FAILURE: (
        "additional real evidence samples with a positive/majority-profitable outcome, or a human-reviewed "
        "decision on whether this market/strategy-family combination is fundamentally not viable",
    ),
    FailureClass.COST_SLIPPAGE_FRAGILITY: (
        "transaction-cost/slippage sensitivity evidence, and confirmation the cost model matches live execution",
    ),
    FailureClass.REGIME_SENSITIVITY: ("evidence across additional market regimes/time windows",),
    FailureClass.ROBUSTNESS_FAILURE: ("a passing result on the remaining unresolved robustness validation stage",),
    FailureClass.EVIDENCE_INSUFFICIENCY: ("a larger real trade/symbol sample before an economic decision can be made",),
    FailureClass.DATA_PROVIDER_LIMITATION: ("an available data provider for the blocked request",),
    FailureClass.VALIDATION_STAGNATION: ("new material evidence changing the candidate's evidence revision",),
    FailureClass.HYPOTHESIS_FAMILY_EXHAUSTION: (
        "a human/developer-reviewed addition to the bounded declarative strategy-family grammar",
    ),
    FailureClass.UNKNOWN: ("human review of an unclassified rejection reason",),
}

# The "ideal" action a failure class would motivate if a live candidate/
# untried family existed to act on - purely informational (surfaced in
# allowed_research_scope); see plan_research_direction for what this
# planner is actually authorized to record as next_research_action.
_DESIRED_ACTION_FOR_CLASS: dict[FailureClass, NextResearchAction] = {
    FailureClass.INSUFFICIENT_SAMPLE: NextResearchAction.GATHER_MORE_EVIDENCE,
    FailureClass.ECONOMIC_VIABILITY_FAILURE: NextResearchAction.REASSESS_MARKET_SCOPE,
    FailureClass.COST_SLIPPAGE_FRAGILITY: NextResearchAction.INVESTIGATE_COST_FRAGILITY,
    FailureClass.REGIME_SENSITIVITY: NextResearchAction.INVESTIGATE_REGIME_DEPENDENCY,
    FailureClass.ROBUSTNESS_FAILURE: NextResearchAction.RUN_ROBUSTNESS_RESEARCH,
    FailureClass.EVIDENCE_INSUFFICIENCY: NextResearchAction.GATHER_MORE_EVIDENCE,
    FailureClass.DATA_PROVIDER_LIMITATION: NextResearchAction.DIVERSIFY_EVIDENCE_SOURCE,
    FailureClass.VALIDATION_STAGNATION: NextResearchAction.RUN_ROBUSTNESS_RESEARCH,
    FailureClass.HYPOTHESIS_FAMILY_EXHAUSTION: NextResearchAction.EXPAND_HYPOTHESIS_FAMILY,
    FailureClass.UNKNOWN: NextResearchAction.WAIT_FOR_REQUIRED_DATA,
}

# Structural actions this planner can never take regardless of failure
# class - reused verbatim on every ResearchDirection record it produces.
# Combines the sustainability objective's own forbidden-justification list
# (never repeated by hand) with the structural production actions a
# ResearchDirection must never trigger.
PROHIBITED_ACTIONS: tuple[str, ...] = tuple(
    dict.fromkeys(
        (
            "strategy_config_mutation",
            "candidate_promotion",
            "approval_creation",
            "approval_bypass",
            "order_execution",
            "champion_promotion",
            "strategy_auto_apply",
            *FORBIDDEN_JUSTIFICATIONS,
        )
    )
)


def _stable_fingerprint(*parts: str) -> str:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


@dataclass(frozen=True)
class FailureAnalysis:
    analysis_id: str
    session_ref: str
    mission_id: str
    blocked_reason: str
    breakdown: Mapping[str, int]
    dominant_failure_class: FailureClass
    evidence_candidate_ids: tuple[str, ...]
    fingerprint: str
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "analysis_id": self.analysis_id,
            "session_ref": self.session_ref,
            "mission_id": self.mission_id,
            "blocked_reason": self.blocked_reason,
            "breakdown": dict(self.breakdown),
            "dominant_failure_class": self.dominant_failure_class.value,
            "evidence_candidate_ids": list(self.evidence_candidate_ids),
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
        }


def mission_history_fingerprint(mission: ResearchMission, *, session_ref: str) -> str:
    """Deterministic fingerprint over exactly the fields a failure analysis
    depends on: the mission's blocked reason and every candidate's terminal
    identity (id/status/rejected_reason). Unchanged whenever the mission's
    candidate history is unchanged, so re-observing the same BLOCKED state
    on a later tick always resolves to the same id - the idempotency key
    the whole "don't regenerate every 15 minutes" requirement rests on."""
    candidate_parts = sorted(
        f"{candidate.candidate_id}:{candidate.status.value}:{candidate.rejected_reason or ''}"
        for candidate in candidate_records(mission)
    )
    return _stable_fingerprint(session_ref, mission.blocked_reason or "", *candidate_parts)


def analyze_mission_failure(mission: ResearchMission, *, session_ref: str, now: str) -> FailureAnalysis:
    """Pure, evidence-grounded failure analysis over a mission's already-
    persisted candidate history. Reuses ``classify_candidate_failure`` per
    terminal candidate; never re-runs research or reads anything beyond the
    mission itself."""
    terminal = tuple(
        candidate for candidate in candidate_records(mission) if candidate.status in (StrategyCandidateStatus.STAGNANT, StrategyCandidateStatus.REJECTED)
    )
    breakdown: dict[str, int] = {}
    evidence_ids: list[str] = []
    for candidate in terminal:
        failure_class = classify_candidate_failure(candidate)
        if failure_class is None:
            continue
        breakdown[failure_class.value] = breakdown.get(failure_class.value, 0) + 1
        evidence_ids.append(candidate.candidate_id)
    if breakdown:
        # Stable tie-break: first class (in FailureClass declaration order)
        # reaching the max count wins, never an arbitrary dict-iteration
        # pick, so the same breakdown always yields the same dominant class.
        max_count = max(breakdown.values())
        dominant = next(cls for cls in FailureClass if breakdown.get(cls.value, 0) == max_count)
    else:
        dominant = FailureClass.HYPOTHESIS_FAMILY_EXHAUSTION
    fingerprint = mission_history_fingerprint(mission, session_ref=session_ref)
    return FailureAnalysis(
        analysis_id=f"failure-analysis:{fingerprint}",
        session_ref=session_ref,
        mission_id=mission.mission_id,
        blocked_reason=mission.blocked_reason or "",
        breakdown=breakdown,
        dominant_failure_class=dominant,
        evidence_candidate_ids=tuple(evidence_ids),
        fingerprint=fingerprint,
        created_at=now,
    )


@dataclass(frozen=True)
class ResearchDirection:
    direction_id: str
    session_ref: str
    mission_id: str
    source_blocker: str
    failure_analysis_id: str
    priority: Mapping[str, object]
    rationale: str
    evidence_requirements: tuple[str, ...]
    allowed_research_scope: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    next_research_action: NextResearchAction
    status: ResearchDirectionStatus
    fingerprint: str
    created_at: str
    updated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "direction_id": self.direction_id,
            "session_ref": self.session_ref,
            "mission_id": self.mission_id,
            "source_blocker": self.source_blocker,
            "failure_analysis_id": self.failure_analysis_id,
            "priority": dict(self.priority),
            "rationale": self.rationale,
            "evidence_requirements": list(self.evidence_requirements),
            "allowed_research_scope": list(self.allowed_research_scope),
            "prohibited_actions": list(self.prohibited_actions),
            "next_research_action": self.next_research_action.value,
            "status": self.status.value,
            "fingerprint": self.fingerprint,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _rationale_for(analysis: FailureAnalysis, priority: ResearchPriorityProposal) -> str:
    breakdown_text = ", ".join(f"{name}={count}" for name, count in sorted(analysis.breakdown.items())) or "no classifiable terminal candidates"
    lines = [
        f"bounded strategy-hypothesis space exhausted ({len(analysis.evidence_candidate_ids)} terminal candidates observed): {breakdown_text}.",
        f"dominant obstacle: {analysis.dominant_failure_class.value}.",
    ]
    if "kr" in priority.flagged_domains:
        lines.append("kr domain has an unresolved structural flag alongside this exhaustion.")
    if "binance" in priority.flagged_domains:
        lines.append("binance domain research evidence is also flagged as incomplete; consider human review of relative research priority across domains.")
    return " ".join(lines)


def plan_research_direction(
    analysis: FailureAnalysis,
    priority: ResearchPriorityProposal,
    *,
    has_untried_family: bool,
    has_recoverable_candidate: bool,
    sustainability_dimensions: tuple[str, ...] = SUSTAINABILITY_DIMENSIONS,
    now: str,
) -> ResearchDirection:
    """Deterministic decision function producing exactly one
    ``ResearchDirection`` for the given failure analysis.

    ``has_untried_family``/``has_recoverable_candidate`` are supplied by the
    caller from the mission's own already-computed state
    (``next_untried_family``, ``attempt_bounded_stagnation_recovery``) -
    this function never recomputes them, so it can never disagree with the
    state machine about whether either already-existing mechanism applies.
    In production wiring (see ``gaon.runtime.autonomous_research_runtime``)
    this planner is only ever invoked once both are already False - the two
    branches below exist for completeness/testability of the full decision
    tree, not because production wiring reaches them today.
    """
    desired = _DESIRED_ACTION_FOR_CLASS.get(analysis.dominant_failure_class, NextResearchAction.WAIT_FOR_REQUIRED_DATA)
    if has_recoverable_candidate:
        # The existing narrow stagnation recovery already handles this case
        # upstream of this planner; recorded here only for observability if
        # a caller ever reaches this planner without checking first.
        next_action = NextResearchAction.RUN_ROBUSTNESS_RESEARCH
        status = ResearchDirectionStatus.PROPOSED
    elif has_untried_family:
        # next_untried_family already handles this case upstream; same as
        # above - completeness only.
        next_action = NextResearchAction.EXPAND_HYPOTHESIS_FAMILY
        status = ResearchDirectionStatus.PROPOSED
    else:
        # No live candidate to gather evidence on, and no untried family in
        # the bounded grammar - the honest, capability-grounded next step is
        # to wait for a human/developer decision, never to fabricate one.
        next_action = NextResearchAction.WAIT_FOR_REQUIRED_DATA
        status = ResearchDirectionStatus.AWAITING_EVIDENCE
    evidence_requirements = _EVIDENCE_REQUIREMENTS.get(analysis.dominant_failure_class, ("human review",))
    allowed_scope = tuple(dict.fromkeys((desired.value, next_action.value)))
    direction_id = f"research-direction:{analysis.fingerprint}"
    return ResearchDirection(
        direction_id=direction_id,
        session_ref=analysis.session_ref,
        mission_id=analysis.mission_id,
        source_blocker=analysis.blocked_reason,
        failure_analysis_id=analysis.analysis_id,
        priority={
            **priority.to_json(),
            "sustainability_dimensions_considered": list(sustainability_dimensions),
        },
        rationale=_rationale_for(analysis, priority),
        evidence_requirements=evidence_requirements,
        allowed_research_scope=allowed_scope,
        prohibited_actions=PROHIBITED_ACTIONS,
        next_research_action=next_action,
        status=status,
        fingerprint=analysis.fingerprint,
        created_at=now,
        updated_at=now,
    )


class ResearchDirectionRepository:
    """Durable storage for ``FailureAnalysis``/``ResearchDirection``
    records. Every write is ``INSERT OR IGNORE`` keyed by the deterministic
    fingerprint-derived id - re-planning against an unchanged mission state
    is always a cheap idempotent no-op, never a duplicate row."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put_failure_analysis(self, analysis: FailureAnalysis) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO research_failure_analyses
                (analysis_id, session_ref, mission_id, blocked_reason, dominant_failure_class,
                 failure_breakdown_json, evidence_candidate_ids_json, fingerprint, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                analysis.analysis_id,
                analysis.session_ref,
                analysis.mission_id,
                analysis.blocked_reason,
                analysis.dominant_failure_class.value,
                json.dumps(dict(analysis.breakdown)),
                json.dumps(list(analysis.evidence_candidate_ids)),
                analysis.fingerprint,
                analysis.created_at,
            ),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def find_failure_analysis_by_fingerprint(self, fingerprint: str) -> FailureAnalysis | None:
        row = self._connection.execute(
            "SELECT analysis_id, session_ref, mission_id, blocked_reason, dominant_failure_class, "
            "failure_breakdown_json, evidence_candidate_ids_json, fingerprint, created_at "
            "FROM research_failure_analyses WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            return None
        return FailureAnalysis(
            analysis_id=row[0],
            session_ref=row[1],
            mission_id=row[2],
            blocked_reason=row[3],
            dominant_failure_class=FailureClass(row[4]),
            breakdown=json.loads(row[5]),
            evidence_candidate_ids=tuple(json.loads(row[6])),
            fingerprint=row[7],
            created_at=row[8],
        )

    def put_direction(self, direction: ResearchDirection) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO research_directions
                (direction_id, session_ref, mission_id, source_blocker, failure_analysis_id,
                 priority_json, rationale, evidence_requirements_json, allowed_research_scope_json,
                 prohibited_actions_json, next_research_action, status, fingerprint, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                direction.direction_id,
                direction.session_ref,
                direction.mission_id,
                direction.source_blocker,
                direction.failure_analysis_id,
                json.dumps(dict(direction.priority)),
                direction.rationale,
                json.dumps(list(direction.evidence_requirements)),
                json.dumps(list(direction.allowed_research_scope)),
                json.dumps(list(direction.prohibited_actions)),
                direction.next_research_action.value,
                direction.status.value,
                direction.fingerprint,
                direction.created_at,
                direction.updated_at,
            ),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def find_direction_by_fingerprint(self, fingerprint: str) -> ResearchDirection | None:
        row = self._connection.execute(
            "SELECT direction_id, session_ref, mission_id, source_blocker, failure_analysis_id, priority_json, "
            "rationale, evidence_requirements_json, allowed_research_scope_json, prohibited_actions_json, "
            "next_research_action, status, fingerprint, created_at, updated_at "
            "FROM research_directions WHERE fingerprint = ?",
            (fingerprint,),
        ).fetchone()
        if row is None:
            return None
        return ResearchDirection(
            direction_id=row[0],
            session_ref=row[1],
            mission_id=row[2],
            source_blocker=row[3],
            failure_analysis_id=row[4],
            priority=json.loads(row[5]),
            rationale=row[6],
            evidence_requirements=tuple(json.loads(row[7])),
            allowed_research_scope=tuple(json.loads(row[8])),
            prohibited_actions=tuple(json.loads(row[9])),
            next_research_action=NextResearchAction(row[10]),
            status=ResearchDirectionStatus(row[11]),
            fingerprint=row[12],
            created_at=row[13],
            updated_at=row[14],
        )

    def count_directions_for_session(self, session_ref: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM research_directions WHERE session_ref = ?", (session_ref,)
        ).fetchone()
        return int(row[0]) if row else 0
