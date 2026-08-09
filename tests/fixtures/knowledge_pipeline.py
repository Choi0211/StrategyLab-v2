from __future__ import annotations

import hashlib
import json

from gaon.knowledge.evidence_hypothesis import EvidenceBackedHypothesisGenerator
from gaon.knowledge.external_research_memory import ExternalResearchMemoryRecord
from gaon.knowledge.strategy_experiment import StrategyExperimentBuilder, StrategyResearchExperiment
from gaon.research.krx_real_pipeline import (
    BacktestExecutionAssumptionSet,
    CanonicalStrategySpec,
    FieldProvenance,
    MarketDataAvailability,
    ProvenancedValue,
    RealBacktestResult,
    RealPerformanceMetrics,
    default_execution_assumptions,
)


def stable_fingerprint(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_strategy(*, symbol: str = "005930", created_at: str = "2026-08-08T00:00:00+00:00") -> CanonicalStrategySpec:
    return CanonicalStrategySpec(
        spec_id=f"strategy:{symbol}:fixture",
        symbol=symbol,
        entry={
            "breakout_lookback": ProvenancedValue(20, FieldProvenance.USER_PROVIDED),
            "close_gt_ma20": ProvenancedValue(True, FieldProvenance.USER_PROVIDED),
            "ma20_gt_ma60": ProvenancedValue(True, FieldProvenance.USER_PROVIDED),
        },
        exit={
            "protective_stop_pct": ProvenancedValue(-5, FieldProvenance.USER_PROVIDED),
            "channel_exit_lookback": ProvenancedValue(10, FieldProvenance.USER_PROVIDED),
        },
        filters={"volume_gte_ma20": ProvenancedValue(True, FieldProvenance.USER_PROVIDED)},
        source_text="20일 고가 돌파",
        created_at=created_at,
    )


def build_experiment(
    *,
    strategy: CanonicalStrategySpec | None = None,
    assumptions: BacktestExecutionAssumptionSet | None = None,
    start: str = "2021-07-25",
    end: str = "2026-07-24",
) -> StrategyResearchExperiment:
    strategy = strategy or build_strategy()
    assumptions = assumptions or default_execution_assumptions()
    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:fixture-experiment",
        fingerprint="c" * 64,
        topic_key="strategy.breakout.robustness",
        loop_id="knowledge-research-loop:fixture-experiment",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a",),
        question_ids=("research-question:a",),
        source_ids=("source:a",),
        created_at="2026-08-08T00:00:00+00:00",
    )
    hypothesis = EvidenceBackedHypothesisGenerator().generate(
        topic_key=memory.topic_key,
        memories=(memory,),
        changed_rules=("add regime filter before breakout entries",),
        rationale="Evidence quality should control validation progression.",
        mechanism="Only structured backtest evidence may validate the experiment.",
        falsification_criteria=("Reject if authoritative metrics are missing.",),
    )
    return StrategyExperimentBuilder().build(
        hypothesis=hypothesis,
        baseline_strategy_id=strategy.spec_id,
        baseline_strategy_fingerprint=strategy.fingerprint,
        assumptions_fingerprint=stable_fingerprint(assumptions.to_json()),
        universe_symbols=(strategy.symbol,),
        start=start,
        end=end,
    )


def build_real_backtest(
    experiment: StrategyResearchExperiment,
    *,
    source: MarketDataAvailability = MarketDataAvailability.FIXTURE,
    trade_count: int = 60,
    profit_factor: float | None = 1.6,
    generated_at: str = "2026-08-08T00:00:00+00:00",
) -> RealBacktestResult:
    strategy = build_strategy(symbol=experiment.universe_symbols[0], created_at=generated_at)
    assumptions = default_execution_assumptions()
    metrics = RealPerformanceMetrics(
        total_return=0.18,
        cagr=0.035,
        mdd=0.09,
        sharpe=0.7,
        win_rate=0.56,
        profit_factor=profit_factor,
        trade_count=trade_count,
        average_trade=0.003,
        average_win=0.012,
        average_loss=-0.008,
        payoff_ratio=1.5,
        exposure=0.42,
        ending_equity=1_180_000.0,
        expectancy=0.003,
        longest_losing_streak=3,
    )
    return RealBacktestResult(
        result_id=f"backtest:{experiment.experiment_id}:fixture",
        run_id=f"{experiment.experiment_id}:run",
        status="completed",
        source=source,
        strategy=strategy,
        dataset_id=f"dataset:{strategy.symbol}:fixture",
        dataset_fingerprint="d" * 64,
        assumptions=assumptions,
        metrics=metrics,
        trades=(),
        equity_curve=(),
        warnings=(),
        generated_at=generated_at,
    )
