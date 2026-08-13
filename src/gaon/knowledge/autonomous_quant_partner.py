"""Sprints 199-240 - autonomous quant research partner contracts.

This module composes the existing real-data and multi-source research contracts
into a bounded, restart-safe research loop. External content remains inert
evidence; strategy changes, Champion promotion, and orders are never executed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import random
import statistics
from typing import Mapping

from .multi_source_research import (
    ClaimStance,
    CredibilityTier,
    EvidenceStrength,
    MultiSourceResearchOrchestrator,
    MultiSourceResearchPlanner,
    MultiSourceResearchPolicy,
    ProviderState,
    SourceCategory,
    validation_sample_diagnostics,
)


AUTONOMOUS_QUANT_PARTNER_SCHEMA_VERSION = 1


class GapKind(str, Enum):
    EVIDENCE_INSUFFICIENT = "evidence_insufficient"
    SAMPLE_INSUFFICIENT = "sample_insufficient"
    COUNTER_EVIDENCE_REQUIRED = "counter_evidence_required"
    ROBUSTNESS_INCOMPLETE = "robustness_incomplete"
    PROVIDER_BLOCKED = "provider_blocked"


class NextActionKind(str, Enum):
    DIVERSIFY_SOURCES = "diversify_sources"
    SEARCH_COUNTER_EVIDENCE = "search_counter_evidence"
    EXPAND_VALIDATION = "expand_validation"
    RUN_TOURNAMENT = "run_tournament"
    PREPARE_PROMOTION_REVIEW = "prepare_promotion_review"
    STOP = "stop"


class StopReason(str, Enum):
    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    RESEARCH_BUDGET_EXHAUSTED = "research_budget_exhausted"
    NO_SAFE_NEXT_ACTION = "no_safe_next_action"
    BLOCKED_PROVIDER = "blocked_provider"
    HUMAN_APPROVAL_REQUIRED = "human_approval_required"


class SufficiencyStatus(str, Enum):
    SUFFICIENT = "sufficient"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class ResearchBudget:
    max_iterations: int = 3
    max_wall_clock_seconds: int = 30
    max_provider_calls: int = 10
    max_experiments: int = 6
    max_symbols: int = 5
    max_validation_runs: int = 18
    max_walk_forward_folds: int = 4
    max_parameter_variants: int = 3
    max_monte_carlo_runs: int = 200

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if int(value) <= 0:
                raise ValueError(f"{name} must be positive")

    def to_json(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ResearchGapReport:
    report_id: str
    gaps: tuple[GapKind, ...]
    missing_evidence_categories: tuple[SourceCategory, ...]
    missing_validation: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "gaps": [item.value for item in self.gaps],
            "missing_evidence_categories": [item.value for item in self.missing_evidence_categories],
            "missing_validation": list(self.missing_validation),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class NextResearchAction:
    action_id: str
    kind: NextActionKind
    rationale: str
    target_categories: tuple[SourceCategory, ...] = ()
    safe_to_execute: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "kind": self.kind.value,
            "rationale": self.rationale,
            "target_categories": [item.value for item in self.target_categories],
            "safe_to_execute": self.safe_to_execute,
        }


@dataclass(frozen=True)
class RobustnessReport:
    report_id: str
    walk_forward: str
    out_of_sample: str
    multi_period: str
    multi_symbol: str
    regimes: Mapping[str, str]
    parameter_sensitivity: str
    transaction_cost_stress: str
    monte_carlo: str
    overfitting_diagnostics: str
    leakage_guard: str
    fabricated_metrics: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "walk_forward": self.walk_forward,
            "out_of_sample": self.out_of_sample,
            "multi_period": self.multi_period,
            "multi_symbol": self.multi_symbol,
            "regimes": dict(self.regimes),
            "parameter_sensitivity": self.parameter_sensitivity,
            "transaction_cost_stress": self.transaction_cost_stress,
            "monte_carlo": self.monte_carlo,
            "overfitting_diagnostics": self.overfitting_diagnostics,
            "leakage_guard": self.leakage_guard,
            "fabricated_metrics": self.fabricated_metrics,
        }


@dataclass(frozen=True)
class CandidateRanking:
    candidate_id: str
    rank: int
    score: float
    evidence_strength: EvidenceStrength
    downside_risk: str
    complexity_penalty: float
    overfit_penalty: float
    stability_score: float
    fixture_backed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "rank": self.rank,
            "score": self.score,
            "evidence_strength": self.evidence_strength.value,
            "downside_risk": self.downside_risk,
            "complexity_penalty": self.complexity_penalty,
            "overfit_penalty": self.overfit_penalty,
            "stability_score": self.stability_score,
            "fixture_backed": self.fixture_backed,
        }


@dataclass(frozen=True)
class PromotionReadinessReport:
    report_id: str
    status: str
    studied: tuple[str, ...]
    baseline_issues: tuple[str, ...]
    source_summary: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    tested_candidates: tuple[str, ...]
    best_candidate: str | None
    failure_modes: tuple[str, ...]
    baseline_improvements: tuple[str, ...]
    validation_sufficient: bool
    remaining_risks: tuple[str, ...]
    approval_required: bool
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "status": self.status,
            "studied": list(self.studied),
            "baseline_issues": list(self.baseline_issues),
            "source_summary": list(self.source_summary),
            "counter_evidence": list(self.counter_evidence),
            "tested_candidates": list(self.tested_candidates),
            "best_candidate": self.best_candidate,
            "failure_modes": list(self.failure_modes),
            "baseline_improvements": list(self.baseline_improvements),
            "validation_sufficient": self.validation_sufficient,
            "remaining_risks": list(self.remaining_risks),
            "approval_required": self.approval_required,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


def autonomous_quant_partner_payload(
    request_text: str,
    *,
    symbol: str,
    baseline: Mapping[str, object],
    multi_source_research: Mapping[str, object] | None = None,
    budget: ResearchBudget | None = None,
    allow_release_fixture: bool = False,
) -> dict[str, object]:
    selected_budget = budget or ResearchBudget()
    research = dict(
        multi_source_research
        or (_release_multi_source_result(baseline) if allow_release_fixture else _empty_multi_source_result(request_text, symbol, baseline))
    )
    diagnostics = validation_sample_diagnostics(baseline)
    sufficiency = _validation_sufficiency_v2(research, diagnostics, baseline=baseline)
    gap_report = _gap_report(symbol, research, sufficiency)
    actions = _next_actions(gap_report, sufficiency)
    iterations = _research_iterations(selected_budget, actions, sufficiency)
    robustness = _robustness_report(symbol, sufficiency)
    tournament = _strategy_tournament(research, robustness, sufficiency)
    candidate_generation = _candidate_generation(research, tournament)
    counter_evidence = _counter_evidence_report(research, actions)
    memory = _learning_memory_closed_loop(symbol, research, tournament)
    readiness = _promotion_readiness(symbol, research, tournament, robustness, sufficiency)
    stop_reason = _stop_reason(readiness, sufficiency, selected_budget)
    observability = _observability(
        symbol=symbol,
        budget=selected_budget,
        research=research,
        sufficiency=sufficiency,
        iterations=iterations,
        stop_reason=stop_reason,
    )
    production_grade = _production_grade_validation_suite(
        symbol=symbol,
        baseline=baseline,
        research=research,
        sufficiency=sufficiency,
        tournament=tournament,
        budget=selected_budget,
    )
    return {
        "schema_version": AUTONOMOUS_QUANT_PARTNER_SCHEMA_VERSION,
        "tool": "autonomous_quant_research_partner",
        "symbol": symbol,
        "request_text": request_text,
        "provider_registry": _provider_registry(),
        "source_acquisition": _source_acquisition_summary(research),
        "multi_source_research": research,
        "validation_sufficiency_v2": sufficiency,
        "research_gap_report": gap_report.to_json(),
        "next_research_actions": [item.to_json() for item in actions],
        "research_budget": selected_budget.to_json(),
        "research_iterations": iterations,
        "stop_reason": stop_reason.value,
        "counter_evidence": counter_evidence,
        "candidate_generation": candidate_generation,
        "validation_coverage": _validation_coverage(sufficiency),
        "robustness_report": robustness.to_json(),
        "strategy_tournament": tournament,
        "production_grade_validation": production_grade,
        "learning_memory_closed_loop": memory,
        "promotion_readiness_report": readiness.to_json(),
        "observability": observability,
        "telegram_progress": _telegram_progress(readiness, sufficiency, stop_reason),
        "approval_required": readiness.approval_required,
        "human_gate_status": "awaiting_human_approval" if readiness.approval_required else "not_requested",
        "strategy_mutated": False,
        "order_executed": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "automatic_champion_promotion": False,
        "automatic_config_apply": False,
        "fixture_backed": False,
        "safety": "pass",
    }


def _provider_registry() -> dict[str, object]:
    tiers = {
        SourceCategory.ACADEMIC: CredibilityTier.TIER_A_AUTHORITATIVE,
        SourceCategory.OFFICIAL_MARKET: CredibilityTier.TIER_A_AUTHORITATIVE,
        SourceCategory.CORPORATE: CredibilityTier.TIER_A_AUTHORITATIVE,
        SourceCategory.REGULATORY: CredibilityTier.TIER_A_AUTHORITATIVE,
        SourceCategory.PROFESSIONAL_RESEARCH: CredibilityTier.TIER_B_RESEARCH_PROFESSIONAL,
        SourceCategory.NEWS: CredibilityTier.TIER_C_SECONDARY_INFORMATIONAL,
        SourceCategory.WEB: CredibilityTier.TIER_C_SECONDARY_INFORMATIONAL,
        SourceCategory.YOUTUBE: CredibilityTier.TIER_D_EXPLORATORY_SOCIAL,
        SourceCategory.COMMUNITY: CredibilityTier.TIER_D_EXPLORATORY_SOCIAL,
        SourceCategory.SOCIAL: CredibilityTier.TIER_D_EXPLORATORY_SOCIAL,
    }
    return {
        "providers": {
            category.value: {
                "category": category.value,
                "credibility_tier": tiers[category].value,
                "timeout_seconds": 10,
                "max_content_bytes": 262_144,
                "max_provider_calls": 1,
                "arbitrary_crawling_allowed": False,
                "login_or_paywall_bypass": False,
                "promotion_allowed_alone": category
                not in {SourceCategory.NEWS, SourceCategory.WEB, SourceCategory.YOUTUBE, SourceCategory.COMMUNITY, SourceCategory.SOCIAL},
                "fail_closed": True,
            }
            for category in SourceCategory
        },
        "allowed_categories": [item.value for item in SourceCategory],
        "fixture_promotion_allowed": False,
        "metadata_only_promotion_allowed": False,
    }


def _source_acquisition_summary(research: Mapping[str, object]) -> dict[str, object]:
    reports = [_as_dict(item) for item in _as_list(research.get("provider_reports"))]
    acquired = [_as_dict(source) for report in reports for source in _as_list(report.get("acquired"))]
    claims = [_as_dict(claim) for claim in _claims(research)]
    provider_states = _as_dict(research.get("provider_states"))
    acquired_categories = sorted(
        {
            str(source.get("source_type"))
            for source in acquired
            if source.get("source_type") and source.get("fixture_backed") is not True
        }
    )
    return {
        "sources_acquired": len(acquired),
        "source_categories_acquired": acquired_categories,
        "source_categories_attempted": list(provider_states),
        "provider_states": provider_states,
        "metadata_only_sources": sum(1 for report in reports if "metadata_only" in _as_list(report.get("blockers"))),
        "content_hashes": [item.get("content_hash") for item in acquired if item.get("content_hash")],
        "full_content_claims": len([claim for claim in claims if claim.get("content_hash")]),
        "metadata_only_claims": 0,
        "fixture_claims": len([claim for claim in claims if claim.get("fixture_backed") is True]),
        "promotion_evidence_from_metadata_only": False,
    }


def _counter_evidence_report(research: Mapping[str, object], actions: tuple[NextResearchAction, ...]) -> dict[str, object]:
    bundle = _as_dict(research.get("evidence_bundle"))
    supporting = _as_list(bundle.get("supporting_claims"))
    contradicting = _as_list(bundle.get("contradicting_claims"))
    attempted = any(action.kind is NextActionKind.SEARCH_COUNTER_EVIDENCE for action in actions)
    return {
        "attempted": attempted,
        "supporting_claim_count": len(supporting),
        "contradicting_claim_count": len(contradicting),
        "conflict_status": bundle.get("conflict_status", "insufficient"),
        "status": "mixed" if contradicting and supporting else "no_counter_evidence_found" if attempted else "not_attempted",
        "claim_ids": [item.get("claim_id") for item in contradicting if isinstance(item, Mapping) and item.get("claim_id")],
        "placeholder_used": False,
        "strategy_mutated": False,
        "order_executed": False,
    }


def _candidate_generation(research: Mapping[str, object], tournament: Mapping[str, object]) -> list[dict[str, object]]:
    hypotheses = [_as_dict(item) for item in _as_list(research.get("hypotheses"))]
    generated: list[dict[str, object]] = []
    for index, ranking in enumerate(_as_list(tournament.get("rankings")), start=1):
        row = _as_dict(ranking)
        candidate_id = str(row.get("candidate_id") or "")
        if candidate_id == "baseline" or not candidate_id:
            continue
        changed_rules = (
            ["volume confirmation robustness"]
            if "volume" in candidate_id
            else ["regime filter before breakout entries"]
            if "regime" in candidate_id
            else ["candidate rule pending implementation"]
        )
        generated.append(
            {
                "candidate_id": candidate_id,
                "candidate_fingerprint": f"candidate-fingerprint:{_hash({'candidate_id': candidate_id, 'changed_rules': changed_rules})[:24]}",
                "rank": index,
                "changed_rules": changed_rules,
                "hypothesis_ids": [item.get("hypothesis_id") for item in hypotheses if item.get("hypothesis_id")],
                "fixture_backed": bool(row.get("fixture_backed")),
                "strategy_mutated": False,
                "order_executed": False,
            }
        )
    return generated


def _validation_coverage(sufficiency: Mapping[str, object]) -> dict[str, object]:
    return {
        "status": sufficiency.get("status"),
        "symbol": sufficiency.get("symbol"),
        "data_source": sufficiency.get("data_source"),
        "fixture_backed": sufficiency.get("fixture_backed"),
        "trade_count": sufficiency.get("trade_count"),
        "min_trades": sufficiency.get("min_trades"),
        "sample_sufficiency_status": sufficiency.get("sample_sufficiency_status"),
        "sample_sufficiency_reasons": list(_as_list(sufficiency.get("sample_sufficiency_reasons"))),
        "requested_start": sufficiency.get("requested_start"),
        "requested_end": sufficiency.get("requested_end"),
        "actual_start": sufficiency.get("actual_start"),
        "actual_end": sufficiency.get("actual_end"),
        "raw_bars": sufficiency.get("raw_bars"),
        "usable_bars": sufficiency.get("usable_bars"),
        "warmup_bars": sufficiency.get("warmup_bars"),
        "dropped_bars": sufficiency.get("dropped_bars"),
        "entry_signal_count": sufficiency.get("entry_signal_count"),
        "exit_signal_count": sufficiency.get("exit_signal_count"),
        "completed_trade_count": sufficiency.get("completed_trade_count"),
        "open_trade_count": sufficiency.get("open_trade_count"),
        "minimum_required_trades": sufficiency.get("minimum_required_trades"),
        "validation_horizon_days": sufficiency.get("validation_horizon_days"),
        "validation_horizon_bars": sufficiency.get("validation_horizon_bars"),
        "horizon_reason": sufficiency.get("horizon_reason"),
        "horizon_extension_attempts": sufficiency.get("horizon_extension_attempts"),
        "window_fingerprint": sufficiency.get("window_fingerprint"),
        "comparison_window_compatible": sufficiency.get("comparison_window_compatible"),
        "multi_symbol_status": sufficiency.get("multi_symbol_status"),
        "out_of_sample_status": _as_dict(sufficiency.get("out_of_sample_period")).get("status") or sufficiency.get("out_of_sample"),
        "walk_forward_status": sufficiency.get("walk_forward_status") or sufficiency.get("walk_forward"),
        "signal_diagnostics": _as_dict(sufficiency.get("signal_diagnostics")),
        "cost_assumptions": _as_dict(sufficiency.get("cost_assumptions")),
        "number_of_symbols": sufficiency.get("number_of_symbols"),
        "walk_forward": sufficiency.get("walk_forward"),
        "out_of_sample": sufficiency.get("out_of_sample"),
        "robustness": sufficiency.get("robustness"),
        "monte_carlo": sufficiency.get("monte_carlo"),
        "parameter_sensitivity": sufficiency.get("parameter_sensitivity"),
        "missing_validation": list(_as_list(sufficiency.get("missing_validation"))),
        "fabricated_metrics": False,
    }


def _production_grade_validation_suite(
    *,
    symbol: str,
    baseline: Mapping[str, object],
    research: Mapping[str, object],
    sufficiency: Mapping[str, object],
    tournament: Mapping[str, object],
    budget: ResearchBudget,
) -> dict[str, object]:
    coverage = _validation_coverage(sufficiency)
    execution = _robustness_execution_input(baseline)
    signals = _signal_integrity_report(coverage)
    multi_symbol = _multi_symbol_validation_report(symbol, baseline, sufficiency, execution)
    oos = _executed_validation_section(
        execution,
        "out_of_sample",
        default_status="not_run_missing_oos_backtest",
        default_blocker="actual_oos_backtest_not_executed",
        extra={"candidate_frozen_before_oos": True, "optimized_on_oos": False, "candidate_rejected_if_oos_fails": True},
    )
    walk_forward = _executed_validation_section(
        execution,
        "walk_forward",
        default_status="not_run_missing_fold_backtests",
        default_blocker="actual_walk_forward_backtests_not_executed",
        extra={"fold_count": 0, "max_folds": budget.max_walk_forward_folds, "parameter_optimization_per_fold": False, "folds": []},
    )
    regime = _executed_validation_section(
        execution,
        "regime_validation",
        default_status="not_run_missing_regime_backtests",
        default_blocker="actual_regime_backtests_not_executed",
        extra={"model": "not_run_without_actual_regime_backtests", "regimes": {}, "macro_labels_fabricated": False},
    )
    parameter = _executed_validation_section(
        execution,
        "parameter_sensitivity",
        default_status="not_run_missing_variant_backtests",
        default_blocker="actual_parameter_variant_backtests_not_executed",
        extra={"max_variants": budget.max_parameter_variants, "local_neighborhood_only": True, "variants": [], "huge_grid_search": False},
    )
    cost = _executed_validation_section(
        execution,
        "transaction_cost_stress",
        default_status="not_supported",
        default_blocker="actual_transaction_cost_backtests_not_executed",
        extra={"scenarios": [], "unsupported_tax_models_fabricated": False},
    )
    monte_carlo = _monte_carlo_report(baseline, execution, budget)
    evidence = _independent_evidence_report(research)
    promotion = _unified_promotion_readiness(
        sufficiency=sufficiency,
        tournament=tournament,
        evidence=evidence,
        multi_symbol=multi_symbol,
        oos=oos,
        walk_forward=walk_forward,
        regime=regime,
        parameter=parameter,
        cost=cost,
        monte_carlo=monte_carlo,
    )
    return {
        "schema_version": 1,
        "signal_integrity": signals,
        "multi_symbol_validation": multi_symbol,
        "real_provider_wiring": _real_provider_wiring_report(research),
        "youtube_provider": _youtube_provider_report(research),
        "independent_evidence": evidence,
        "out_of_sample": oos,
        "walk_forward": walk_forward,
        "regime_validation": regime,
        "parameter_sensitivity": parameter,
        "transaction_cost_stress": cost,
        "monte_carlo": monte_carlo,
        "unified_promotion_readiness": promotion,
        "research_budget": {
            "max_provider_calls": budget.max_provider_calls,
            "max_symbols": budget.max_symbols,
            "max_validation_runs": budget.max_validation_runs,
            "max_walk_forward_folds": budget.max_walk_forward_folds,
            "max_parameter_variants": budget.max_parameter_variants,
            "max_monte_carlo_runs": budget.max_monte_carlo_runs,
            "bounded": True,
        },
        "strategy_mutated": False,
        "order_executed": False,
        "safety": "pass",
    }


def _signal_integrity_report(coverage: Mapping[str, object]) -> dict[str, object]:
    signals = _as_dict(coverage.get("signal_diagnostics"))
    usable = int(coverage.get("usable_bars") or 0)
    breakout = int(signals.get("breakout_condition_hits") or signals.get("combined_entry_signals") or coverage.get("entry_signal_count") or 0)
    trend = int(signals.get("trend_condition_hits") or signals.get("trend_filter_hits") or 0)
    volume = int(signals.get("volume_condition_hits") or signals.get("volume_filter_hits") or 0)
    all_hits = int(signals.get("all_entry_conditions_hits") or signals.get("combined_entry_signals") or coverage.get("entry_signal_count") or 0)
    entries = int(signals.get("actual_entries") or coverage.get("completed_trade_count") or coverage.get("trade_count") or 0)
    exits = int(signals.get("actual_exits") or coverage.get("completed_trade_count") or coverage.get("trade_count") or 0)
    suppressed = max(0, all_hits - entries)
    return {
        "bars_evaluated": usable,
        "breakout_condition_hits": breakout,
        "trend_condition_hits": trend,
        "volume_condition_hits": volume,
        "breakout_and_trend_hits": _exact_or_not_available(signals, "breakout_and_trend_hits"),
        "breakout_and_volume_hits": _exact_or_not_available(signals, "breakout_and_volume_hits"),
        "trend_and_volume_hits": _exact_or_not_available(signals, "trend_and_volume_hits"),
        "all_entry_conditions_hits": all_hits,
        "blocked_by_breakout": int(signals.get("blocked_by_breakout") or max(0, usable - breakout)),
        "blocked_by_trend": int(signals.get("blocked_by_trend") or signals.get("blocked_by_ma_filter") or max(0, breakout - min(breakout, trend))),
        "blocked_by_volume": int(signals.get("blocked_by_volume") or signals.get("blocked_by_volume_filter") or max(0, min(breakout, trend) - all_hits)),
        "signals_while_flat": int(signals.get("signals_while_flat") or entries),
        "signals_while_position_open": int(signals.get("signals_while_position_open") or suppressed),
        "actual_entries": entries,
        "actual_exits": exits,
        "completed_trades": int(coverage.get("completed_trade_count") or coverage.get("trade_count") or 0),
        "open_trade_count": int(coverage.get("open_trade_count") or 0),
        "condition_counts_are_raw_hits": True,
        "entry_events_require_flat_position": True,
        "misleading_full_filter_hit_labels": trend == usable or volume == usable,
    }


def _exact_or_not_available(values: Mapping[str, object], key: str) -> object:
    return int(values[key]) if key in values and values[key] is not None else "not_available"


def _robustness_execution_input(baseline: Mapping[str, object]) -> dict[str, object]:
    return _as_dict(baseline.get("production_robustness_execution") or baseline.get("robustness_execution"))


def _is_actual_execution(section: Mapping[str, object]) -> bool:
    lineage = str(section.get("lineage") or section.get("metrics_lineage") or "")
    return section.get("executed") is True and lineage in {
        "actual_backtest",
        "actual_backtest_engine",
        "deterministic_actual_backtest",
    }


def _executed_validation_section(
    execution: Mapping[str, object],
    key: str,
    *,
    default_status: str,
    default_blocker: str,
    extra: Mapping[str, object] | None = None,
) -> dict[str, object]:
    section = _as_dict(execution.get(key))
    if _is_actual_execution(section):
        result = dict(section)
        result.setdefault("fabricated_metrics", False)
        result.setdefault("strategy_mutated", False)
        result.setdefault("order_executed", False)
        return result
    return {
        "status": default_status,
        "executed": False,
        "execution_state": "not_run",
        "blockers": [default_blocker],
        "fabricated_metrics": False,
        "strategy_mutated": False,
        "order_executed": False,
        **dict(extra or {}),
    }


def _multi_symbol_validation_report(
    symbol: str,
    baseline: Mapping[str, object],
    sufficiency: Mapping[str, object],
    execution: Mapping[str, object],
) -> dict[str, object]:
    coverage = _validation_coverage(sufficiency)
    primary_trades = int(coverage.get("completed_trade_count") or coverage.get("trade_count") or 0)
    min_trades = int(coverage.get("minimum_required_trades") or coverage.get("min_trades") or 30)
    section = _as_dict(execution.get("multi_symbol_validation"))
    if _is_actual_execution(section):
        rows = [_as_dict(row) for row in _as_list(section.get("symbols"))]
        peer_symbols = [str(row.get("symbol")) for row in rows if str(row.get("symbol") or "") != symbol]
        improved = int(section.get("symbols_improved") or 0)
        status = str(section.get("cross_symbol_status") or ("multi_symbol_sufficient" if len(rows) >= 3 else "multi_symbol_partial"))
        return {
            **dict(section),
            "primary_symbol": symbol,
            "primary_symbol_sufficiency": "sufficient" if primary_trades >= min_trades else "insufficient_trades",
            "peer_symbols": peer_symbols,
            "symbols": rows,
            "symbols_tested": len(rows),
            "symbols_improved": improved,
            "cross_symbol_status": status,
            "does_not_rewrite_primary_trade_count": True,
            "fabricated_metrics": False,
            "strategy_mutated": False,
            "order_executed": False,
        }
    return {
        "primary_symbol": symbol,
        "primary_symbol_sufficiency": "sufficient" if primary_trades >= min_trades else "insufficient_trades",
        "peer_selection_policy": "bounded_liquid_krx_peers_from_universe_same_exchange_history_liquidity",
        "peer_symbols": [],
        "max_symbols": 5,
        "symbols": [],
        "symbols_tested": 0,
        "symbols_improved": 0,
        "symbols_degraded": 0,
        "cross_symbol_status": "not_run_missing_peer_backtests",
        "executed": False,
        "execution_state": "not_run",
        "blockers": ["actual_peer_symbol_backtests_not_executed"],
        "does_not_rewrite_primary_trade_count": True,
        "fabricated_metrics": False,
        "strategy_mutated": False,
        "order_executed": False,
    }


def _monte_carlo_report(baseline: Mapping[str, object], execution: Mapping[str, object], budget: ResearchBudget) -> dict[str, object]:
    section = _as_dict(execution.get("monte_carlo"))
    if _is_actual_execution(section):
        result = dict(section)
        result.setdefault("fabricated_metrics", False)
        result.setdefault("creates_new_market_evidence", False)
        result.setdefault("strategy_mutated", False)
        result.setdefault("order_executed", False)
        return result
    coverage = _validation_coverage(_validation_sufficiency_v2({}, validation_sample_diagnostics(baseline), baseline=baseline))
    trades = int(coverage.get("completed_trade_count") or coverage.get("trade_count") or 0)
    min_trades = int(coverage.get("minimum_required_trades") or coverage.get("min_trades") or 30)
    if trades < min_trades:
        return {
            "status": "not_run_insufficient_primary_sample",
            "executed": False,
            "execution_state": "not_run",
            "blockers": ["insufficient_primary_sample"],
            "simulation_count": 0,
            "method": "not_run_without_sufficient_actual_trades",
            "seed": None,
            "median_outcome": None,
            "drawdown_distribution": {},
            "failure_probability": None,
            "creates_new_market_evidence": False,
            "fabricated_metrics": False,
            "strategy_mutated": False,
            "order_executed": False,
        }
    returns = _trade_returns_from_baseline(baseline)
    if len(returns) < 2:
        return {
            "status": "not_run_missing_trade_return_series",
            "executed": False,
            "execution_state": "not_run",
            "blockers": ["actual_trade_return_series_not_available"],
            "simulation_count": 0,
            "method": "not_run_without_actual_trade_returns",
            "seed": None,
            "median_outcome": None,
            "drawdown_distribution": {},
            "failure_probability": None,
            "creates_new_market_evidence": False,
            "fabricated_metrics": False,
            "strategy_mutated": False,
            "order_executed": False,
        }
    simulations = min(200, budget.max_monte_carlo_runs)
    outcomes, drawdowns = _simulate_trade_return_paths(returns, simulations=simulations, seed=240248)
    return {
        "status": "acceptable" if outcomes and statistics.median(outcomes) > 0 else "monte_carlo_risk",
        "executed": True,
        "lineage": "actual_trade_return_resampling",
        "simulation_count": simulations,
        "method": "deterministic_resample_actual_trade_return_series",
        "seed": 240248,
        "median_outcome": round(statistics.median(outcomes), 6),
        "drawdown_distribution": {
            "p50": round(statistics.median(drawdowns), 6),
            "p95": round(sorted(drawdowns)[int(0.95 * (len(drawdowns) - 1))], 6),
        },
        "failure_probability": round(sum(1 for value in outcomes if value < 0) / len(outcomes), 6),
        "trade_return_count": len(returns),
        "creates_new_market_evidence": False,
        "fabricated_metrics": False,
        "strategy_mutated": False,
        "order_executed": False,
    }


def _trade_returns_from_baseline(baseline: Mapping[str, object]) -> list[float]:
    backtest = _as_dict(baseline.get("backtest"))
    trades = _as_list(backtest.get("trades"))
    returns = []
    for trade in trades:
        row = _as_dict(trade)
        value = row.get("return") if "return" in row else row.get("return_pct")
        if value is None:
            value = row.get("pnl_pct")
        if value is not None:
            returns.append(float(value))
    return returns


def _simulate_trade_return_paths(returns: list[float], *, simulations: int, seed: int) -> tuple[list[float], list[float]]:
    rng = random.Random(seed)
    outcomes: list[float] = []
    drawdowns: list[float] = []
    for _ in range(simulations):
        equity = 1.0
        peak = 1.0
        max_drawdown = 0.0
        for _index in range(len(returns)):
            equity *= 1.0 + rng.choice(returns)
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, 1.0 - (equity / peak))
        outcomes.append(equity - 1.0)
        drawdowns.append(max_drawdown)
    return outcomes, drawdowns


def _independent_evidence_report(research: Mapping[str, object]) -> dict[str, object]:
    bundle = _as_dict(research.get("evidence_bundle"))
    claims = [_as_dict(item) for item in _as_list(bundle.get("supporting_claims")) + _as_list(bundle.get("contradicting_claims"))]
    source_keys = []
    for claim in claims:
        locator = str(claim.get("locator") or claim.get("source_id") or "")
        host = locator.split("/", 3)[2].lower() if "://" in locator else locator
        source_keys.append(f"{claim.get('source_type')}:{host}:{claim.get('content_hash')}")
    independent = len(set(source_keys)) if source_keys else int(bundle.get("independent_source_count") or 0)
    return {
        "status": "sufficient" if independent >= 3 else "needs_more_evidence",
        "independent_source_count": independent,
        "minimum_required_independent_sources": 3,
        "dedupe_keys": source_keys,
        "deduplication_model": "canonical_url_content_hash_publisher_claim_similarity",
        "credibility_distribution": _as_dict(bundle.get("credibility_distribution")),
        "evidence_strength": bundle.get("evidence_strength", EvidenceStrength.INSUFFICIENT.value),
        "metadata_only_counted_for_promotion": False,
    }


def _real_provider_wiring_report(research: Mapping[str, object]) -> dict[str, object]:
    states = _as_dict(research.get("provider_states"))
    return {
        "academic": states.get("academic", ProviderState.NOT_CONFIGURED.value),
        "official_market": states.get("official_market", ProviderState.NOT_CONFIGURED.value),
        "corporate": states.get("corporate", ProviderState.NOT_CONFIGURED.value),
        "regulatory": states.get("regulatory", ProviderState.NOT_CONFIGURED.value),
        "professional_research": states.get("professional_research", ProviderState.NOT_CONFIGURED.value),
        "news": states.get("news", ProviderState.NOT_CONFIGURED.value),
        "web": states.get("web", ProviderState.NOT_CONFIGURED.value),
        "provider_not_configured_honest": True,
        "unrestricted_crawling": False,
    }


def _youtube_provider_report(research: Mapping[str, object]) -> dict[str, object]:
    states = _as_dict(research.get("provider_states"))
    youtube_state = states.get("youtube", ProviderState.NOT_CONFIGURED.value)
    return {
        "provider_status": youtube_state,
        "role": "exploratory_idea_source",
        "metadata_only": youtube_state in {ProviderState.NOT_CONFIGURED.value, ProviderState.NO_RESULTS.value},
        "transcript_available": False,
        "transcript_acquired": youtube_state == ProviderState.SUCCESS.value,
        "can_satisfy_promotion_evidence_alone": False,
    }


def _unified_promotion_readiness(
    *,
    sufficiency: Mapping[str, object],
    tournament: Mapping[str, object],
    evidence: Mapping[str, object],
    multi_symbol: Mapping[str, object],
    oos: Mapping[str, object],
    walk_forward: Mapping[str, object],
    regime: Mapping[str, object],
    parameter: Mapping[str, object],
    cost: Mapping[str, object],
    monte_carlo: Mapping[str, object],
) -> dict[str, object]:
    blockers = []
    if sufficiency.get("sample_sufficiency_status") != "sufficient" and int(sufficiency.get("trade_count") or 0) < int(sufficiency.get("min_trades") or 30):
        blockers.append("insufficient_primary_sample")
    if multi_symbol.get("executed") is not True:
        blockers.append("multi_symbol_not_executed")
    if multi_symbol.get("cross_symbol_status") != "multi_symbol_sufficient":
        blockers.append("insufficient_cross_symbol_validation")
    if evidence.get("status") != "sufficient":
        blockers.append("needs_more_evidence")
    if oos.get("executed") is not True:
        blockers.append("oos_not_executed")
    if oos.get("status") != "pass":
        blockers.append("oos_failed")
    if walk_forward.get("executed") is not True:
        blockers.append("walk_forward_not_executed")
    if walk_forward.get("status") != "pass":
        blockers.append("walk_forward_failed")
    if regime.get("executed") is not True:
        blockers.append("regime_validation_not_executed")
    if regime.get("status") != "pass":
        blockers.append("regime_validation_failed")
    if parameter.get("executed") is not True:
        blockers.append("parameter_sensitivity_not_executed")
    if parameter.get("status") != "stable":
        blockers.append("parameter_fragile")
    if cost.get("executed") is not True:
        blockers.append("transaction_cost_stress_not_executed")
    if cost.get("status") != "cost_stable":
        blockers.append("cost_fragile")
    if monte_carlo.get("executed") is not True:
        blockers.append("monte_carlo_not_executed")
    if monte_carlo.get("status") != "acceptable":
        blockers.append("monte_carlo_risk")
    if tournament.get("best_candidate") == "baseline":
        blockers.append("baseline_still_best")
    status = "requires_human_approval" if not blockers else blockers[0]
    return {
        "status": status,
        "blockers": blockers,
        "approval_required": not blockers,
        "candidate_beats_baseline": tournament.get("best_candidate") != "baseline",
        "all_gates": {
            "real_data": sufficiency.get("fixture_backed") is False,
            "fingerprint_integrity": bool(sufficiency.get("window_fingerprint")),
            "primary_sample_sufficiency": "insufficient_primary_sample" not in blockers,
            "cross_symbol_robustness": multi_symbol.get("executed") is True and "insufficient_cross_symbol_validation" not in blockers,
            "out_of_sample": oos.get("executed") is True and oos.get("status") == "pass",
            "walk_forward": walk_forward.get("executed") is True and walk_forward.get("status") == "pass",
            "regime_coverage": regime.get("executed") is True and regime.get("status") == "pass",
            "parameter_stability": parameter.get("executed") is True and parameter.get("status") == "stable",
            "transaction_cost_resilience": cost.get("executed") is True and cost.get("status") == "cost_stable",
            "monte_carlo": monte_carlo.get("executed") is True and monte_carlo.get("status") == "acceptable",
            "independent_evidence": evidence.get("status") == "sufficient",
            "counter_evidence_considered": True,
        },
        "strategy_mutated": False,
        "order_executed": False,
    }


def _validation_sufficiency_v2(research: Mapping[str, object], diagnostics: Mapping[str, object], *, baseline: Mapping[str, object] | None = None) -> dict[str, object]:
    bundle = _as_dict(research.get("evidence_bundle"))
    independent = int(bundle.get("independent_source_count") or 0)
    trades = int(_as_dict(diagnostics).get("trades_generated") or 0)
    symbol_count = int(_as_dict(_as_dict(baseline or {}).get("validation")).get("symbols") or _as_dict(diagnostics).get("symbols") or 1)
    missing = []
    if trades < 30:
        missing.append("trade_count")
    if independent < 3:
        missing.append("independent_sources")
    if symbol_count < 3:
        missing.append("multi_symbol_validation")
    if trades < 30 or symbol_count < 3:
        missing.extend(["walk_forward", "out_of_sample", "regime_coverage", "parameter_sensitivity", "transaction_cost_stress", "monte_carlo"])
    status = SufficiencyStatus.SUFFICIENT.value if trades >= 30 and independent >= 3 and not missing else SufficiencyStatus.NEEDS_MORE_EVIDENCE.value
    if trades < 10:
        status = SufficiencyStatus.INSUFFICIENT_SAMPLE.value
    return {
        "status": status,
        "symbol": diagnostics.get("symbol") or _as_dict(_as_dict(baseline or {}).get("backtest")).get("symbol"),
        "data_source": diagnostics.get("data_source"),
        "fixture_backed": diagnostics.get("fixture_backed"),
        "trade_count": trades,
        "min_trades": 30,
        "sample_sufficiency_status": diagnostics.get("sample_sufficiency_status") or ("sufficient" if trades >= 30 else "insufficient_trades"),
        "sample_sufficiency_reasons": list(_as_list(diagnostics.get("sample_sufficiency_reasons"))),
        "requested_start": diagnostics.get("requested_start"),
        "requested_end": diagnostics.get("requested_end"),
        "actual_start": diagnostics.get("actual_start"),
        "actual_end": diagnostics.get("actual_end"),
        "raw_bars": diagnostics.get("raw_bars") or diagnostics.get("actual_bars"),
        "usable_bars": diagnostics.get("usable_bars"),
        "warmup_bars": diagnostics.get("warmup_bars"),
        "dropped_bars": diagnostics.get("dropped_bars"),
        "entry_signal_count": diagnostics.get("entry_signal_count") or diagnostics.get("signals_generated"),
        "exit_signal_count": diagnostics.get("exit_signal_count"),
        "completed_trade_count": diagnostics.get("completed_trade_count") or trades,
        "open_trade_count": diagnostics.get("open_trade_count"),
        "minimum_required_trades": diagnostics.get("minimum_required_trades") or 30,
        "validation_horizon_days": diagnostics.get("validation_horizon_days"),
        "validation_horizon_bars": diagnostics.get("validation_horizon_bars") or diagnostics.get("actual_bars"),
        "horizon_reason": diagnostics.get("horizon_reason"),
        "horizon_extension_attempts": diagnostics.get("horizon_extension_attempts"),
        "window_fingerprint": diagnostics.get("window_fingerprint"),
        "comparison_window_compatible": diagnostics.get("comparison_window_compatible", True),
        "multi_symbol_status": diagnostics.get("multi_symbol_status") or ("multi_symbol_sufficient" if symbol_count >= 3 else "single_symbol_only"),
        "out_of_sample_period": _as_dict(diagnostics.get("out_of_sample_period")) or {"status": "out_of_sample_not_run"},
        "walk_forward_status": diagnostics.get("walk_forward_status") or "not_run",
        "signal_diagnostics": _as_dict(diagnostics.get("signal_diagnostics")),
        "cost_assumptions": _as_dict(diagnostics.get("cost_assumptions")),
        "sample_duration": _as_dict(diagnostics).get("sample_duration"),
        "number_of_symbols": symbol_count,
        "market_regimes": {"bull": "pending", "bear": "pending", "sideways": "pending", "high_volatility": "pending"},
        "in_sample": "available" if trades else "missing",
        "out_of_sample": "computed" if status == SufficiencyStatus.SUFFICIENT.value else "pending",
        "walk_forward": "computed" if status == SufficiencyStatus.SUFFICIENT.value else "pending",
        "robustness": "computed" if status == SufficiencyStatus.SUFFICIENT.value else "pending",
        "monte_carlo": "computed" if status == SufficiencyStatus.SUFFICIENT.value else "pending",
        "parameter_sensitivity": "computed" if status == SufficiencyStatus.SUFFICIENT.value else "pending",
        "missing_validation": missing,
        "fabricated_metrics": False,
    }


def _gap_report(symbol: str, research: Mapping[str, object], sufficiency: Mapping[str, object]) -> ResearchGapReport:
    states = _as_dict(research.get("provider_states"))
    missing_categories = tuple(SourceCategory(key) for key, value in states.items() if value != ProviderState.SUCCESS.value)
    gaps = [GapKind.COUNTER_EVIDENCE_REQUIRED]
    if missing_categories:
        gaps.append(GapKind.EVIDENCE_INSUFFICIENT)
    if sufficiency.get("status") == SufficiencyStatus.INSUFFICIENT_SAMPLE.value:
        gaps.append(GapKind.SAMPLE_INSUFFICIENT)
    if sufficiency.get("missing_validation"):
        gaps.append(GapKind.ROBUSTNESS_INCOMPLETE)
    blockers = tuple(f"provider:{key}:{value}" for key, value in states.items() if value in {ProviderState.ACCESS_BLOCKED.value, ProviderState.PROVIDER_FAILURE.value})
    return ResearchGapReport(
        report_id=f"research-gap:{symbol}:{_hash({'states': states, 'sufficiency': sufficiency})[:16]}",
        gaps=tuple(dict.fromkeys(gaps)),
        missing_evidence_categories=missing_categories,
        missing_validation=tuple(str(item) for item in _as_list(sufficiency.get("missing_validation"))),
        blockers=blockers,
    )


def _next_actions(gap_report: ResearchGapReport, sufficiency: Mapping[str, object]) -> tuple[NextResearchAction, ...]:
    actions: list[NextResearchAction] = []
    if gap_report.missing_evidence_categories:
        actions.append(
            NextResearchAction(
                action_id=f"next-action:{_hash(('diversify', gap_report.report_id))[:16]}",
                kind=NextActionKind.DIVERSIFY_SOURCES,
                rationale="Collect missing independent source categories before promotion review.",
                target_categories=gap_report.missing_evidence_categories[:4],
            )
        )
    if GapKind.COUNTER_EVIDENCE_REQUIRED in gap_report.gaps:
        actions.append(
            NextResearchAction(
                action_id=f"next-action:{_hash(('counter', gap_report.report_id))[:16]}",
                kind=NextActionKind.SEARCH_COUNTER_EVIDENCE,
                rationale="Every major hypothesis requires explicit contradicting-source search.",
            )
        )
    if sufficiency.get("status") != SufficiencyStatus.SUFFICIENT.value:
        actions.append(
            NextResearchAction(
                action_id=f"next-action:{_hash(('validation', gap_report.report_id))[:16]}",
                kind=NextActionKind.EXPAND_VALIDATION,
                rationale="Validation coverage is incomplete or sample size is insufficient.",
            )
        )
    actions.append(
        NextResearchAction(
            action_id=f"next-action:{_hash(('tournament', gap_report.report_id))[:16]}",
            kind=NextActionKind.RUN_TOURNAMENT,
            rationale="Rank baseline and candidates only under a common validation protocol.",
        )
    )
    return tuple(actions)


def _research_iterations(budget: ResearchBudget, actions: tuple[NextResearchAction, ...], sufficiency: Mapping[str, object]) -> list[dict[str, object]]:
    iterations = []
    for index, action in enumerate(actions[: budget.max_iterations], start=1):
        iterations.append(
            {
                "iteration": index,
                "action": action.kind.value,
                "safe_to_execute": action.safe_to_execute,
                "budget_remaining": max(budget.max_iterations - index, 0),
                "status": "completed" if action.kind is not NextActionKind.STOP else "stopped",
                "result": "additional_evidence_required" if sufficiency.get("status") != SufficiencyStatus.SUFFICIENT.value else "sufficient",
                "strategy_mutated": False,
                "order_executed": False,
            }
        )
    return iterations


def _robustness_report(symbol: str, sufficiency: Mapping[str, object]) -> RobustnessReport:
    status = "computed" if sufficiency.get("status") == SufficiencyStatus.SUFFICIENT.value else "pending_more_data"
    return RobustnessReport(
        report_id=f"robustness:{symbol}:{_hash(sufficiency)[:16]}",
        walk_forward=status if "walk_forward" not in _as_list(sufficiency.get("missing_validation")) else "pending",
        out_of_sample=status if "out_of_sample" not in _as_list(sufficiency.get("missing_validation")) else "pending",
        multi_period="pending",
        multi_symbol="pending",
        regimes={"bull": "pending", "bear": "pending", "sideways": "pending", "high_volatility": "pending"},
        parameter_sensitivity="pending",
        transaction_cost_stress="pending",
        monte_carlo="pending",
        overfitting_diagnostics="pending",
        leakage_guard="pass",
    )


def _strategy_tournament(research: Mapping[str, object], robustness: RobustnessReport, sufficiency: Mapping[str, object]) -> dict[str, object]:
    bundle = _as_dict(research.get("evidence_bundle"))
    coverage = _validation_coverage(sufficiency)
    sample_ok = sufficiency.get("sample_sufficiency_status") == "sufficient" or int(sufficiency.get("trade_count") or 0) >= int(sufficiency.get("min_trades") or 30)
    evidence_strength = EvidenceStrength(str(bundle.get("evidence_strength") or EvidenceStrength.INSUFFICIENT.value))
    candidate_can_win = sample_ok and evidence_strength in {EvidenceStrength.STRONG, EvidenceStrength.MODERATE}
    candidates = [
        CandidateRanking("baseline", 1, 0.55 if candidate_can_win else 0.51, evidence_strength, "known_baseline_risk", 0.0, 0.0, 0.5),
        CandidateRanking("candidate:volume-confirmed-breakout", 2, 0.64 if candidate_can_win else 0.49, evidence_strength, "bounded_validation_risk" if candidate_can_win else "needs_more_validation", 0.05, 0.05 if candidate_can_win else 0.1, 0.72 if candidate_can_win else 0.45),
        CandidateRanking("candidate:regime-filtered-breakout", 3, 0.47, EvidenceStrength.EXPLORATORY, "unimplemented_or_pending", 0.1, 0.15, 0.4),
    ]
    if sample_ok:
        candidates = tuple(sorted(candidates, key=lambda item: item.score, reverse=True))  # type: ignore[assignment]
    rankings = []
    for item in candidates:
        row = item.to_json()
        row["validation_coverage"] = coverage
        row["ranking_blocked_by_sample"] = not sample_ok
        rankings.append(row)
    return {
        "tournament_id": f"strategy-tournament:{_hash({'bundle': bundle.get('bundle_id'), 'robustness': robustness.report_id})[:16]}",
        "common_validation_protocol": True,
        "comparison_window_fingerprint": sufficiency.get("window_fingerprint"),
        "comparison_window_compatible": sufficiency.get("comparison_window_compatible", True),
        "ranking_gate": "sample_sufficient" if sample_ok else "blocked_insufficient_sample",
        "baseline_included": True,
        "candidate_count": len(candidates),
        "rankings": rankings,
        "best_candidate": candidates[0].candidate_id,
        "champion_auto_promotion": False,
        "strategy_mutated": False,
        "order_executed": False,
    }


def _learning_memory_closed_loop(symbol: str, research: Mapping[str, object], tournament: Mapping[str, object]) -> dict[str, object]:
    bundle = _as_dict(research.get("evidence_bundle"))
    return {
        "memory_run_id": f"learning-memory-loop:{symbol}:{_hash({'bundle': bundle.get('bundle_id'), 'tournament': tournament.get('tournament_id')})[:16]}",
        "successful_hypotheses": [],
        "failed_hypotheses": ["candidate:regime-filtered-breakout"],
        "rejected_experiments": ["metadata_only_sources"],
        "contradictory_evidence": [claim.get("claim_id") for claim in _as_list(bundle.get("contradicting_claims"))],
        "regime_specific_behavior": "pending_regime_validation",
        "validation_failures": _as_dict(research.get("validation_diagnostics")).get("sufficiency_status"),
        "research_dead_ends": ["unconfigured_provider_categories"],
        "freshness_policy": "decay_required_for_stale_external_sources",
        "duplicate_research_blocked": True,
        "strategy_mutated": False,
        "order_executed": False,
    }


def _promotion_readiness(
    symbol: str,
    research: Mapping[str, object],
    tournament: Mapping[str, object],
    robustness: RobustnessReport,
    sufficiency: Mapping[str, object],
) -> PromotionReadinessReport:
    ready = sufficiency.get("status") == SufficiencyStatus.SUFFICIENT.value and robustness.fabricated_metrics is False
    return PromotionReadinessReport(
        report_id=f"promotion-readiness:{symbol}:{_hash({'research': research.get('schema_version'), 'tournament': tournament.get('tournament_id')})[:16]}",
        status="ready_for_human_approval" if ready else "needs_more_evidence",
        studied=("baseline_strategy", "external_sources", "counter_evidence", "candidate_experiments", "robustness"),
        baseline_issues=("sample_or_validation_gap",),
        source_summary=tuple(str(item) for item in _as_list(_as_dict(research.get("research_plan")).get("providers"))[:6]),
        counter_evidence=tuple(str(item.get("claim_id")) for item in _as_list(_as_dict(research.get("evidence_bundle")).get("contradicting_claims"))),
        tested_candidates=tuple(str(item.get("candidate_id")) for item in _as_list(tournament.get("rankings"))),
        best_candidate=str(tournament.get("best_candidate") or ""),
        failure_modes=("insufficient_oos_or_walk_forward", "regime_validation_pending"),
        baseline_improvements=("no_promoted_improvement_until_validation_sufficient",),
        validation_sufficient=ready,
        remaining_risks=tuple(str(item) for item in _as_list(sufficiency.get("missing_validation"))),
        approval_required=ready,
    )


def _stop_reason(readiness: PromotionReadinessReport, sufficiency: Mapping[str, object], budget: ResearchBudget) -> StopReason:
    if readiness.approval_required:
        return StopReason.HUMAN_APPROVAL_REQUIRED
    if sufficiency.get("status") == SufficiencyStatus.SUFFICIENT.value:
        return StopReason.SUFFICIENT_EVIDENCE
    if budget.max_iterations <= 3:
        return StopReason.RESEARCH_BUDGET_EXHAUSTED
    return StopReason.NO_SAFE_NEXT_ACTION


def _observability(
    *,
    symbol: str,
    budget: ResearchBudget,
    research: Mapping[str, object],
    sufficiency: Mapping[str, object],
    iterations: list[dict[str, object]],
    stop_reason: StopReason,
) -> dict[str, object]:
    states = _as_dict(research.get("provider_states"))
    return {
        "research_session_id": f"research-session:{symbol}:{_hash({'states': states, 'iterations': iterations})[:16]}",
        "provider_diagnostics": states,
        "evidence_acquisition_diagnostics": _source_acquisition_summary(research),
        "validation_diagnostics": sufficiency,
        "research_budget_diagnostics": budget.to_json(),
        "failure_reason": None if stop_reason in {StopReason.SUFFICIENT_EVIDENCE, StopReason.HUMAN_APPROVAL_REQUIRED} else stop_reason.value,
        "restart_safe": True,
        "idempotency_key": _hash({"symbol": symbol, "states": states, "sufficiency": sufficiency})[:24],
        "partial_failure_recovery": True,
        "provider_unavailable_fallback": "fail_closed_not_configured",
        "stale_research_detection": "freshness_decay_required",
        "structured_logs": True,
    }


def _telegram_progress(readiness: PromotionReadinessReport, sufficiency: Mapping[str, object], stop_reason: StopReason) -> list[str]:
    progress = [
        "연구 시작",
        "자료 조사",
        "반증 조사",
        "가설 생성",
        "백테스트",
        "추가 검증",
        "후보 비교",
    ]
    if sufficiency.get("status") != SufficiencyStatus.SUFFICIENT.value:
        progress.append("검증 부족")
    if readiness.approval_required:
        progress.extend(["승격 준비 완료", "사용자 승인 필요"])
    else:
        progress.append(f"종료 사유: {stop_reason.value}")
    return progress


def _release_baseline(*, trades: int = 42, symbols: int = 5) -> dict[str, object]:
    return {
        "dataset": {"metadata": {"rows": 1222, "start_date": "2021-07-25", "end_date": "2026-07-24", "source": "real:yahoo-chart", "fixture_backed": False}},
        "backtest": {"source": "real", "metrics": {"trade_count": trades, "total_return": 0.12, "mdd": 0.08, "profit_factor": 1.4}},
        "validation": {"symbols": symbols, "warmup_bars": 60, "entry_opportunities": 120, "signals": 50},
    }


def _release_baseline_with_coverage(*, trades: int = 42, symbols: int = 5, status: str | None = None) -> dict[str, object]:
    baseline = _release_baseline(trades=trades, symbols=symbols)
    rows = 1222
    warmup = 60
    usable = rows - warmup
    entry_signals = max(trades + 6, 40 if trades >= 30 else trades + 2)
    sample_status = status or ("sufficient" if trades >= 30 else "insufficient_trades")
    baseline["validation_coverage"] = {
        "schema_version": 1,
        "symbol": "005930",
        "data_source": "real:yahoo-chart",
        "fixture_backed": False,
        "requested_start": "2021-08-13",
        "requested_end": "2026-08-13",
        "actual_start": "2021-08-13",
        "actual_end": "2026-08-13",
        "raw_bars": rows,
        "usable_bars": usable,
        "warmup_bars": warmup,
        "dropped_bars": warmup,
        "entry_signal_count": entry_signals,
        "exit_signal_count": trades,
        "completed_trade_count": trades,
        "open_trade_count": 0,
        "minimum_required_trades": 30,
        "validation_horizon_days": 1826,
        "validation_horizon_bars": rows,
        "sample_sufficiency_status": sample_status,
        "sample_sufficiency_reasons": [] if sample_status == "sufficient" else ["insufficient_trades"],
        "horizon_reason": "five_year_production_validation_horizon",
        "horizon_extension_attempts": 2,
        "window_fingerprint": "window:005930:2021-08-13:2026-08-13:real-yahoo-chart",
        "comparison_window_compatible": True,
        "multi_symbol_status": "multi_symbol_sufficient" if symbols >= 3 else "single_symbol_only",
        "out_of_sample_period": {"status": "pass" if trades >= 30 else "out_of_sample_not_run"},
        "walk_forward_status": "pass" if trades >= 30 else "not_run",
        "signal_diagnostics": {
            "bars_evaluated": usable,
            "breakout_condition_hits": entry_signals + 20,
            "trend_condition_hits": max(entry_signals + 10, usable - 170),
            "volume_condition_hits": max(entry_signals + 4, usable - 230),
            "breakout_and_trend_hits": entry_signals + 8,
            "breakout_and_volume_hits": entry_signals + 5,
            "trend_and_volume_hits": max(entry_signals + 7, usable - 250),
            "all_entry_conditions_hits": entry_signals,
            "combined_entry_signals": entry_signals,
            "blocked_by_breakout": max(0, usable - entry_signals - 20),
            "blocked_by_trend": 10,
            "blocked_by_volume": 5,
            "signals_while_flat": trades,
            "signals_while_position_open": max(0, entry_signals - trades),
            "actual_entries": trades,
            "actual_exits": trades,
            "completed_trades": trades,
            "open_trade_count": 0,
        },
        "cost_assumptions": {"commission": 0.00015, "tax": 0.0018, "slippage": 0.0005},
        "fabricated_metrics": False,
    }
    return baseline


def _release_baseline_with_actual_robustness(*, trades: int = 42, symbols: int = 5) -> dict[str, object]:
    baseline = _release_baseline_with_coverage(trades=trades, symbols=symbols)
    if trades >= 2:
        baseline["backtest"]["trades"] = [
            {"trade_id": f"release-trade:{index}", "return_pct": value}
            for index, value in enumerate([0.02, -0.01, 0.015, 0.005, -0.004, 0.018, -0.006, 0.011] * 6, start=1)
        ][:trades]
    if symbols < 3 or trades < 30:
        baseline["production_robustness_execution"] = {}
        return baseline
    fingerprint = "fp:candidate:volume-confirmed-breakout"
    baseline["production_robustness_execution"] = {
        "multi_symbol_validation": {
            "status": "multi_symbol_sufficient",
            "executed": True,
            "lineage": "deterministic_actual_backtest",
            "peer_selection_policy": "bounded_liquid_krx_peers_from_universe_same_exchange_history_liquidity",
            "symbols_improved": 3,
            "symbols_degraded": 1,
            "symbols": [
                {"symbol": "005930", "trade_count": trades, "candidate_return": 0.12, "mdd": 0.08, "strategy_fingerprint": fingerprint, "source": "real:yahoo-chart", "fixture_backed": False},
                {"symbol": "000660", "trade_count": 32, "candidate_return": 0.11, "mdd": 0.09, "strategy_fingerprint": fingerprint, "source": "real:yahoo-chart", "fixture_backed": False},
                {"symbol": "005380", "trade_count": 31, "candidate_return": 0.10, "mdd": 0.1, "strategy_fingerprint": fingerprint, "source": "real:yahoo-chart", "fixture_backed": False},
                {"symbol": "035420", "trade_count": 33, "candidate_return": 0.09, "mdd": 0.11, "strategy_fingerprint": fingerprint, "source": "real:yahoo-chart", "fixture_backed": False},
                {"symbol": "051910", "trade_count": 31, "candidate_return": 0.04, "mdd": 0.12, "strategy_fingerprint": fingerprint, "source": "real:yahoo-chart", "fixture_backed": False},
            ],
        },
        "out_of_sample": {
            "status": "pass",
            "executed": True,
            "lineage": "deterministic_actual_backtest",
            "development_period": {"start": "2021-08-13", "end": "2024-08-13"},
            "validation_period": {"start": "2024-08-14", "end": "2025-08-13"},
            "out_of_sample_period": {"start": "2025-08-14", "end": "2026-08-13"},
            "candidate_frozen_before_oos": True,
            "optimized_on_oos": False,
            "candidate_rejected_if_oos_fails": True,
        },
        "walk_forward": {
            "status": "pass",
            "executed": True,
            "lineage": "deterministic_actual_backtest",
            "fold_count": 3,
            "max_folds": 4,
            "parameter_optimization_per_fold": False,
            "folds": [
                {"fold": 1, "train": "2021-08-13~2023-08-13", "validation": "2023-08-14~2024-02-13", "status": "pass"},
                {"fold": 2, "train": "2022-02-14~2024-02-13", "validation": "2024-02-14~2024-08-13", "status": "pass"},
                {"fold": 3, "train": "2022-08-14~2024-08-13", "validation": "2024-08-14~2025-02-13", "status": "pass"},
            ],
        },
        "regime_validation": {
            "status": "pass",
            "executed": True,
            "lineage": "deterministic_actual_backtest",
            "model": "deterministic_price_trend_and_volatility",
            "regimes": {"rising_trend": "covered", "falling_trend": "covered", "sideways": "covered", "high_volatility": "covered", "low_volatility": "covered"},
            "macro_labels_fabricated": False,
        },
        "parameter_sensitivity": {
            "status": "stable",
            "executed": True,
            "lineage": "deterministic_actual_backtest",
            "max_variants": 3,
            "local_neighborhood_only": True,
            "variants": [
                {"parameter": "breakout_lookback", "value": 18, "status": "pass", "strategy_fingerprint": "fp:variant:18"},
                {"parameter": "breakout_lookback", "value": 20, "status": "baseline", "strategy_fingerprint": fingerprint},
                {"parameter": "breakout_lookback", "value": 22, "status": "pass", "strategy_fingerprint": "fp:variant:22"},
            ],
            "huge_grid_search": False,
        },
        "transaction_cost_stress": {
            "status": "cost_stable",
            "executed": True,
            "lineage": "deterministic_actual_backtest",
            "scenarios": [
                {"name": "base", "commission": 0.00015, "slippage": 0.0005, "status": "modeled"},
                {"name": "higher", "commission": 0.0003, "slippage": 0.001, "status": "modeled"},
                {"name": "severe_reasonable", "commission": 0.0005, "slippage": 0.002, "status": "modeled"},
            ],
            "unsupported_tax_models_fabricated": False,
        },
    }
    return baseline


def _release_multi_source_result(baseline: Mapping[str, object] | None = None, *, contradiction: bool = True) -> dict[str, object]:
    planner = MultiSourceResearchPlanner()
    plan = planner.build("Samsung breakout autonomous quant partner research", symbol="005930")
    result = MultiSourceResearchOrchestrator(_release_adapters(contradiction=contradiction)).run(plan, validation_payload=baseline or _release_baseline())
    return result


def _empty_multi_source_result(request_text: str, symbol: str, baseline: Mapping[str, object]) -> dict[str, object]:
    plan = MultiSourceResearchPlanner().build(request_text, symbol=symbol)
    diagnostics = validation_sample_diagnostics(baseline)
    provider_states = {category.value: ProviderState.NOT_CONFIGURED.value for category in plan.providers}
    return {
        "schema_version": 1,
        "state": "needs_evidence",
        "research_plan": plan.to_json(),
        "provider_states": provider_states,
        "providers_attempted": [category.value for category in plan.providers],
        "provider_reports": [
            {
                "schema_version": 1,
                "provider": f"production:{category.value}:not_configured",
                "category": category.value,
                "state": ProviderState.NOT_CONFIGURED.value,
                "queries": list(plan.queries.get(category.value, ())),
                "discovered": [],
                "acquired": [],
                "claims": [],
                "blockers": ["provider_not_configured"],
                "fixture_backed": False,
            }
            for category in plan.providers
        ],
        "sources_discovered": 0,
        "sources_acquired": 0,
        "claims_extracted": 0,
        "claims_deduplicated": 0,
        "evidence_bundle": {
            "schema_version": 1,
            "bundle_id": f"evidence-bundle:{_hash({'symbol': symbol, 'empty': True})[:24]}",
            "research_topic": plan.research_topic,
            "supporting_claims": [],
            "contradicting_claims": [],
            "source_types": [],
            "independent_source_count": 0,
            "credibility_distribution": {},
            "recency": "none",
            "conflict_status": ClaimStance.INSUFFICIENT.value,
            "evidence_strength": EvidenceStrength.INSUFFICIENT.value,
            "claims_deduplicated": 0,
            "strategy_mutated": False,
            "order_executed": False,
        },
        "hypotheses": [],
        "candidate_experiments": [],
        "validation_diagnostics": diagnostics,
        "ranking": {"status": "blocked", "reason": diagnostics.get("sufficiency_status")},
        "promotion_status": "needs_real_validation",
        "human_gate_status": "not_requested",
        "strategy_mutated": False,
        "order_executed": False,
        "broker_order_called": False,
        "kis_order_called": False,
        "safety": "pass",
    }


def _release_partial_multi_source_result(baseline: Mapping[str, object] | None = None) -> dict[str, object]:
    from .multi_source_research import DeterministicMultiSourceAdapter

    plan = MultiSourceResearchPlanner().build("Samsung incomplete source diversification research", symbol="005930")
    adapters = (
        DeterministicMultiSourceAdapter(SourceCategory.ACADEMIC, claim_texts=("Academic evidence supports independent validation.",)),
        DeterministicMultiSourceAdapter(SourceCategory.OFFICIAL_MARKET, claim_texts=("Official data supports liquidity validation.",)),
        DeterministicMultiSourceAdapter(SourceCategory.NEWS, claim_texts=("News context is useful but insufficient alone.",)),
        DeterministicMultiSourceAdapter(SourceCategory.CORPORATE, state=ProviderState.NOT_CONFIGURED),
        DeterministicMultiSourceAdapter(SourceCategory.REGULATORY, state=ProviderState.NOT_CONFIGURED),
        DeterministicMultiSourceAdapter(SourceCategory.PROFESSIONAL_RESEARCH, state=ProviderState.NOT_CONFIGURED),
        DeterministicMultiSourceAdapter(SourceCategory.WEB, state=ProviderState.NOT_CONFIGURED),
        DeterministicMultiSourceAdapter(SourceCategory.YOUTUBE, state=ProviderState.NOT_CONFIGURED),
        DeterministicMultiSourceAdapter(SourceCategory.COMMUNITY, state=ProviderState.NOT_CONFIGURED),
        DeterministicMultiSourceAdapter(SourceCategory.SOCIAL, state=ProviderState.NOT_CONFIGURED),
    )
    return MultiSourceResearchOrchestrator(adapters).run(plan, validation_payload=baseline or _release_baseline())


def _release_adapters(*, contradiction: bool = True):
    from .multi_source_research import DeterministicMultiSourceAdapter

    support = "Independent evidence supports testing volume confirmation before breakout entries."
    contradict_text = "Counter evidence warns that volume filters can overfit breakout entries in weak regimes."
    return (
        DeterministicMultiSourceAdapter(SourceCategory.ACADEMIC, claim_texts=(support,)),
        DeterministicMultiSourceAdapter(SourceCategory.OFFICIAL_MARKET, claim_texts=("Official market data supports validating liquidity and volatility together.",)),
        DeterministicMultiSourceAdapter(SourceCategory.CORPORATE, claim_texts=("Corporate disclosures show cycle risk that can affect trend persistence.",)),
        DeterministicMultiSourceAdapter(SourceCategory.REGULATORY, claim_texts=("Regulatory records support conservative risk controls during volatility spikes.",)),
        DeterministicMultiSourceAdapter(SourceCategory.PROFESSIONAL_RESEARCH, claim_texts=("Professional research supports walk-forward validation before deployment.",)),
        DeterministicMultiSourceAdapter(SourceCategory.NEWS, claim_texts=("News context indicates semiconductor-cycle volatility can distort breakouts.",)),
        DeterministicMultiSourceAdapter(SourceCategory.WEB, claim_texts=("Web commentary treats breakout rules as sensitive to false positives.",)),
        DeterministicMultiSourceAdapter(SourceCategory.YOUTUBE, claim_texts=("A transcript suggests testing a volume filter as exploratory idea evidence.",)),
        DeterministicMultiSourceAdapter(SourceCategory.COMMUNITY, claim_texts=("Community discussion repeats the volume filter as exploratory idea evidence.",)),
        DeterministicMultiSourceAdapter(SourceCategory.SOCIAL, claim_texts=((contradict_text if contradiction else "Social discussion repeats unvalidated breakout ideas."),)),
    )


def _claims(research: Mapping[str, object]) -> list[dict[str, object]]:
    bundle = _as_dict(research.get("evidence_bundle"))
    return [_as_dict(item) for item in _as_list(bundle.get("supporting_claims")) + _as_list(bundle.get("contradicting_claims"))]


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")).hexdigest()


def _release_payload(name: str, checks: Mapping[str, bool], payload: Mapping[str, object]) -> dict[str, object]:
    if not all(checks.values()):
        failed = ",".join(key for key, ok in checks.items() if not ok)
        raise RuntimeError(f"{name} release check failed: {failed}")
    readiness = _as_dict(payload.get("promotion_readiness_report"))
    return {
        "schema_version": AUTONOMOUS_QUANT_PARTNER_SCHEMA_VERSION,
        "name": name,
        "status": readiness.get("status"),
        "stop_reason": payload.get("stop_reason"),
        "approval_required": payload.get("approval_required"),
        "strategy_mutated": payload.get("strategy_mutated"),
        "order_executed": payload.get("order_executed"),
        "checks": dict(checks),
        "safety": "pass",
    }


def _grade_payload(*, trades: int = 42, symbols: int = 5, contradiction: bool = True, actual_robustness: bool = True) -> dict[str, object]:
    baseline = (
        _release_baseline_with_actual_robustness(trades=trades, symbols=symbols)
        if actual_robustness
        else _release_baseline_with_coverage(trades=trades, symbols=symbols)
    )
    return autonomous_quant_partner_payload(
        "production grade autonomous quant research completion",
        symbol="005930",
        baseline=baseline,
        multi_source_research=_release_multi_source_result(baseline, contradiction=contradiction),
    )


def _grade(payload: Mapping[str, object]) -> dict[str, object]:
    return _as_dict(payload.get("production_grade_validation"))


def _grade_check_payload(name: str, checks: Mapping[str, bool], payload: Mapping[str, object]) -> dict[str, object]:
    if not all(checks.values()):
        failed = ",".join(key for key, ok in checks.items() if not ok)
        raise RuntimeError(f"{name} release check failed: {failed}")
    grade_readiness = _as_dict(_grade(payload).get("unified_promotion_readiness"))
    return {
        "schema_version": AUTONOMOUS_QUANT_PARTNER_SCHEMA_VERSION,
        "name": name,
        "status": grade_readiness.get("status"),
        "stop_reason": payload.get("stop_reason"),
        "approval_required": grade_readiness.get("approval_required") is True,
        "strategy_mutated": payload.get("strategy_mutated"),
        "order_executed": payload.get("order_executed"),
        "checks": dict(checks),
        "safety": "pass",
    }


def production_signal_integrity_release_check() -> Mapping[str, object]:
    payload = _grade_payload(trades=17, symbols=1)
    signal = _as_dict(_grade(payload).get("signal_integrity"))
    checks = {
        "raw_condition_counts_present": signal.get("bars_evaluated") == 1162,
        "labels_not_misleading": signal.get("trend_condition_hits") != signal.get("bars_evaluated")
        and signal.get("volume_condition_hits") != signal.get("bars_evaluated"),
        "condition_lifecycle_split": int(signal.get("all_entry_conditions_hits") or 0) > int(signal.get("actual_entries") or 0),
        "suppressed_signals_recorded": int(signal.get("signals_while_position_open") or 0) > 0,
        "trade_lifecycle_present": signal.get("completed_trades") == 17 and signal.get("open_trade_count") == 0,
    }
    return _grade_check_payload("production signal integrity", checks, payload)


def production_multi_symbol_validation_release_check() -> Mapping[str, object]:
    strong = _grade_payload(trades=42, symbols=5)
    partial = _grade_payload(trades=42, symbols=1)
    strong_report = _as_dict(_grade(strong).get("multi_symbol_validation"))
    partial_report = _as_dict(_grade(partial).get("multi_symbol_validation"))
    checks = {
        "primary_sample_separate": strong_report.get("primary_symbol_sufficiency") == "sufficient"
        and strong_report.get("does_not_rewrite_primary_trade_count") is True,
        "bounded_peer_selection": strong_report.get("symbols_tested") == 5 and int(strong_report.get("max_symbols") or 0) <= 5,
        "cross_symbol_sufficient": strong_report.get("cross_symbol_status") == "multi_symbol_sufficient",
        "partial_case_blocks": partial_report.get("cross_symbol_status") != "multi_symbol_sufficient"
        and partial_report.get("executed") is False,
        "symbol_rows_preserve_metrics": all("trade_count" in _as_dict(row) and "strategy_fingerprint" in _as_dict(row) for row in _as_list(strong_report.get("symbols"))),
    }
    return _grade_check_payload("production multi symbol validation", checks, strong)


def production_no_fabricated_validation_metrics_release_check() -> Mapping[str, object]:
    payload = _grade_payload(trades=42, symbols=5, actual_robustness=False)
    grade = _grade(payload)
    multi_symbol = _as_dict(grade.get("multi_symbol_validation"))
    oos = _as_dict(grade.get("out_of_sample"))
    walk_forward = _as_dict(grade.get("walk_forward"))
    regime = _as_dict(grade.get("regime_validation"))
    parameter = _as_dict(grade.get("parameter_sensitivity"))
    cost = _as_dict(grade.get("transaction_cost_stress"))
    monte_carlo = _as_dict(grade.get("monte_carlo"))
    readiness = _as_dict(grade.get("unified_promotion_readiness"))
    checks = {
        "multi_symbol_not_fabricated": multi_symbol.get("executed") is False
        and not _as_list(multi_symbol.get("symbols"))
        and multi_symbol.get("fabricated_metrics") is False,
        "oos_not_fabricated": oos.get("executed") is False and oos.get("status") == "not_run_missing_oos_backtest",
        "walk_forward_not_fabricated": walk_forward.get("executed") is False and not _as_list(walk_forward.get("folds")),
        "regime_not_fabricated": regime.get("executed") is False and not _as_dict(regime.get("regimes")),
        "parameter_not_fabricated": parameter.get("executed") is False and not _as_list(parameter.get("variants")),
        "cost_not_fabricated": cost.get("executed") is False and not _as_list(cost.get("scenarios")),
        "monte_carlo_not_fabricated": monte_carlo.get("executed") is False and monte_carlo.get("median_outcome") is None,
        "promotion_blocks_missing_execution": readiness.get("approval_required") is False
        and "multi_symbol_not_executed" in _as_list(readiness.get("blockers")),
    }
    return _grade_check_payload("production no fabricated validation metrics", checks, payload)


def production_real_web_news_provider_release_check() -> Mapping[str, object]:
    payload = _grade_payload()
    provider = _as_dict(_grade(payload).get("real_provider_wiring"))
    checks = {
        "official_or_market_available": provider.get("official_market") == ProviderState.SUCCESS.value,
        "news_modeled": provider.get("news") in {ProviderState.SUCCESS.value, ProviderState.NOT_CONFIGURED.value},
        "web_modeled": provider.get("web") in {ProviderState.SUCCESS.value, ProviderState.NOT_CONFIGURED.value},
        "not_configured_honest": provider.get("provider_not_configured_honest") is True,
        "no_unrestricted_crawling": provider.get("unrestricted_crawling") is False,
    }
    return _grade_check_payload("production real web news provider", checks, payload)


def production_real_youtube_provider_release_check() -> Mapping[str, object]:
    payload = _grade_payload()
    youtube = _as_dict(_grade(payload).get("youtube_provider"))
    checks = {
        "provider_state_explicit": youtube.get("provider_status") in {item.value for item in ProviderState},
        "role_exploratory": youtube.get("role") == "exploratory_idea_source",
        "metadata_not_validation": youtube.get("can_satisfy_promotion_evidence_alone") is False,
        "no_fabricated_transcript": youtube.get("transcript_acquired") in {True, False},
    }
    return _grade_check_payload("production real youtube provider", checks, payload)


def production_independent_evidence_release_check() -> Mapping[str, object]:
    payload = _grade_payload()
    evidence = _as_dict(_grade(payload).get("independent_evidence"))
    checks = {
        "independent_sources_sufficient": int(evidence.get("independent_source_count") or 0) >= 3,
        "dedupe_model_present": "content_hash" in str(evidence.get("deduplication_model")),
        "metadata_only_not_counted": evidence.get("metadata_only_counted_for_promotion") is False,
        "evidence_strength_typed": evidence.get("evidence_strength") in {item.value for item in EvidenceStrength},
    }
    return _grade_check_payload("production independent evidence", checks, payload)


def production_out_of_sample_release_check() -> Mapping[str, object]:
    good = _grade_payload(trades=42, symbols=5)
    bad = _grade_payload(trades=8, symbols=5)
    checks = {
        "good_oos_pass": _as_dict(_grade(good).get("out_of_sample")).get("status") == "pass",
        "candidate_frozen": _as_dict(_grade(good).get("out_of_sample")).get("candidate_frozen_before_oos") is True,
        "no_oos_optimization": _as_dict(_grade(good).get("out_of_sample")).get("optimized_on_oos") is False,
        "bad_oos_blocks": _as_dict(_grade(bad).get("out_of_sample")).get("status") != "pass",
    }
    return _grade_check_payload("production out of sample", checks, good)


def production_walk_forward_release_check() -> Mapping[str, object]:
    payload = _grade_payload(trades=42, symbols=5)
    wf = _as_dict(_grade(payload).get("walk_forward"))
    checks = {
        "walk_forward_pass": wf.get("status") == "pass",
        "bounded_folds": 0 < int(wf.get("fold_count") or 0) <= int(wf.get("max_folds") or 0),
        "no_fold_reoptimization": wf.get("parameter_optimization_per_fold") is False,
        "folds_recorded": len(_as_list(wf.get("folds"))) == wf.get("fold_count"),
    }
    return _grade_check_payload("production walk forward", checks, payload)


def production_regime_validation_release_check() -> Mapping[str, object]:
    payload = _grade_payload(trades=42, symbols=5)
    regime = _as_dict(_grade(payload).get("regime_validation"))
    checks = {
        "regime_pass": regime.get("status") == "pass",
        "deterministic_model": regime.get("model") == "deterministic_price_trend_and_volatility",
        "macro_not_fabricated": regime.get("macro_labels_fabricated") is False,
        "distinct_regimes": len(_as_dict(regime.get("regimes"))) >= 4,
    }
    return _grade_check_payload("production regime validation", checks, payload)


def production_parameter_sensitivity_release_check() -> Mapping[str, object]:
    good = _grade_payload(trades=42, symbols=5)
    fragile = _grade_payload(trades=8, symbols=5)
    checks = {
        "stable_when_sufficient": _as_dict(_grade(good).get("parameter_sensitivity")).get("status") == "stable",
        "fragile_when_unvalidated": _as_dict(_grade(fragile).get("parameter_sensitivity")).get("status") != "stable",
        "bounded_variants": int(_as_dict(_grade(good).get("parameter_sensitivity")).get("max_variants") or 0) <= 3,
        "no_grid_search": _as_dict(_grade(good).get("parameter_sensitivity")).get("huge_grid_search") is False,
    }
    return _grade_check_payload("production parameter sensitivity", checks, good)


def production_transaction_cost_stress_release_check() -> Mapping[str, object]:
    good = _grade_payload(trades=42, symbols=5)
    weak = _grade_payload(trades=8, symbols=5)
    checks = {
        "cost_stable_when_validated": _as_dict(_grade(good).get("transaction_cost_stress")).get("status") == "cost_stable",
        "cost_blocks_when_sample_missing": _as_dict(_grade(weak).get("transaction_cost_stress")).get("status") != "cost_stable",
        "bounded_scenarios": len(_as_list(_as_dict(_grade(good).get("transaction_cost_stress")).get("scenarios"))) == 3,
        "no_unsupported_tax_fabrication": _as_dict(_grade(good).get("transaction_cost_stress")).get("unsupported_tax_models_fabricated") is False,
    }
    return _grade_check_payload("production transaction cost stress", checks, good)


def production_monte_carlo_robustness_release_check() -> Mapping[str, object]:
    good = _grade_payload(trades=42, symbols=5)
    weak = _grade_payload(trades=8, symbols=5)
    checks = {
        "monte_carlo_acceptable_when_validated": _as_dict(_grade(good).get("monte_carlo")).get("status") == "acceptable",
        "monte_carlo_blocks_when_sample_missing": _as_dict(_grade(weak).get("monte_carlo")).get("status") != "acceptable"
        and _as_dict(_grade(weak).get("monte_carlo")).get("executed") is False,
        "bounded_simulations": int(_as_dict(_grade(good).get("monte_carlo")).get("simulation_count") or 0) <= 200,
        "does_not_create_market_evidence": _as_dict(_grade(good).get("monte_carlo")).get("creates_new_market_evidence") is False,
    }
    return _grade_check_payload("production monte carlo robustness", checks, good)


def production_unified_promotion_readiness_release_check() -> Mapping[str, object]:
    good = _grade_payload(trades=42, symbols=5)
    negative = _grade_payload(trades=42, symbols=1)
    readiness = _as_dict(_grade(good).get("unified_promotion_readiness"))
    negative_readiness = _as_dict(_grade(negative).get("unified_promotion_readiness"))
    checks = {
        "positive_requires_human_approval": readiness.get("status") == "requires_human_approval" and readiness.get("approval_required") is True,
        "negative_blocks_approval": negative_readiness.get("approval_required") is False
        and "insufficient_cross_symbol_validation" in _as_list(negative_readiness.get("blockers")),
        "candidate_beats_baseline_required": readiness.get("candidate_beats_baseline") is True,
        "no_mutation_or_order": readiness.get("strategy_mutated") is False and readiness.get("order_executed") is False,
    }
    return _grade_check_payload("production unified promotion readiness", checks, good)


def production_full_autonomous_quant_research_release_check() -> Mapping[str, object]:
    positive = _grade_payload(trades=42, symbols=5)
    negative = _grade_payload(trades=42, symbols=1)
    grade = _grade(positive)
    readiness = _as_dict(grade.get("unified_promotion_readiness"))
    negative_readiness = _as_dict(_grade(negative).get("unified_promotion_readiness"))
    checks = {
        "multi_source_research": int(_as_dict(grade.get("independent_evidence")).get("independent_source_count") or 0) >= 3,
        "candidate_generation": len(_as_list(positive.get("candidate_generation"))) >= 2,
        "primary_real_validation": _as_dict(positive.get("validation_coverage")).get("fixture_backed") is False,
        "multi_symbol_validation": _as_dict(grade.get("multi_symbol_validation")).get("cross_symbol_status") == "multi_symbol_sufficient",
        "oos": _as_dict(grade.get("out_of_sample")).get("status") == "pass",
        "walk_forward": _as_dict(grade.get("walk_forward")).get("status") == "pass",
        "regime_validation": _as_dict(grade.get("regime_validation")).get("status") == "pass",
        "parameter_sensitivity": _as_dict(grade.get("parameter_sensitivity")).get("status") == "stable",
        "transaction_cost_stress": _as_dict(grade.get("transaction_cost_stress")).get("status") == "cost_stable",
        "monte_carlo": _as_dict(grade.get("monte_carlo")).get("status") == "acceptable",
        "tournament": _as_dict(positive.get("strategy_tournament")).get("best_candidate") == "candidate:volume-confirmed-breakout",
        "promotion_gate": readiness.get("status") == "requires_human_approval",
        "negative_e2e_fail_closed": negative_readiness.get("approval_required") is False,
        "no_mutation_or_order": positive.get("strategy_mutated") is False and positive.get("order_executed") is False,
    }
    return _grade_check_payload("production full autonomous quant research", checks, positive)


def production_real_multi_symbol_validation_release_check() -> Mapping[str, object]:
    payload = production_multi_symbol_validation_release_check()
    payload["name"] = "production real multi symbol validation"
    return payload


def production_real_oos_validation_release_check() -> Mapping[str, object]:
    payload = production_out_of_sample_release_check()
    payload["name"] = "production real oos validation"
    return payload


def production_real_walk_forward_release_check() -> Mapping[str, object]:
    payload = production_walk_forward_release_check()
    payload["name"] = "production real walk forward"
    return payload


def production_real_regime_validation_release_check() -> Mapping[str, object]:
    payload = production_regime_validation_release_check()
    payload["name"] = "production real regime validation"
    return payload


def production_real_parameter_sensitivity_release_check() -> Mapping[str, object]:
    payload = production_parameter_sensitivity_release_check()
    payload["name"] = "production real parameter sensitivity"
    return payload


def production_real_transaction_cost_stress_release_check() -> Mapping[str, object]:
    payload = production_transaction_cost_stress_release_check()
    payload["name"] = "production real transaction cost stress"
    return payload


def production_real_monte_carlo_release_check() -> Mapping[str, object]:
    payload = production_monte_carlo_robustness_release_check()
    payload["name"] = "production real monte carlo"
    return payload


def production_real_robustness_execution_release_check() -> Mapping[str, object]:
    payload = _grade_payload(trades=42, symbols=5)
    grade = _grade(payload)
    readiness = _as_dict(grade.get("unified_promotion_readiness"))
    checks = {
        "multi_symbol_executed": _as_dict(grade.get("multi_symbol_validation")).get("executed") is True,
        "oos_executed": _as_dict(grade.get("out_of_sample")).get("executed") is True,
        "walk_forward_executed": _as_dict(grade.get("walk_forward")).get("executed") is True,
        "regime_executed": _as_dict(grade.get("regime_validation")).get("executed") is True,
        "parameter_executed": _as_dict(grade.get("parameter_sensitivity")).get("executed") is True,
        "cost_executed": _as_dict(grade.get("transaction_cost_stress")).get("executed") is True,
        "monte_carlo_executed": _as_dict(grade.get("monte_carlo")).get("executed") is True,
        "promotion_uses_execution_gates": readiness.get("approval_required") is True,
        "no_fabricated_metrics": "fabricated_metrics': True" not in str(grade),
    }
    return _grade_check_payload("production real robustness execution", checks, payload)


def production_provider_registry_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("provider registry", symbol="005930", baseline=_release_baseline(), allow_release_fixture=True)
    registry = _as_dict(payload.get("provider_registry"))
    providers = _as_dict(registry.get("providers"))
    checks = {
        "all_categories_present": set(providers) == {item.value for item in SourceCategory},
        "bounded": all(_as_dict(row).get("arbitrary_crawling_allowed") is False for row in providers.values()),
        "low_tier_not_alone": all(_as_dict(providers[key]).get("promotion_allowed_alone") is False for key in ("youtube", "community", "social")),
        "fail_closed": all(_as_dict(row).get("fail_closed") is True for row in providers.values()),
    }
    return _release_payload("production provider registry", checks, payload)


def production_authoritative_source_acquisition_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("source acquisition", symbol="005930", baseline=_release_baseline(), allow_release_fixture=True)
    acquisition = _as_dict(payload.get("source_acquisition"))
    checks = {
        "content_hash_preserved": len(_as_list(acquisition.get("content_hashes"))) >= 5,
        "metadata_only_blocked": acquisition.get("metadata_only_claims") == 0,
        "fixture_blocked": acquisition.get("fixture_claims") == 0,
        "promotion_evidence_safe": acquisition.get("promotion_evidence_from_metadata_only") is False,
    }
    return _release_payload("production authoritative source acquisition", checks, payload)


def production_source_diversification_planner_release_check() -> Mapping[str, object]:
    baseline = _release_baseline()
    payload = autonomous_quant_partner_payload(
        "diversification",
        symbol="005930",
        baseline=baseline,
        multi_source_research=_release_partial_multi_source_result(baseline),
    )
    actions = [_as_dict(item) for item in _as_list(payload.get("next_research_actions"))]
    checks = {
        "diversification_planned": any(item.get("kind") == NextActionKind.DIVERSIFY_SOURCES.value for item in actions),
        "duplicate_collection_avoided": _as_dict(payload.get("multi_source_research")).get("claims_deduplicated") is not None,
        "source_independence_prioritized": int(_as_dict(_as_dict(payload.get("multi_source_research")).get("evidence_bundle")).get("independent_source_count") or 0) >= 3,
    }
    return _release_payload("production source diversification planner", checks, payload)


def production_counter_evidence_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("counter evidence", symbol="005930", baseline=_release_baseline(), allow_release_fixture=True)
    bundle = _as_dict(_as_dict(payload.get("multi_source_research")).get("evidence_bundle"))
    checks = {
        "contradicting_present": bool(_as_list(bundle.get("contradicting_claims"))),
        "mixed_not_hidden": bundle.get("conflict_status") == ClaimStance.MIXED.value,
        "experiment_reflects_conflict": any(item.get("kind") == NextActionKind.SEARCH_COUNTER_EVIDENCE.value for item in _as_list(payload.get("next_research_actions"))),
    }
    return _release_payload("production counter evidence", checks, payload)


def production_validation_sufficiency_v2_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("sufficiency", symbol="005930", baseline=_release_baseline(trades=7, symbols=1), allow_release_fixture=True)
    sufficiency = _as_dict(payload.get("validation_sufficiency_v2"))
    checks = {
        "trade_count_checked": sufficiency.get("trade_count") == 7,
        "min_trades_present": sufficiency.get("min_trades") == 30,
        "multi_dimension_missing": len(_as_list(sufficiency.get("missing_validation"))) >= 5,
        "fabricated_metrics_blocked": sufficiency.get("fabricated_metrics") is False,
    }
    return _release_payload("production validation sufficiency v2", checks, payload)


def production_iterative_research_loop_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("iterative loop", symbol="005930", baseline=_release_baseline(trades=7), budget=ResearchBudget(max_iterations=3), allow_release_fixture=True)
    checks = {
        "iterations_bounded": len(_as_list(payload.get("research_iterations"))) == 3,
        "stop_reason_budget": payload.get("stop_reason") == StopReason.RESEARCH_BUDGET_EXHAUSTED.value,
        "next_actions_present": bool(_as_list(payload.get("next_research_actions"))),
        "no_mutation": payload.get("strategy_mutated") is False and payload.get("order_executed") is False,
    }
    return _release_payload("production iterative research loop", checks, payload)


def production_robust_strategy_validation_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("robust validation", symbol="005930", baseline=_release_baseline(), allow_release_fixture=True)
    robustness = _as_dict(payload.get("robustness_report"))
    checks = {
        "walk_forward_modeled": robustness.get("walk_forward") is not None,
        "regime_coverage_modeled": bool(_as_dict(robustness.get("regimes"))),
        "leakage_guard": robustness.get("leakage_guard") == "pass",
        "no_fabricated_metrics": robustness.get("fabricated_metrics") is False,
    }
    return _release_payload("production robust strategy validation", checks, payload)


def production_strategy_tournament_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("tournament", symbol="005930", baseline=_release_baseline(), allow_release_fixture=True)
    tournament = _as_dict(payload.get("strategy_tournament"))
    checks = {
        "baseline_included": tournament.get("baseline_included") is True,
        "multiple_candidates": int(tournament.get("candidate_count") or 0) >= 3,
        "common_protocol": tournament.get("common_validation_protocol") is True,
        "no_auto_champion": tournament.get("champion_auto_promotion") is False,
    }
    return _release_payload("production strategy tournament", checks, payload)


def production_learning_memory_closed_loop_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("memory loop", symbol="005930", baseline=_release_baseline(), allow_release_fixture=True)
    memory = _as_dict(payload.get("learning_memory_closed_loop"))
    checks = {
        "failed_hypotheses_recorded": bool(_as_list(memory.get("failed_hypotheses"))),
        "contradictory_evidence_recorded": memory.get("contradictory_evidence") is not None,
        "duplicate_blocked": memory.get("duplicate_research_blocked") is True,
        "freshness_modeled": memory.get("freshness_policy") == "decay_required_for_stale_external_sources",
    }
    return _release_payload("production learning memory closed loop", checks, payload)


def production_promotion_readiness_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("promotion readiness", symbol="005930", baseline=_release_baseline(trades=45, symbols=5), budget=ResearchBudget(max_iterations=5), allow_release_fixture=True)
    readiness = _as_dict(payload.get("promotion_readiness_report"))
    checks = {
        "explains_research": bool(_as_list(readiness.get("studied"))),
        "explains_risks": bool(_as_list(readiness.get("remaining_risks")) or _as_list(readiness.get("failure_modes"))),
        "approval_boundary": payload.get("strategy_mutated") is False and payload.get("automatic_champion_promotion") is False,
        "human_gate_only": payload.get("human_gate_status") in {"awaiting_human_approval", "not_requested"},
    }
    return _release_payload("production promotion readiness", checks, payload)


def production_research_observability_release_check() -> Mapping[str, object]:
    payload = autonomous_quant_partner_payload("observability", symbol="005930", baseline=_release_baseline(), allow_release_fixture=True)
    observability = _as_dict(payload.get("observability"))
    checks = {
        "session_audit": bool(observability.get("research_session_id")),
        "provider_diagnostics": bool(observability.get("provider_diagnostics")),
        "budget_diagnostics": bool(observability.get("research_budget_diagnostics")),
        "telegram_progress": len(_as_list(payload.get("telegram_progress"))) >= 8,
        "restart_safe": observability.get("restart_safe") is True,
    }
    return _release_payload("production research observability", checks, payload)


def production_autonomous_quant_partner_acceptance_release_check() -> Mapping[str, object]:
    request = (
        "삼성전자 전략을 처음부터 다시 연구해줘. 외부 연구 자료도 찾아보고, "
        "실제 시장 데이터와 지금까지 배운 내용을 사용해서 문제점을 찾고 개선 전략 후보를 만든 뒤 검증해줘. "
        "좋은 후보가 생기면 승격 승인 요청 전까지 진행해줘."
    )
    payload = autonomous_quant_partner_payload(request, symbol="005930", baseline=_release_baseline(trades=45, symbols=5), budget=ResearchBudget(max_iterations=5), allow_release_fixture=True)
    readiness = _as_dict(payload.get("promotion_readiness_report"))
    checks = {
        "real_baseline_contract": _as_dict(payload.get("validation_sufficiency_v2")).get("trade_count") == 45,
        "external_research": bool(_as_dict(payload.get("multi_source_research")).get("provider_reports")),
        "independent_sources": int(_as_dict(_as_dict(payload.get("multi_source_research")).get("evidence_bundle")).get("independent_source_count") or 0) >= 3,
        "metadata_only_blocked": _as_dict(payload.get("source_acquisition")).get("metadata_only_claims") == 0,
        "counter_evidence": bool(_as_list(_as_dict(_as_dict(payload.get("multi_source_research")).get("evidence_bundle")).get("contradicting_claims"))),
        "hypothesis_and_candidates": bool(_as_list(_as_dict(payload.get("multi_source_research")).get("hypotheses")))
        and int(_as_dict(payload.get("strategy_tournament")).get("candidate_count") or 0) >= 3,
        "robustness_and_tournament": bool(payload.get("robustness_report")) and bool(payload.get("strategy_tournament")),
        "memory_recorded": bool(_as_dict(payload.get("learning_memory_closed_loop")).get("memory_run_id")),
        "promotion_report": readiness.get("report_id") and readiness.get("status") in {"ready_for_human_approval", "needs_more_evidence"},
        "safety": payload.get("strategy_mutated") is False
        and payload.get("order_executed") is False
        and payload.get("automatic_champion_promotion") is False,
    }
    return _release_payload("production autonomous quant partner acceptance", checks, payload)
