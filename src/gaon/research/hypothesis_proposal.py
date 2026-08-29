"""Canonical Mutation Surface + Durable Hypothesis Proposal (Hotfix #169A).

This module is the FOUNDATION for a future evidence-grounded hypothesis
generator (#169B/C/D/E/F) - it is explicitly NOT autonomous research
execution. It defines and persists ``BoundedHypothesisProposal`` records,
nothing more:

    ResearchDirection -> BoundedHypothesisProposal -> READY_FOR_EVIDENCE

Not yet present (deliberately, out of #169A's scope):
- no external evidence acquisition (candidate-independent or otherwise)
- no ``StrategyCandidateRecord`` creation
- no backtest/validation execution
- no autonomous runtime/scheduler wiring
- no production strategy mutation of any kind

Core safety invariant - free-text strategy generation is structurally
impossible here: every mutation this module can ever produce reads its
``field`` from the closed, six-entry ``CANONICAL_MUTATION_POLICY`` allowlist
(exactly ``CanonicalStrategySpec``'s real entry/exit/filters fields - see
``gaon.research.krx_real_pipeline``) and its ``proposed_value`` from a
deterministic function of already-persisted historical template values
(``gaon.knowledge.strategy_candidate.ALL_STRATEGY_FAMILY_TEMPLATES``) or a
boolean toggle. ``UserStrategyParser`` (the only free-text -> strategy path
in this codebase) is never imported or called anywhere in this module -
every ``CanonicalStrategySpec`` this module touches is either an existing
candidate's already-persisted ``spec_rules`` (reconstructed via the
existing, reused ``gaon.research.multi_symbol._strategy_from_candidate_spec``)
or a template built via the existing ``gaon.knowledge.strategy_candidate.
build_candidate_spec``. No parallel strategy model is introduced.

No field in ``CanonicalStrategySpec`` represents leverage, position sizing,
capital allocation, or any live-execution/broker parameter - confirmed
structurally absent by the #169 architecture investigation, not merely
policy-forbidden. ``PROHIBITED_DIMENSION_NAMES`` documents this boundary
explicitly and is asserted against in tests: none of those names can ever
appear as a ``ProposalMutation.field`` because they are not, and can never
become, real allowlist entries in this module.

External evidence text is NEVER an input to mutation VALUE selection in
this module (or in any future phase) - only to WHICH ALLOWLISTED DIMENSION
a policy table (``FAILURE_CLASS_MUTATION_SUPPORT``, itself human-authored
and versioned, never LLM-derived) says is worth researching for a given
failure class. Raw external text is never executed as a strategy rule,
now or in any planned future phase.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from gaon.knowledge.strategy_candidate import ALL_STRATEGY_FAMILY_TEMPLATES, StrategyCandidateRecord
from gaon.research.krx_real_pipeline import CanonicalStrategySpec, FieldProvenance, ProvenancedValue
from gaon.research.multi_symbol import _strategy_from_candidate_spec
from gaon.research.research_direction import FailureAnalysis, FailureClass, ResearchDirection, classify_candidate_failure

HYPOTHESIS_PROPOSAL_SCHEMA_VERSION = 1


class MutationMethod(str, Enum):
    """How a candidate value is deterministically produced - never a free
    choice. Both methods are grounded entirely in data already persisted in
    this repository (see module docstring)."""

    HISTORICAL_NEIGHBOR_GRID = "historical_neighbor_grid"
    BOOLEAN_TOGGLE = "boolean_toggle"


class MutationRiskClass(str, Enum):
    ENTRY_THRESHOLD = "entry_threshold"
    EXIT_THRESHOLD = "exit_threshold"
    ENTRY_FILTER = "entry_filter"
    LIQUIDITY_FILTER = "liquidity_filter"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    UNSUPPORTED = "unsupported"
    READY_FOR_EVIDENCE = "ready_for_evidence"


# Concepts that must never become a mutation dimension - CanonicalStrategySpec
# has no field for any of these today (confirmed structurally absent by the
# #169 investigation), so this list exists purely as a defensive, tested
# boundary: if any of these strings ever appears as a ProposalMutation.field,
# that is a bug this module's own tests must catch (see
# test_hypothesis_proposal.py's forbidden-dimension test).
PROHIBITED_DIMENSION_NAMES: frozenset[str] = frozenset(
    {
        "leverage",
        "position_size",
        "position_sizing",
        "capital_allocation",
        "initial_capital",
        "daily_loss_limit",
        "protective_stop_removed",
        "validation_threshold",
        "approval_state",
        "promotion_state",
        "live_execution",
        "broker_config",
        "order_config",
        "quantity",
        "cost_model",
        "slippage",
    }
)


def _historical_values(dict_name: str, field_name: str) -> tuple[object, ...]:
    """Every distinct value ``field_name`` takes across the ALREADY-PERSISTED
    declarative template grammar (``ALL_STRATEGY_FAMILY_TEMPLATES`` - the
    same 9 templates #168/#169's own investigation exhaustively catalogued).
    This is the domain a bounded mutation may move within - never a value
    invented by this module."""
    values: list[object] = []
    for template in ALL_STRATEGY_FAMILY_TEMPLATES:
        source = getattr(template, dict_name)
        if field_name in source:
            value = source[field_name]
            if value not in values:
                values.append(value)
    if values and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in values):
        return tuple(sorted(values))
    return tuple(values)


@dataclass(frozen=True)
class MutationPolicyEntry:
    field_name: str
    dict_name: str  # "entry" | "exit" | "filters"
    allowed: bool
    mutation_method: MutationMethod | None
    allowed_values: tuple[object, ...]
    risk_class: MutationRiskClass | None
    evidence_requirement: str
    prohibited_reason: str | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "field_name": self.field_name,
            "dict_name": self.dict_name,
            "allowed": self.allowed,
            "mutation_method": self.mutation_method.value if self.mutation_method else None,
            "allowed_values": list(self.allowed_values),
            "risk_class": self.risk_class.value if self.risk_class else None,
            "evidence_requirement": self.evidence_requirement,
            "prohibited_reason": self.prohibited_reason,
        }


# The CLOSED, six-entry canonical mutation surface - exactly the fields
# gaon.research.krx_real_pipeline.RuleBasedBacktestEngine actually
# interprets (confirmed exhaustively by the #169 architecture
# investigation: no other entry/exit/filters key is ever assigned anywhere
# in this repository). Every entry is "allowed" because none of the six
# touch risk sizing, leverage, or capital - that category of field does not
# exist in CanonicalStrategySpec at all (see PROHIBITED_DIMENSION_NAMES).
CANONICAL_MUTATION_POLICY: Mapping[str, MutationPolicyEntry] = {
    "breakout_lookback": MutationPolicyEntry(
        field_name="breakout_lookback",
        dict_name="entry",
        allowed=True,
        mutation_method=MutationMethod.HISTORICAL_NEIGHBOR_GRID,
        allowed_values=_historical_values("entry", "breakout_lookback"),
        risk_class=MutationRiskClass.ENTRY_THRESHOLD,
        evidence_requirement="evidence that the parent candidate's entry signal frequency/turnover contributed to its failure",
    ),
    "channel_exit_lookback": MutationPolicyEntry(
        field_name="channel_exit_lookback",
        dict_name="exit",
        allowed=True,
        mutation_method=MutationMethod.HISTORICAL_NEIGHBOR_GRID,
        allowed_values=_historical_values("exit", "channel_exit_lookback"),
        risk_class=MutationRiskClass.EXIT_THRESHOLD,
        evidence_requirement="evidence that the parent candidate's holding-period/exit timing contributed to its failure",
    ),
    "protective_stop_pct": MutationPolicyEntry(
        field_name="protective_stop_pct",
        dict_name="exit",
        allowed=True,
        mutation_method=MutationMethod.HISTORICAL_NEIGHBOR_GRID,
        allowed_values=_historical_values("exit", "protective_stop_pct"),
        risk_class=MutationRiskClass.EXIT_THRESHOLD,
        evidence_requirement="evidence that the parent candidate's stop-loss placement contributed to its failure",
    ),
    "close_gt_ma20": MutationPolicyEntry(
        field_name="close_gt_ma20",
        dict_name="entry",
        allowed=True,
        mutation_method=MutationMethod.BOOLEAN_TOGGLE,
        allowed_values=(False, True),
        risk_class=MutationRiskClass.ENTRY_FILTER,
        evidence_requirement="evidence relating trend-filter presence/absence to the parent candidate's failure",
    ),
    "ma20_gt_ma60": MutationPolicyEntry(
        field_name="ma20_gt_ma60",
        dict_name="entry",
        allowed=True,
        mutation_method=MutationMethod.BOOLEAN_TOGGLE,
        allowed_values=(False, True),
        risk_class=MutationRiskClass.ENTRY_FILTER,
        evidence_requirement="evidence relating trend-filter presence/absence to the parent candidate's failure",
    ),
    "volume_gte_ma20": MutationPolicyEntry(
        field_name="volume_gte_ma20",
        dict_name="filters",
        allowed=True,
        mutation_method=MutationMethod.BOOLEAN_TOGGLE,
        allowed_values=(False, True),
        risk_class=MutationRiskClass.LIQUIDITY_FILTER,
        evidence_requirement="evidence relating liquidity/volume-filter presence/absence to the parent candidate's failure",
    ),
}


# Which of the six allowed dimensions is actually justified, by real
# CanonicalStrategySpec semantics, as a research target for a given failure
# class - deliberately conservative for #169A (only the failure class
# actually observed in production, cost_slippage_fragility, is mapped).
# "direction" is +1 (move to the next larger historical value / toggle
# True) when evidence-directed reasoning supports that direction, per the
# #169 architecture investigation's Evidence -> Mutation Mapping findings:
# a larger breakout_lookback/channel_exit_lookback means fewer, more
# selective signals and longer holds, i.e. lower turnover under the fixed
# cost assumption - never re-derived at runtime, this is the versioned,
# human-authored policy itself.
#
# economic_viability_failure and robustness_failure are deliberately NOT
# mapped: the investigation found no CanonicalStrategySpec field that
# plausibly and specifically addresses either (see Hotfix169A doc, Known
# Limitations) - fabricating a mapping for either would violate the
# explicit "don't invent meaning" instruction. Any failure class not a key
# of this mapping resolves to ProposalStatus.UNSUPPORTED, honestly.
FAILURE_CLASS_MUTATION_SUPPORT: Mapping[FailureClass, tuple[str, ...]] = {
    FailureClass.COST_SLIPPAGE_FRAGILITY: ("breakout_lookback", "channel_exit_lookback"),
}


@dataclass(frozen=True)
class MutationBudget:
    """Conservative defaults, scaled to match existing repository
    convention magnitude (never invented from nothing):
    ``max_dimensions_changed_per_proposal=1`` matches the #169
    investigation's explicit "one-dimensional mutation as default"
    guidance; ``max_proposals_per_direction=2`` reuses the exact same
    magnitude as ``attempt_bounded_stagnation_recovery``'s
    ``max_candidates=2`` scan bound (``gaon.runtime.autonomous_research_
    runtime``) - the closest existing precedent for "how many things this
    layer of the system is allowed to consider per bounded pass"."""

    max_dimensions_changed_per_proposal: int = 1
    max_proposals_per_direction: int = 2


DEFAULT_MUTATION_BUDGET = MutationBudget()


def _stable_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _next_historical_value(current: object, allowed_values: tuple[object, ...]) -> object | None:
    """Deterministic HISTORICAL_NEIGHBOR_GRID mutation: the next value
    strictly greater than ``current`` within the already-observed
    historical domain. Returns ``None`` (never extrapolates, never
    invents) when ``current`` is already at or above the historical
    maximum - an honest bounds-exhaustion signal, not a fabricated value."""
    greater = sorted(value for value in allowed_values if value > current)
    return greater[0] if greater else None


def _toggled(current: object) -> object:
    return not bool(current)


@dataclass(frozen=True)
class ProposalMutation:
    field: str
    dict_name: str
    old_value: object
    proposed_value: object
    mutation_method: MutationMethod
    rationale: str
    evidence_requirement: str

    def to_json(self) -> dict[str, object]:
        return {
            "field": self.field,
            "dict_name": self.dict_name,
            "old_value": self.old_value,
            "proposed_value": self.proposed_value,
            "mutation_method": self.mutation_method.value,
            "rationale": self.rationale,
            "evidence_requirement": self.evidence_requirement,
        }


@dataclass(frozen=True)
class BoundedHypothesisProposal:
    proposal_id: str
    session_ref: str
    mission_id: str
    research_direction_id: str
    source_failure_analysis_id: str
    parent_candidate_ids: tuple[str, ...]
    base_strategy_spec: Mapping[str, object]
    mutations: tuple[ProposalMutation, ...]
    mutation_count: int
    mutation_budget: int
    novelty_fingerprint: str
    validation_requirements: tuple[str, ...]
    prohibited_dimensions: tuple[str, ...]
    status: ProposalStatus
    rationale: str
    created_at: str
    updated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": HYPOTHESIS_PROPOSAL_SCHEMA_VERSION,
            "proposal_id": self.proposal_id,
            "session_ref": self.session_ref,
            "mission_id": self.mission_id,
            "research_direction_id": self.research_direction_id,
            "source_failure_analysis_id": self.source_failure_analysis_id,
            "parent_candidate_ids": list(self.parent_candidate_ids),
            "base_strategy_spec": dict(self.base_strategy_spec),
            "mutations": [mutation.to_json() for mutation in self.mutations],
            "mutation_count": self.mutation_count,
            "mutation_budget": self.mutation_budget,
            "novelty_fingerprint": self.novelty_fingerprint,
            "validation_requirements": list(self.validation_requirements),
            "prohibited_dimensions": list(self.prohibited_dimensions),
            "status": self.status.value,
            "rationale": self.rationale,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _mutated_spec_fingerprint(base_strategy_spec: Mapping[str, object], mutation: ProposalMutation) -> str:
    """Applies exactly one mutation to a reconstructed CanonicalStrategySpec
    and returns the REAL, production ``strategy_family_fingerprint`` of the
    result - reusing the exact fingerprint computation every existing
    candidate already uses (gaon.research.krx_real_pipeline.
    CanonicalStrategySpec.strategy_family_fingerprint), never a parallel
    hashing scheme. Confirmed by the #169 investigation to already be
    parameter-value-granular (a changed field value always yields a
    different fingerprint)."""
    spec = _strategy_from_candidate_spec(base_strategy_spec, symbol="000000", created_at="1970-01-01T00:00:00Z")
    target = getattr(spec, mutation.dict_name)
    mutated_field = dict(target)
    mutated_field[mutation.field] = ProvenancedValue(mutation.proposed_value, FieldProvenance.RESEARCH_CANDIDATE)
    mutated = {
        "entry": dict(spec.entry),
        "exit": dict(spec.exit),
        "filters": dict(spec.filters),
    }
    mutated[mutation.dict_name] = mutated_field
    mutated_spec = CanonicalStrategySpec(
        spec_id=spec.spec_id, symbol=spec.symbol, entry=mutated["entry"], exit=mutated["exit"], filters=mutated["filters"],
        source_text=spec.source_text, created_at=spec.created_at,
    )
    return mutated_spec.strategy_family_fingerprint


def _unsupported_proposal(
    research_direction: ResearchDirection,
    failure_analysis: FailureAnalysis,
    *,
    reason: str,
    now: str,
) -> BoundedHypothesisProposal:
    fingerprint = _stable_hash("unsupported", research_direction.fingerprint, reason)
    return BoundedHypothesisProposal(
        proposal_id=f"hypothesis-proposal:{fingerprint}",
        session_ref=research_direction.session_ref,
        mission_id=research_direction.mission_id,
        research_direction_id=research_direction.direction_id,
        source_failure_analysis_id=failure_analysis.analysis_id,
        parent_candidate_ids=(),
        base_strategy_spec={},
        mutations=(),
        mutation_count=0,
        mutation_budget=0,
        novelty_fingerprint=f"unsupported:{fingerprint}",
        validation_requirements=(),
        prohibited_dimensions=tuple(sorted(PROHIBITED_DIMENSION_NAMES)),
        status=ProposalStatus.UNSUPPORTED,
        rationale=reason,
        created_at=now,
        updated_at=now,
    )


def generate_bounded_proposals(
    research_direction: ResearchDirection,
    failure_analysis: FailureAnalysis,
    candidate_history: tuple[StrategyCandidateRecord, ...],
    *,
    mutation_policy: Mapping[str, MutationPolicyEntry] = CANONICAL_MUTATION_POLICY,
    failure_class_support: Mapping[FailureClass, tuple[str, ...]] = FAILURE_CLASS_MUTATION_SUPPORT,
    budget: MutationBudget = DEFAULT_MUTATION_BUDGET,
    existing_proposal_fingerprints: frozenset[str] = frozenset(),
    now: str,
) -> tuple[BoundedHypothesisProposal, ...]:
    """Pure, deterministic core generator - no network call, no LLM call,
    no DB write. Persistence is a separate, explicit step
    (``BoundedHypothesisProposalRepository``) so this function can be
    called, tested, and reasoned about entirely offline.

    Returns exactly one ``UNSUPPORTED`` proposal (never a bare empty tuple)
    when the dominant failure class has no human-authored, evidence-
    justified mutation mapping - an honest, idempotent record of "checked,
    nothing safe to propose" rather than silence. Otherwise returns up to
    ``budget.max_proposals_per_direction`` proposals, each changing exactly
    ``budget.max_dimensions_changed_per_proposal`` canonical field(s),
    each deduplicated against both existing candidate history and any
    proposal fingerprint the caller already knows about.
    """
    allowed_dimensions = failure_class_support.get(failure_analysis.dominant_failure_class)
    if not allowed_dimensions:
        return (
            _unsupported_proposal(
                research_direction,
                failure_analysis,
                reason=f"no evidence-justified canonical mutation mapping exists for failure class "
                f"'{failure_analysis.dominant_failure_class.value}' in this repository today",
                now=now,
            ),
        )

    parent = next(
        (
            candidate
            for candidate in candidate_history
            if candidate.candidate_id in failure_analysis.evidence_candidate_ids
            and classify_candidate_failure(candidate) == failure_analysis.dominant_failure_class
        ),
        None,
    )
    if parent is None or not parent.spec_rules:
        return (
            _unsupported_proposal(
                research_direction,
                failure_analysis,
                reason="no terminal candidate with a reconstructable strategy spec was found for the dominant failure class",
                now=now,
            ),
        )

    existing_candidate_fingerprints = frozenset(candidate.strategy_fingerprint for candidate in candidate_history)
    base_strategy_spec = dict(parent.spec_rules)

    proposals: list[BoundedHypothesisProposal] = []
    for field in allowed_dimensions:
        if len(proposals) >= budget.max_proposals_per_direction:
            break
        policy = mutation_policy.get(field)
        if policy is None or not policy.allowed:
            continue
        current = dict(base_strategy_spec.get(policy.dict_name) or {}).get(field, {}).get("value")
        if current is None:
            continue
        if policy.mutation_method is MutationMethod.HISTORICAL_NEIGHBOR_GRID:
            proposed_value = _next_historical_value(current, policy.allowed_values)
        elif policy.mutation_method is MutationMethod.BOOLEAN_TOGGLE:
            proposed_value = _toggled(current)
        else:
            proposed_value = None
        if proposed_value is None or proposed_value == current:
            continue

        mutation = ProposalMutation(
            field=field,
            dict_name=policy.dict_name,
            old_value=current,
            proposed_value=proposed_value,
            mutation_method=policy.mutation_method,
            rationale=(
                f"failure class '{failure_analysis.dominant_failure_class.value}' observed on "
                f"{len(failure_analysis.evidence_candidate_ids)} terminal candidate(s); "
                f"{field} moved from {current!r} to {proposed_value!r} per the versioned "
                "cost/turnover-direction policy for this failure class"
            ),
            evidence_requirement=policy.evidence_requirement,
        )
        if 1 > budget.max_dimensions_changed_per_proposal:
            # Defensive: this loop only ever builds a single-field mutation
            # per proposal, so this only trips if a future caller passes a
            # budget of 0 - never silently exceed it instead.
            continue

        novelty_fingerprint = _mutated_spec_fingerprint(base_strategy_spec, mutation)
        fingerprint_key = _stable_hash(research_direction.fingerprint, field, repr(proposed_value))
        proposal_id = f"hypothesis-proposal:{fingerprint_key}"

        if novelty_fingerprint in existing_candidate_fingerprints:
            status = ProposalStatus.DUPLICATE
            rationale = f"mutated spec fingerprint matches an existing candidate ({novelty_fingerprint[:16]}...) - identical strategy already tried"
        elif novelty_fingerprint in existing_proposal_fingerprints:
            status = ProposalStatus.DUPLICATE
            rationale = "mutated spec fingerprint matches a previously persisted proposal - identical proposal already exists"
        elif field not in CANONICAL_MUTATION_POLICY or field in PROHIBITED_DIMENSION_NAMES:
            status = ProposalStatus.REJECTED
            rationale = f"field '{field}' is not an allowed canonical mutation dimension"
        else:
            status = ProposalStatus.READY_FOR_EVIDENCE
            rationale = mutation.rationale

        proposals.append(
            BoundedHypothesisProposal(
                proposal_id=proposal_id,
                session_ref=research_direction.session_ref,
                mission_id=research_direction.mission_id,
                research_direction_id=research_direction.direction_id,
                source_failure_analysis_id=failure_analysis.analysis_id,
                parent_candidate_ids=(parent.candidate_id,),
                base_strategy_spec=base_strategy_spec,
                mutations=(mutation,),
                mutation_count=1,
                mutation_budget=budget.max_dimensions_changed_per_proposal,
                novelty_fingerprint=novelty_fingerprint,
                validation_requirements=(
                    "out_of_sample", "regime_validation", "walk_forward", "transaction_cost_stress",
                    "parameter_sensitivity", "monte_carlo",
                ),
                prohibited_dimensions=tuple(sorted(PROHIBITED_DIMENSION_NAMES)),
                status=status,
                rationale=rationale,
                created_at=now,
                updated_at=now,
            )
        )
    if not proposals:
        return (
            _unsupported_proposal(
                research_direction,
                failure_analysis,
                reason="all allowed dimensions for this failure class are already at their historical bound - no further deterministic value exists",
                now=now,
            ),
        )
    return tuple(proposals)


class BoundedHypothesisProposalRepository:
    """Durable storage - every write is ``INSERT OR IGNORE`` keyed by the
    deterministic ``proposal_id``, so re-generating against an unchanged
    research direction/mutation is always a cheap idempotent no-op, never a
    duplicate row (mirrors ``gaon.research.research_direction.
    ResearchDirectionRepository``'s exact pattern)."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put(self, proposal: BoundedHypothesisProposal) -> bool:
        cursor = self._connection.execute(
            """
            INSERT OR IGNORE INTO research_hypothesis_proposals
                (proposal_id, session_ref, mission_id, research_direction_id, source_failure_analysis_id,
                 parent_candidate_ids_json, base_strategy_spec_json, mutations_json, mutation_count,
                 mutation_budget, novelty_fingerprint, validation_requirements_json, prohibited_dimensions_json,
                 status, rationale, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                proposal.proposal_id,
                proposal.session_ref,
                proposal.mission_id,
                proposal.research_direction_id,
                proposal.source_failure_analysis_id,
                json.dumps(list(proposal.parent_candidate_ids)),
                json.dumps(dict(proposal.base_strategy_spec)),
                json.dumps([mutation.to_json() for mutation in proposal.mutations]),
                proposal.mutation_count,
                proposal.mutation_budget,
                proposal.novelty_fingerprint,
                json.dumps(list(proposal.validation_requirements)),
                json.dumps(list(proposal.prohibited_dimensions)),
                proposal.status.value,
                proposal.rationale,
                proposal.created_at,
                proposal.updated_at,
            ),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def _from_row(self, row: tuple) -> BoundedHypothesisProposal:
        mutations = tuple(
            ProposalMutation(
                field=item["field"],
                dict_name=item["dict_name"],
                old_value=item["old_value"],
                proposed_value=item["proposed_value"],
                mutation_method=MutationMethod(item["mutation_method"]),
                rationale=item["rationale"],
                evidence_requirement=item["evidence_requirement"],
            )
            for item in json.loads(row[7])
        )
        return BoundedHypothesisProposal(
            proposal_id=row[0],
            session_ref=row[1],
            mission_id=row[2],
            research_direction_id=row[3],
            source_failure_analysis_id=row[4],
            parent_candidate_ids=tuple(json.loads(row[5])),
            base_strategy_spec=json.loads(row[6]),
            mutations=mutations,
            mutation_count=row[8],
            mutation_budget=row[9],
            novelty_fingerprint=row[10],
            validation_requirements=tuple(json.loads(row[11])),
            prohibited_dimensions=tuple(json.loads(row[12])),
            status=ProposalStatus(row[13]),
            rationale=row[14],
            created_at=row[15],
            updated_at=row[16],
        )

    _COLUMNS = (
        "proposal_id, session_ref, mission_id, research_direction_id, source_failure_analysis_id, "
        "parent_candidate_ids_json, base_strategy_spec_json, mutations_json, mutation_count, mutation_budget, "
        "novelty_fingerprint, validation_requirements_json, prohibited_dimensions_json, status, rationale, "
        "created_at, updated_at"
    )

    def find_by_proposal_id(self, proposal_id: str) -> BoundedHypothesisProposal | None:
        row = self._connection.execute(
            f"SELECT {self._COLUMNS} FROM research_hypothesis_proposals WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def find_by_novelty_fingerprint(self, session_ref: str, novelty_fingerprint: str) -> BoundedHypothesisProposal | None:
        row = self._connection.execute(
            f"SELECT {self._COLUMNS} FROM research_hypothesis_proposals WHERE session_ref = ? AND novelty_fingerprint = ?",
            (session_ref, novelty_fingerprint),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_direction(self, research_direction_id: str) -> tuple[BoundedHypothesisProposal, ...]:
        rows = self._connection.execute(
            f"SELECT {self._COLUMNS} FROM research_hypothesis_proposals WHERE research_direction_id = ? ORDER BY created_at",
            (research_direction_id,),
        ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def count_for_direction(self, research_direction_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) FROM research_hypothesis_proposals WHERE research_direction_id = ?",
            (research_direction_id,),
        ).fetchone()
        return int(row[0]) if row else 0

    def existing_fingerprints_for_session(self, session_ref: str) -> frozenset[str]:
        rows = self._connection.execute(
            "SELECT novelty_fingerprint FROM research_hypothesis_proposals WHERE session_ref = ?", (session_ref,)
        ).fetchall()
        return frozenset(row[0] for row in rows)


def _raise_if_failed(label: str, checks: dict[str, bool]) -> None:
    failed = tuple(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError(f"{label} release check failed: {failed}")


def production_bounded_hypothesis_proposal_release_check() -> dict[str, object]:
    """Release check proving Hotfix #169A end-to-end: a genuinely
    production-shaped exhausted mission (the exact real breakdown reported
    for #168 - 4 cost_slippage_fragility / 2 regime_sensitivity / 2
    robustness_failure / 1 economic_viability_failure) produces only
    canonical, deterministic, budget-bounded, deduplicated
    ``BoundedHypothesisProposal`` records - never a free-text-derived value,
    never a forbidden dimension, never a ``StrategyCandidateRecord``, and
    never any strategy/order/champion/approval mutation - via real
    repository before/after observation, not a by-construction claim.
    """
    import sqlite3
    from dataclasses import replace

    from gaon.knowledge.research_mission import add_candidate, candidate_records, extract_or_update_mission, record_blocked
    from gaon.knowledge.strategy_candidate import ALL_STRATEGY_FAMILY_TEMPLATES, StrategyCandidateStatus, new_candidate
    from gaon.research.research_direction import analyze_mission_failure, plan_research_direction
    from gaon.research.research_priority import propose_research_priority
    from gaon.runtime.llm_conversation import LLMConversationSession
    from gaon.runtime.migrations import migrate
    from gaon.runtime.telegram_agent import TelegramConversationAgent

    now = "2026-08-30T00:00:05Z"
    session_id = "telegram:100"
    default_stagnant_reason = "stagnation: no measurable progress across bounded cycles"

    _observed_tables = (
        "champion_registry", "champion_history", "promotion_requests", "promotion_decisions",
        "approvals", "research_approval_decisions", "research_config_approvals",
        "strategy_deployment_requests", "strategy_deployment_runs",
        "strategy_execution_plans", "strategy_execution_runs",
    )

    def _table_counts(conn: sqlite3.Connection) -> dict[str, int]:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _observed_tables}

    connection = sqlite3.connect(":memory:")
    try:
        from gaon.runtime.config import GaonRuntimeConfig

        migrate(connection)
        config = GaonRuntimeConfig(
            mode="execute", dry_run=False, telegram_enabled=True, telegram_bot_token="t",
            telegram_allowed_chat_ids=("100",), approval_signing_secret="s",
        )
        agent = TelegramConversationAgent(config, connection)
        agent._brain._repository.upsert_session(LLMConversationSession(session_id, "release-check", "telegram", "active", now, now, {}))

        mission = extract_or_update_mission("국내 주식 전체를 대상으로 단타 전략이 3개 나올 때까지 연구해주세요", existing=None, now=now)
        specs = (
            ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
            ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
            ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
            ({"transaction_cost_stress": "fail_underperformed_baseline"}, StrategyCandidateStatus.STAGNANT),
            ({"regime_validation": "fail"}, StrategyCandidateStatus.STAGNANT),
            ({"regime_validation": "fail"}, StrategyCandidateStatus.STAGNANT),
            ({"out_of_sample": "fail"}, StrategyCandidateStatus.STAGNANT),
            ({"out_of_sample": "fail"}, StrategyCandidateStatus.STAGNANT),
            (None, StrategyCandidateStatus.REJECTED),
        )
        for sequence, (family, (stage_status, status)) in enumerate(
            zip((t.family for t in ALL_STRATEGY_FAMILY_TEMPLATES), specs), start=1
        ):
            candidate = new_candidate(family, sequence=sequence, now=now)
            if stage_status is None:
                candidate = replace(
                    candidate, status=status,
                    rejected_reason="economic_viability_failed:non_positive_median_return_and_minority_profitable_symbols",
                )
            else:
                candidate = replace(candidate, status=status, rejected_reason=default_stagnant_reason, validation_stage_status=stage_status)
            mission = add_candidate(mission, candidate, now=now)
        mission = record_blocked(
            mission, reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted", now=now
        )
        candidate_count_before = len(mission.candidates)

        analysis = analyze_mission_failure(mission, session_ref=session_id, now=now)
        priority = propose_research_priority(mission, None)
        direction = plan_research_direction(analysis, priority, has_untried_family=False, has_recoverable_candidate=False, now=now)
        candidate_history = candidate_records(mission)

        counts_before = _table_counts(connection)

        repository = BoundedHypothesisProposalRepository(connection)
        first_proposals = generate_bounded_proposals(direction, analysis, candidate_history, now=now)
        first_created = [repository.put(proposal) for proposal in first_proposals]

        existing_fingerprints = repository.existing_fingerprints_for_session(session_id)
        second_proposals = generate_bounded_proposals(
            direction, analysis, candidate_history, existing_proposal_fingerprints=existing_fingerprints, now=now
        )
        second_created = [repository.put(proposal) for proposal in second_proposals]

        counts_after = _table_counts(connection)
        proposal_row_count = connection.execute("SELECT COUNT(*) FROM research_hypothesis_proposals").fetchone()[0]
        mission_reloaded = agent._brain._mission_for(session_id)  # untouched: never persisted by this check

        # Unsupported failure class must resolve honestly, not fabricate a mapping.
        unsupported_mission = extract_or_update_mission("국내 주식 전체를 대상으로 3개의 단타 전략이 나올 때까지 연구해주세요", existing=None, now=now)
        unsupported_candidate = new_candidate("breakout_standard", sequence=1, now=now)
        unsupported_candidate = replace(unsupported_candidate, status=StrategyCandidateStatus.REJECTED, rejected_reason="some_future_reason_never_classified_here")
        unsupported_mission = add_candidate(unsupported_mission, unsupported_candidate, now=now)
        unsupported_mission = record_blocked(unsupported_mission, reason="strategy_hypothesis_space_exhausted: x", now=now)
        unsupported_analysis = analyze_mission_failure(unsupported_mission, session_ref="telegram:101", now=now)
        unsupported_priority = propose_research_priority(unsupported_mission, None)
        unsupported_direction = plan_research_direction(unsupported_analysis, unsupported_priority, has_untried_family=False, has_recoverable_candidate=False, now=now)
        unsupported_proposals = generate_bounded_proposals(
            unsupported_direction, unsupported_analysis, candidate_records(unsupported_mission), now=now
        )
    finally:
        connection.close()

    import inspect

    import gaon.research.hypothesis_proposal as _this_module

    # Static source check (not sys.modules, contaminated by whatever else
    # ran in this process): the generator's own module CODE (not its
    # explanatory docstring, which names UserStrategyParser only to say it
    # is never used) must never import or call it - the one free-text ->
    # strategy path in this codebase.
    _source = inspect.getsource(_this_module)
    # Built via concatenation, not a literal contiguous string, so this
    # check's own source line is never a false-positive self-match.
    _forbidden_symbol = "UserStrategyParser"
    _no_user_strategy_parser_reference = ("import " + _forbidden_symbol) not in _source and (_forbidden_symbol + "(") not in _source

    all_first_ready = all(p.status == ProposalStatus.READY_FOR_EVIDENCE for p in first_proposals)
    all_second_duplicate = all(p.status == ProposalStatus.DUPLICATE for p in second_proposals)
    forbidden_fields = {mutation.field for p in first_proposals for mutation in p.mutations} & PROHIBITED_DIMENSION_NAMES
    values_from_domain = all(
        mutation.proposed_value in CANONICAL_MUTATION_POLICY[mutation.field].allowed_values
        for p in first_proposals
        for mutation in p.mutations
    )

    checks = {
        "canonical_only": all(mutation.field in CANONICAL_MUTATION_POLICY for p in first_proposals for mutation in p.mutations),
        "no_free_text_generation": _no_user_strategy_parser_reference,
        "mutation_bounded": all(p.mutation_count <= DEFAULT_MUTATION_BUDGET.max_dimensions_changed_per_proposal for p in first_proposals)
        and len(first_proposals) <= DEFAULT_MUTATION_BUDGET.max_proposals_per_direction,
        "deterministic_values": values_from_domain,
        "forbidden_mutation_rejected": len(forbidden_fields) == 0,
        "duplicate_rejected": all_first_ready and all_second_duplicate and not any(second_created),
        "unsupported_failure_honest": len(unsupported_proposals) == 1 and unsupported_proposals[0].status == ProposalStatus.UNSUPPORTED,
        "lineage_preserved": all(
            p.mission_id == mission.mission_id and p.research_direction_id == direction.direction_id and p.source_failure_analysis_id == analysis.analysis_id
            for p in first_proposals
        ),
        "proposal_durable": proposal_row_count == sum(1 for c in first_created if c),
        "candidate_not_created": len(mission.candidates) == candidate_count_before and (mission_reloaded is None or len(mission_reloaded.candidates) == candidate_count_before),
        "strategy_not_mutated": (
            counts_before["strategy_deployment_requests"] == counts_after["strategy_deployment_requests"]
            and counts_before["strategy_deployment_runs"] == counts_after["strategy_deployment_runs"]
            and counts_before["strategy_execution_plans"] == counts_after["strategy_execution_plans"]
            and counts_before["strategy_execution_runs"] == counts_after["strategy_execution_runs"]
        ),
        "order_not_executed": True,  # no tool executor is even constructed in this check - no tool call path exists to place one
        "champion_not_promoted": (
            counts_before["champion_registry"] == counts_after["champion_registry"]
            and counts_before["champion_history"] == counts_after["champion_history"]
            and counts_before["promotion_requests"] == counts_after["promotion_requests"]
            and counts_before["promotion_decisions"] == counts_after["promotion_decisions"]
        ),
        "approval_not_bypassed": (
            counts_before["approvals"] == counts_after["approvals"]
            and counts_before["research_approval_decisions"] == counts_after["research_approval_decisions"]
            and counts_before["research_config_approvals"] == counts_after["research_config_approvals"]
        ),
    }
    _raise_if_failed("production bounded hypothesis proposal", checks)
    return {
        "schema_version": HYPOTHESIS_PROPOSAL_SCHEMA_VERSION,
        "canonical_only": True,
        "free_text_generation": False,
        "mutation_bounded": True,
        "deterministic_values": True,
        "forbidden_mutation_rejected": True,
        "duplicate_rejected": True,
        "unsupported_failure_honest": True,
        "lineage_preserved": True,
        "proposal_durable": True,
        "candidate_created": False,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }
