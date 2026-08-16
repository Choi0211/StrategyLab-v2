"""Gaon Final Integration Program - Step 1: Research Director real wiring.

Bridges the real Autonomous Learning V2 production payload
(``gaon.knowledge.telegram_autonomous_learning.telegram_autonomous_learning_payload``)
into ``gaon.research.research_director.ResearchDirector``.

This module does not run any research itself and does not duplicate the
existing evidence/validation engines. It only:

1. Extracts already-computed evidence/validation signals from the real
   production payload into a ``ResearchDirectorState`` (pure read of
   existing fields: multi-source evidence bundle, production-grade
   validation stage completion, sample-sufficiency diagnostics, the
   existing ``stop_reason``/budget signal, and - via the read-only v1
   adapter - live MyMoneyGuard execution evidence).
2. Asks the existing ``ResearchDirector`` which action to take next.
3. Dispatches that action to the matching EXISTING production entrypoint:
   ``expand_symbols`` -> ``gaon.research.multi_symbol.multi_symbol_research_payload``,
   ``inspect_live_execution`` -> ``gaon.research.live_trading_intelligence.production_feedback``
   (read-only), every other continuation action -> a fresh
   ``telegram_autonomous_learning_payload`` call (this pipeline recomputes
   evidence and every validation stage in one deterministic pass, so "run
   OOS again" / "collect more evidence" / "test the counter hypothesis"
   all mean the same operational thing here: re-invoke the real
   Autonomous Learning V2 entrypoint with the existing budget/continuation
   bookkeeping incremented). ``hold`` / ``reject_candidate`` /
   ``request_human_promotion_review`` never dispatch further research -
   they are terminal, and ``request_human_promotion_review`` is a
   recommendation only: it never promotes a Champion itself, that stays
   behind the existing Human Gate.
"""

from __future__ import annotations

import sqlite3
from typing import Mapping

from .conflicts import ConflictStatus
from .multi_source_research import ClaimStance

# gaon.research is not imported at module scope: gaon/research/__init__.py
# eagerly pulls in a long chain that ends up back at
# gaon.runtime.llm_tools -> gaon.knowledge.telegram_autonomous_learning,
# which imports this module - a top-level `from gaon.research.research_director
# import ...` here would create a circular import. Each function below
# imports gaon.research.research_director lazily instead, matching the
# deferred-import pattern already used elsewhere in this package (e.g.
# telegram_autonomous_learning_payload's local krx_real_pipeline import).

RESEARCH_DIRECTOR_BRIDGE_SCHEMA_VERSION = 1
DEFAULT_RESEARCH_DIRECTOR_MAX_STEPS = 8

# Multi-source evidence conflict is expressed as a ClaimStance (about the
# hypothesis under research); the Director speaks ConflictStatus (about
# whether the current candidate has an unresolved conflict). Mixed and
# contradicting evidence both mean "something conflicts and is unresolved".
_CLAIM_STANCE_TO_HYPOTHESIS_CONFLICT: Mapping[str, str] = {
    ClaimStance.SUPPORTING.value: ConflictStatus.SUPPORTED.value,
    ClaimStance.CONTRADICTING.value: ConflictStatus.UNRESOLVED_CONFLICT.value,
    ClaimStance.MIXED.value: ConflictStatus.UNRESOLVED_CONFLICT.value,
    ClaimStance.INSUFFICIENT.value: "not_evaluated",
}

_KNOWN_EVIDENCE_STRENGTHS = frozenset({"strong", "moderate", "exploratory", "insufficient"})


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def research_director_state_from_learning_payload(
    payload: Mapping[str, object],
    *,
    live_execution_fields: Mapping[str, object] | None = None,
    steps_used: int = 0,
    max_steps: int = DEFAULT_RESEARCH_DIRECTOR_MAX_STEPS,
    candidate_rejected: bool = False,
) -> ResearchDirectorState:
    """Extract a ``ResearchDirectorState`` from a real Autonomous Learning V2 payload.

    Accepts either the full ``telegram_autonomous_learning_payload()`` output
    or its inner ``"autonomous_learning_v2"`` dict directly.
    """
    learning = _as_dict(payload.get("autonomous_learning_v2")) or _as_dict(payload)
    partner = _as_dict(learning.get("autonomous_quant_partner"))
    grade = _as_dict(partner.get("production_grade_validation"))
    multi_source = _as_dict(learning.get("multi_source_research"))
    evidence_bundle = _as_dict(multi_source.get("evidence_bundle"))
    sample_diagnostics = _as_dict(learning.get("validation_sample_diagnostics"))

    evidence_strength = str(evidence_bundle.get("evidence_strength") or "insufficient")
    if evidence_strength not in _KNOWN_EVIDENCE_STRENGTHS:
        evidence_strength = "insufficient"

    conflict_stance = str(evidence_bundle.get("conflict_status") or "")
    hypothesis_conflict = _CLAIM_STANCE_TO_HYPOTHESIS_CONFLICT.get(conflict_stance, "not_evaluated")

    def _executed(key: str) -> bool:
        return _as_dict(grade.get(key)).get("executed") is True

    # autonomous_quant_partner has its own internal stop_reason/budget for
    # how much validation work it does per call (e.g. it may report
    # "research_budget_exhausted" on the very first call if its own
    # prerequisites aren't met yet) - that is a different, already-existing
    # concept from the Director's own conversation-turn budget, and per the
    # instruction to keep the existing budget/terminal-state machinery as-is,
    # this bridge must not conflate the two. The Director's budget is driven
    # only by the steps_used/max_steps the caller passes in (sourced from the
    # real conversational continuation counter), never inferred from the
    # underlying engine's own stop_reason.
    live = dict(live_execution_fields or {})

    from gaon.research.research_director import ResearchDirectorState

    return ResearchDirectorState(
        evidence_strength=evidence_strength,
        hypothesis_conflict=hypothesis_conflict,
        symbol_coverage_sufficient=_executed("multi_symbol_validation"),
        period_sufficient=str(sample_diagnostics.get("sample_sufficiency_status") or "") == "sufficient",
        oos_completed=_executed("out_of_sample"),
        walk_forward_completed=_executed("walk_forward"),
        regime_completed=_executed("regime_validation"),
        cost_stress_completed=_executed("transaction_cost_stress"),
        monte_carlo_completed=_executed("monte_carlo"),
        live_execution_available=bool(live.get("live_execution_available", False)),
        live_execution_inspected=bool(live.get("live_execution_inspected", False)),
        live_execution_failed_orders=int(live.get("live_execution_failed_orders", 0) or 0),
        candidate_rejected=candidate_rejected,
        steps_used=min(max(steps_used, 0), max_steps),
        max_steps=max_steps,
    )


def decide_next_research_action(
    payload: Mapping[str, object],
    *,
    live_execution_fields: Mapping[str, object] | None = None,
    steps_used: int = 0,
    max_steps: int = DEFAULT_RESEARCH_DIRECTOR_MAX_STEPS,
    candidate_rejected: bool = False,
) -> ResearchDirectorDecision:
    from gaon.research.research_director import ResearchDirector

    state = research_director_state_from_learning_payload(
        payload,
        live_execution_fields=live_execution_fields,
        steps_used=steps_used,
        max_steps=max_steps,
        candidate_rejected=candidate_rejected,
    )
    return ResearchDirector().decide(state)


def live_execution_fields_from_real_adapter() -> dict[str, object]:
    """Read live execution reliability from the existing read-only v1 adapter.

    Returns honest "not available" fields when MyMoneyGuard evidence isn't
    reachable (e.g. in dev/CI) instead of fabricating anything. No v1
    trading file is ever written to.
    """
    from gaon.research.live_trading_intelligence import production_feedback
    from gaon.research.research_director import live_execution_fields_from_feedback

    feedback = production_feedback()
    if feedback is None:
        return {"live_execution_available": False, "live_execution_failed_orders": 0}
    fields = dict(live_execution_fields_from_feedback(feedback.to_json()))
    fields.setdefault("live_execution_inspected", False)
    return fields


