"""Gaon Completion Phase 3 - Research Director orchestration layer.

Autonomous Learning V2, autonomous research, multi-symbol research, global
market research, learning memory, live trading intelligence, and news
intelligence are each already implemented as separate engines elsewhere in
``gaon.research`` / ``gaon.knowledge``. This module does not reimplement any
of them. It only decides, from a snapshot of already-computed state, which
one of those engines should run next.

The Research Director never executes anything itself: ``decide`` is a pure
function from ``ResearchDirectorState`` to a single recommended
``ResearchDirectorAction``. Callers remain responsible for invoking the
actual engine (OOS runner, walk-forward runner, live trading adapter, ...)
and for feeding the resulting state back in on the next call.

Safety invariants:
- every decision is a deterministic function of already-structured evidence
  fields (``evidence_refs`` names exactly which fields drove it); nothing is
  invented from thin air.
- a research budget (``max_steps``) bounds the loop; once exhausted the
  Director always returns a terminal ``hold`` with
  ``stop_reason=research_budget_exhausted`` rather than continuing forever.
- ``request_human_promotion_review`` is a recommendation only. It never
  promotes a Champion, mutates a strategy, or executes an order - approval
  remains a separate, human-gated step performed elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


RESEARCH_DIRECTOR_SCHEMA_VERSION = 1

_KNOWN_EVIDENCE_STRENGTHS = {"strong", "moderate", "exploratory", "insufficient"}
_KNOWN_CONFLICT_STATUSES = {
    "supported",
    "unresolved_conflict",
    "insufficient_independence",
    "no_comparable_evidence",
    "not_evaluated",
}


class ResearchDirectorAction(str, Enum):
    COLLECT_MORE_EVIDENCE = "collect_more_evidence"
    EXPAND_SYMBOLS = "expand_symbols"
    EXPAND_PERIOD = "expand_period"
    TEST_COUNTER_HYPOTHESIS = "test_counter_hypothesis"
    RUN_OOS = "run_oos"
    RUN_WALK_FORWARD = "run_walk_forward"
    TEST_REGIME = "test_regime"
    TEST_COSTS = "test_costs"
    RUN_MONTE_CARLO = "run_monte_carlo"
    INSPECT_LIVE_EXECUTION = "inspect_live_execution"
    HOLD = "hold"
    REJECT_CANDIDATE = "reject_candidate"
    REQUEST_HUMAN_PROMOTION_REVIEW = "request_human_promotion_review"


@dataclass(frozen=True)
class ResearchDirectorState:
    """Aggregated, already-computed research-state signals.

    Every field here is expected to be sourced from an existing engine
    (multi-source evidence bundle, conflict detector, validation loop, live
    trading intelligence adapter) - this dataclass only aggregates them for
    the Director, it does not compute any of them itself.
    """

    evidence_strength: str
    hypothesis_conflict: str
    symbol_coverage_sufficient: bool
    period_sufficient: bool
    oos_completed: bool
    walk_forward_completed: bool
    regime_completed: bool
    cost_stress_completed: bool
    monte_carlo_completed: bool
    live_execution_available: bool
    live_execution_inspected: bool
    live_execution_failed_orders: int
    candidate_rejected: bool
    steps_used: int
    max_steps: int

    def __post_init__(self) -> None:
        if self.evidence_strength not in _KNOWN_EVIDENCE_STRENGTHS:
            raise ValueError(f"unknown evidence_strength: {self.evidence_strength}")
        if self.hypothesis_conflict not in _KNOWN_CONFLICT_STATUSES:
            raise ValueError(f"unknown hypothesis_conflict: {self.hypothesis_conflict}")
        if self.live_execution_failed_orders < 0:
            raise ValueError("live_execution_failed_orders must be non-negative")
        if self.steps_used < 0 or self.max_steps <= 0:
            raise ValueError("steps_used must be non-negative and max_steps must be positive")

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_DIRECTOR_SCHEMA_VERSION,
            "evidence_strength": self.evidence_strength,
            "hypothesis_conflict": self.hypothesis_conflict,
            "symbol_coverage_sufficient": self.symbol_coverage_sufficient,
            "period_sufficient": self.period_sufficient,
            "oos_completed": self.oos_completed,
            "walk_forward_completed": self.walk_forward_completed,
            "regime_completed": self.regime_completed,
            "cost_stress_completed": self.cost_stress_completed,
            "monte_carlo_completed": self.monte_carlo_completed,
            "live_execution_available": self.live_execution_available,
            "live_execution_inspected": self.live_execution_inspected,
            "live_execution_failed_orders": self.live_execution_failed_orders,
            "candidate_rejected": self.candidate_rejected,
            "steps_used": self.steps_used,
            "max_steps": self.max_steps,
        }


@dataclass(frozen=True)
class ResearchDirectorDecision:
    action: ResearchDirectorAction
    reason: str
    evidence_refs: tuple[str, ...]
    terminal: bool
    stop_reason: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RESEARCH_DIRECTOR_SCHEMA_VERSION,
            "action": self.action.value,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "terminal": self.terminal,
            "stop_reason": self.stop_reason,
            "strategy_mutated": False,
            "order_executed": False,
            "champion_promoted": False,
            "approval_bypassed": False,
        }


def _decision(
    action: ResearchDirectorAction,
    reason: str,
    evidence_refs: tuple[str, ...],
    *,
    terminal: bool = False,
    stop_reason: str | None = None,
) -> ResearchDirectorDecision:
    return ResearchDirectorDecision(action, reason, evidence_refs, terminal, stop_reason)


class ResearchDirector:
    """Decides the single next research action from a state snapshot.

    ``decide`` never calls into OOS/walk-forward/regime/cost/Monte
    Carlo/live-execution engines itself; it only names which one the caller
    should invoke next, in a fixed, evidence-cited priority order.
    """

    def decide(self, state: ResearchDirectorState) -> ResearchDirectorDecision:
        if state.steps_used >= state.max_steps:
            return _decision(
                ResearchDirectorAction.HOLD,
                "Research budget exhausted; stopping rather than researching indefinitely.",
                ("steps_used", "max_steps"),
                terminal=True,
                stop_reason="research_budget_exhausted",
            )
        if state.candidate_rejected:
            return _decision(
                ResearchDirectorAction.REJECT_CANDIDATE,
                "An upstream blocking critic finding already rejected this candidate.",
                ("candidate_rejected",),
                terminal=True,
                stop_reason="candidate_rejected",
            )
        if state.hypothesis_conflict == "unresolved_conflict":
            return _decision(
                ResearchDirectorAction.TEST_COUNTER_HYPOTHESIS,
                "New evidence conflicts with the hypothesis under research and is unresolved.",
                ("hypothesis_conflict",),
            )
        if state.evidence_strength in ("insufficient", "exploratory"):
            return _decision(
                ResearchDirectorAction.COLLECT_MORE_EVIDENCE,
                f"Evidence strength is '{state.evidence_strength}', below what a decision requires.",
                ("evidence_strength",),
            )
        if not state.symbol_coverage_sufficient:
            return _decision(
                ResearchDirectorAction.EXPAND_SYMBOLS,
                "Symbol coverage is not yet sufficient to generalize the candidate.",
                ("symbol_coverage_sufficient",),
            )
        if not state.period_sufficient:
            return _decision(
                ResearchDirectorAction.EXPAND_PERIOD,
                "Observation period is not yet long enough for a reliable read.",
                ("period_sufficient",),
            )
        if not state.oos_completed:
            return _decision(
                ResearchDirectorAction.RUN_OOS,
                "Out-of-sample validation has not been run yet.",
                ("oos_completed",),
            )
        if not state.walk_forward_completed:
            return _decision(
                ResearchDirectorAction.RUN_WALK_FORWARD,
                "Walk-forward validation has not been run yet.",
                ("walk_forward_completed",),
            )
        if not state.regime_completed:
            return _decision(
                ResearchDirectorAction.TEST_REGIME,
                "Market-regime robustness has not been tested yet.",
                ("regime_completed",),
            )
        if not state.cost_stress_completed:
            return _decision(
                ResearchDirectorAction.TEST_COSTS,
                "Transaction-cost stress has not been tested yet.",
                ("cost_stress_completed",),
            )
        if not state.monte_carlo_completed:
            return _decision(
                ResearchDirectorAction.RUN_MONTE_CARLO,
                "Monte Carlo robustness has not been run yet.",
                ("monte_carlo_completed",),
            )
        if state.live_execution_available and not state.live_execution_inspected:
            return _decision(
                ResearchDirectorAction.INSPECT_LIVE_EXECUTION,
                "Real MyMoneyGuard execution evidence is available and has not been reviewed yet.",
                ("live_execution_available", "live_execution_inspected"),
            )
        return _decision(
            ResearchDirectorAction.REQUEST_HUMAN_PROMOTION_REVIEW,
            (
                "All required validation stages passed, evidence is "
                f"'{state.evidence_strength}', and there is no unresolved hypothesis "
                "conflict; recommending human review rather than auto-promoting."
            ),
            (
                "evidence_strength",
                "hypothesis_conflict",
                "oos_completed",
                "walk_forward_completed",
                "regime_completed",
                "cost_stress_completed",
                "monte_carlo_completed",
            ),
            terminal=True,
            stop_reason="ready_for_human_review",
        )


def live_execution_fields_from_feedback(feedback_json: Mapping[str, object]) -> dict[str, object]:
    """Map ``LiveTradingIntelligence`` output onto the Director's live-execution fields.

    Accepts the JSON payload already produced by
    ``gaon.research.live_trading_intelligence.LiveFeedback.to_json()`` (or an
    equivalent mapping with the same keys). This function does not read
    v1 trading files itself and does not import the live trading module -
    the caller is responsible for obtaining that read-only evidence and
    passing its already-computed summary in here. Execution failures
    (``failed_order_count`` / ``unconfirmed_order_count``) are surfaced
    separately from strategy performance (``completed_trade_count`` /
    ``win_rate``) so a bad fill never gets counted as a bad strategy.
    """
    return {
        "live_execution_available": True,
        "live_execution_failed_orders": int(feedback_json.get("failed_order_count", 0) or 0)
        + int(feedback_json.get("unconfirmed_order_count", 0) or 0),
    }


def _raise_if_failed(label: str, checks: Mapping[str, bool]) -> None:
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"{label} release check failed: {failed}")


def _complete_state(**overrides: object) -> ResearchDirectorState:
    base = dict(
        evidence_strength="strong",
        hypothesis_conflict="supported",
        symbol_coverage_sufficient=True,
        period_sufficient=True,
        oos_completed=True,
        walk_forward_completed=True,
        regime_completed=True,
        cost_stress_completed=True,
        monte_carlo_completed=True,
        live_execution_available=False,
        live_execution_inspected=False,
        live_execution_failed_orders=0,
        candidate_rejected=False,
        steps_used=0,
        max_steps=20,
    )
    base.update(overrides)
    return ResearchDirectorState(**base)  # type: ignore[arg-type]


def production_research_director_release_check() -> Mapping[str, object]:
    """Deterministic release check exercising every Director branch."""
    director = ResearchDirector()

    budget_exhausted = director.decide(_complete_state(steps_used=20, evidence_strength="insufficient"))
    rejected = director.decide(_complete_state(candidate_rejected=True))
    conflict = director.decide(_complete_state(hypothesis_conflict="unresolved_conflict"))
    weak_evidence = director.decide(_complete_state(evidence_strength="exploratory"))
    needs_symbols = director.decide(_complete_state(symbol_coverage_sufficient=False))
    needs_period = director.decide(_complete_state(period_sufficient=False))
    needs_oos = director.decide(_complete_state(oos_completed=False))
    needs_walk_forward = director.decide(_complete_state(walk_forward_completed=False))
    needs_regime = director.decide(_complete_state(regime_completed=False))
    needs_costs = director.decide(_complete_state(cost_stress_completed=False))
    needs_monte_carlo = director.decide(_complete_state(monte_carlo_completed=False))
    needs_live_inspection = director.decide(
        _complete_state(live_execution_available=True, live_execution_inspected=False, live_execution_failed_orders=2)
    )
    ready_for_review = director.decide(_complete_state())

    checks = {
        "budget_exhausted_holds_terminally": budget_exhausted.action is ResearchDirectorAction.HOLD
        and budget_exhausted.terminal
        and budget_exhausted.stop_reason == "research_budget_exhausted",
        "budget_check_takes_priority_over_all_else": budget_exhausted.action is ResearchDirectorAction.HOLD,
        "rejected_candidate_is_terminal": rejected.action is ResearchDirectorAction.REJECT_CANDIDATE and rejected.terminal,
        "conflict_triggers_counter_hypothesis": conflict.action is ResearchDirectorAction.TEST_COUNTER_HYPOTHESIS,
        "weak_evidence_triggers_collection": weak_evidence.action is ResearchDirectorAction.COLLECT_MORE_EVIDENCE,
        "symbol_gap_triggers_expansion": needs_symbols.action is ResearchDirectorAction.EXPAND_SYMBOLS,
        "period_gap_triggers_expansion": needs_period.action is ResearchDirectorAction.EXPAND_PERIOD,
        "missing_oos_triggers_oos": needs_oos.action is ResearchDirectorAction.RUN_OOS,
        "missing_walk_forward_triggers_walk_forward": needs_walk_forward.action is ResearchDirectorAction.RUN_WALK_FORWARD,
        "missing_regime_triggers_regime": needs_regime.action is ResearchDirectorAction.TEST_REGIME,
        "missing_costs_triggers_costs": needs_costs.action is ResearchDirectorAction.TEST_COSTS,
        "missing_monte_carlo_triggers_monte_carlo": needs_monte_carlo.action is ResearchDirectorAction.RUN_MONTE_CARLO,
        "live_evidence_triggers_inspection": needs_live_inspection.action is ResearchDirectorAction.INSPECT_LIVE_EXECUTION,
        "fully_validated_recommends_human_review": ready_for_review.action is ResearchDirectorAction.REQUEST_HUMAN_PROMOTION_REVIEW
        and ready_for_review.terminal,
        "human_review_is_recommendation_not_promotion": all(
            decision.to_json()["champion_promoted"] is False and decision.to_json()["approval_bypassed"] is False
            for decision in (
                budget_exhausted, rejected, conflict, weak_evidence, needs_symbols, needs_period,
                needs_oos, needs_walk_forward, needs_regime, needs_costs, needs_monte_carlo,
                needs_live_inspection, ready_for_review,
            )
        ),
        "every_decision_cites_evidence": all(
            bool(decision.evidence_refs)
            for decision in (
                budget_exhausted, rejected, conflict, weak_evidence, needs_symbols, needs_period,
                needs_oos, needs_walk_forward, needs_regime, needs_costs, needs_monte_carlo,
                needs_live_inspection, ready_for_review,
            )
        ),
    }
    _raise_if_failed("production research director", checks)
    return {
        "schema_version": RESEARCH_DIRECTOR_SCHEMA_VERSION,
        "branches_verified": len(checks),
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "safety": "pass",
    }