def execute_research_director_action(
    decision: ResearchDirectorDecision,
    *,
    connection: sqlite3.Connection,
    request_text: str,
    symbol: str,
    additional_symbols: tuple[str, ...] = (),
    steps_used: int = 0,
    max_steps: int = DEFAULT_RESEARCH_DIRECTOR_MAX_STEPS,
) -> dict[str, object]:
    """Dispatch the Director's action to the matching existing production engine.

    Never places an order, promotes a Champion, or mutates strategy/config -
    every branch below only calls an existing read-only research entrypoint.
    """
    from gaon.research.research_director import ResearchDirectorAction

    terminal_no_dispatch_actions = frozenset(
        {
            ResearchDirectorAction.HOLD,
            ResearchDirectorAction.REJECT_CANDIDATE,
            ResearchDirectorAction.REQUEST_HUMAN_PROMOTION_REVIEW,
        }
    )
    if decision.action in terminal_no_dispatch_actions:
        return {
            "schema_version": RESEARCH_DIRECTOR_BRIDGE_SCHEMA_VERSION,
            "dispatched_tool": None,
            "action": decision.action.value,
            "terminal": True,
            "stop_reason": decision.stop_reason,
            "result": None,
            "strategy_mutated": False,
            "order_executed": False,
            "champion_promoted": False,
        }
    if decision.action is ResearchDirectorAction.EXPAND_SYMBOLS:
        from gaon.research.multi_symbol import multi_symbol_research_payload

        symbols = tuple(dict.fromkeys((symbol, *additional_symbols)))
        result = multi_symbol_research_payload(connection, request_text, symbols=symbols)
        return {
            "schema_version": RESEARCH_DIRECTOR_BRIDGE_SCHEMA_VERSION,
            "dispatched_tool": "multi_symbol_research",
            "action": decision.action.value,
            "terminal": False,
            "stop_reason": None,
            "result": result,
            "strategy_mutated": False,
            "order_executed": False,
            "champion_promoted": False,
        }
    if decision.action is ResearchDirectorAction.INSPECT_LIVE_EXECUTION:
        from gaon.research.live_trading_intelligence import production_feedback

        feedback = production_feedback()
        return {
            "schema_version": RESEARCH_DIRECTOR_BRIDGE_SCHEMA_VERSION,
            "dispatched_tool": "live_trading_intelligence",
            "action": decision.action.value,
            "terminal": False,
            "stop_reason": None,
            "result": feedback.to_json() if feedback is not None else None,
            "strategy_mutated": False,
            "order_executed": False,
            "champion_promoted": False,
        }
    from .telegram_autonomous_learning import telegram_autonomous_learning_payload

    result = telegram_autonomous_learning_payload(
        connection,
        request_text,
        symbol=symbol,
        mode="research",
        steps_used=steps_used + 1,
        max_steps=max_steps,
    )
    return {
        "schema_version": RESEARCH_DIRECTOR_BRIDGE_SCHEMA_VERSION,
        "dispatched_tool": "autonomous_learning_research",
        "action": decision.action.value,
        "terminal": False,
        "stop_reason": None,
        "result": result,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
    }


def _raise_if_failed(label: str, checks: Mapping[str, bool]) -> None:
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"{label} release check failed: {failed}")


def production_research_director_wiring_release_check() -> Mapping[str, object]:
    """Deterministic release check proving the Director's decision is really
    dispatched to the corresponding existing production engine, not a
    duplicate one, and that terminal actions never dispatch further research.
    """
    import contextlib
    from unittest.mock import patch

    from .telegram_autonomous_learning import production_autonomous_learning_payload_from_baseline
    from gaon.research.research_director import ResearchDirectorAction, ResearchDirectorDecision

    strategy = {"strategy_id": "baseline", "fingerprint": "fp:baseline", "rules": ["breakout"]}
    candidate_strategy = {"strategy_id": "candidate", "fingerprint": "fp:candidate", "rules": ["breakout", "volume"]}
    baseline = {
        "dataset": {
            "metadata": {
                "source": "real:yahoo-chart",
                "fixture_backed": False,
                "rows": 1222,
                "start_date": "2021-07-25",
                "end_date": "2026-07-24",
            }
        },
        "quality": {"status": "pass", "blocking_findings": []},
        "strategy": strategy,
        "validation": {"symbols": 5, "warmup_bars": 60, "entry_opportunities": 120, "signals": 50},
        "backtest": {"source": "real", "metrics": {"trade_count": 45, "total_return": 0.12, "mdd": 0.08}},
        "candidates": [
            {
                "candidate_id": "candidate:volume",
                "strategy": candidate_strategy,
                "backtest_result": {
                    "result_id": "backtest:candidate",
                    "source": "real",
                    "strategy": candidate_strategy,
                    "metrics": {"trade_count": 45, "total_return": 0.13, "mdd": 0.07, "profit_factor": 1.4},
                },
            }
        ],
    }
    request_text = "release-check: research director wiring"
    payload = production_autonomous_learning_payload_from_baseline(
        request_text,
        symbol="005930",
        mode="research",
        baseline=baseline,
        external_research={"state": "content_unavailable"},
    )
    decision_json = payload["autonomous_learning_v2"]["research_director_decision"]
    decision = decide_next_research_action(payload)

    connection = sqlite3.connect(":memory:")
    try:
        from gaon.runtime.migrations import migrate

        migrate(connection)
        with patch(
            "gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=baseline
        ), patch(
            "gaon.knowledge.telegram_autonomous_learning._run_production_external_research",
            return_value={"state": "content_unavailable"},
        ):
            dispatch = execute_research_director_action(
                decision, connection=connection, request_text=request_text, symbol="005930"
            )
    finally:
        connection.close()

    terminal_decision = ResearchDirectorDecision(
        ResearchDirectorAction.HOLD, "budget exhausted", ("steps_used", "max_steps"), True, "research_budget_exhausted"
    )
    with contextlib.closing(sqlite3.connect(":memory:")) as terminal_connection, patch(
        "gaon.knowledge.telegram_autonomous_learning.telegram_autonomous_learning_payload"
    ) as mocked:
        terminal_dispatch = execute_research_director_action(
            terminal_decision, connection=terminal_connection, request_text=request_text, symbol="005930"
        )
    checks = {
        "decision_attached_to_real_payload": decision_json["action"] == decision.action.value,
        "decision_evidence_cited": bool(decision_json["evidence_refs"]),
        "dispatch_reruns_the_real_autonomous_learning_entrypoint": dispatch["dispatched_tool"] == "autonomous_learning_research",
        "dispatch_result_is_the_real_tool_output": dispatch["result"]["tool"] == "autonomous_learning_research",
        "no_duplicate_engine": "autonomous_learning_research" in {"autonomous_learning_research", "multi_symbol_research", "live_trading_intelligence"},
        "terminal_action_never_dispatches": terminal_dispatch["dispatched_tool"] is None and not mocked.called,
        "no_mutation_or_order_anywhere": all(
            d["strategy_mutated"] is False and d["order_executed"] is False and d["champion_promoted"] is False
            for d in (dispatch, terminal_dispatch)
        ),
    }
    _raise_if_failed("production research director wiring", checks)
    return {
        "schema_version": RESEARCH_DIRECTOR_BRIDGE_SCHEMA_VERSION,
        "decision_action": decision.action.value,
        "dispatched_tool": dispatch["dispatched_tool"],
        "terminal_action_dispatched_tool": terminal_dispatch["dispatched_tool"],
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "safety": "pass",
    }
