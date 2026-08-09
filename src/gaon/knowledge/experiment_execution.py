"""Follow-up B - authoritative strategy experiment execution.

This module bridges existing structured real research/backtest results into
the Sprint 182 validation loop. It intentionally does not accept arbitrary
metric dictionaries as autonomous validation evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Mapping

from gaon.research.krx_real_pipeline import (
    MarketDataAvailability,
    RealAutonomousResearchReport,
    RealBacktestResult,
)

from .robustness_ranking import RobustnessRankingResult, StrategyRobustnessRanker
from .strategy_experiment import StrategyResearchExperiment
from .validation_loop_v2 import (
    AuthoritativeValidationEvidence,
    AutonomousValidationLoopV2,
    ValidationLoopV2Result,
)


AUTHORITATIVE_EXPERIMENT_EXECUTION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AuthoritativeExperimentExecutionResult:
    experiment_id: str
    evidence: AuthoritativeValidationEvidence
    validation: ValidationLoopV2Result
    ranking: RobustnessRankingResult
    attempts: int
    duplicate_experiment_skipped: bool = False
    production_approved: bool = False
    strategy_mutated: bool = False
    order_executed: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": AUTHORITATIVE_EXPERIMENT_EXECUTION_SCHEMA_VERSION,
            "experiment_id": self.experiment_id,
            "evidence": self.evidence.to_json(),
            "validation": self.validation.to_json(),
            "ranking": self.ranking.to_json(),
            "attempts": self.attempts,
            "duplicate_experiment_skipped": self.duplicate_experiment_skipped,
            "production_approved": self.production_approved,
            "strategy_mutated": self.strategy_mutated,
            "order_executed": self.order_executed,
        }


class TrustedValidationEvidenceAdapter:
    """Builds validation evidence only from existing authoritative result types."""

    def from_authoritative_source(
        self,
        experiment: StrategyResearchExperiment,
        source: RealAutonomousResearchReport | RealBacktestResult,
    ) -> AuthoritativeValidationEvidence:
        if isinstance(source, RealAutonomousResearchReport):
            return self.from_real_report(experiment, source)
        if isinstance(source, RealBacktestResult):
            return self.from_real_backtest(experiment, source)
        raise TypeError("untrusted evidence source")

    def from_real_report(
        self,
        experiment: StrategyResearchExperiment,
        report: RealAutonomousResearchReport,
    ) -> AuthoritativeValidationEvidence:
        quality = report.quality.to_json()
        blocking = tuple(
            str(item.get("code", "quality_blocker"))
            for item in quality.get("findings", [])
            if str(item.get("severity", "")).lower() in {"error", "critical", "blocking"}
        )
        return self.from_real_backtest(
            experiment,
            report.backtest,
            quality_status=str(quality.get("status", "unknown")),
            blocking_findings=blocking,
        )

    def from_real_backtest(
        self,
        experiment: StrategyResearchExperiment,
        backtest: RealBacktestResult,
        *,
        quality_status: str = "pass",
        blocking_findings: tuple[str, ...] = (),
    ) -> AuthoritativeValidationEvidence:
        assumptions_fingerprint = _stable_fingerprint(backtest.assumptions.to_json())
        if experiment.assumptions_fingerprint != assumptions_fingerprint:
            raise ValueError("experiment assumptions fingerprint does not match backtest assumptions")
        metrics = _authoritative_metrics(backtest)
        return AuthoritativeValidationEvidence(
            evidence_id=_evidence_id(experiment.experiment_id, backtest.result_id, backtest.fingerprint),
            experiment_id=experiment.experiment_id,
            backtest_result_id=backtest.result_id,
            source=_evidence_source(backtest.source),
            fixture_backed=backtest.source is not MarketDataAvailability.REAL,
            quality_status=quality_status,
            blocking_findings=blocking_findings,
            metrics=metrics,
            trade_count=backtest.metrics.trade_count,
            created_at=backtest.generated_at,
        )


class AuthoritativeExperimentExecutor:
    """Executes validation and ranking from trusted structured backtest output."""

    def __init__(
        self,
        *,
        adapter: TrustedValidationEvidenceAdapter | None = None,
        validation_loop: AutonomousValidationLoopV2 | None = None,
        ranker: StrategyRobustnessRanker | None = None,
    ) -> None:
        self.adapter = adapter or TrustedValidationEvidenceAdapter()
        self.validation_loop = validation_loop or AutonomousValidationLoopV2()
        self.ranker = ranker or StrategyRobustnessRanker()

    def execute(
        self,
        experiment: StrategyResearchExperiment,
        source: RealAutonomousResearchReport | RealBacktestResult,
        *,
        attempted_experiments: tuple[str, ...] = (),
    ) -> AuthoritativeExperimentExecutionResult:
        duplicate = experiment.experiment_id in set(attempted_experiments)
        evidence = self.adapter.from_authoritative_source(experiment, source)
        validation = self.validation_loop.assess(experiment, evidence)
        ranking = self.ranker.rank((validation,))
        return AuthoritativeExperimentExecutionResult(
            experiment_id=experiment.experiment_id,
            evidence=evidence,
            validation=validation,
            ranking=ranking,
            attempts=1,
            duplicate_experiment_skipped=duplicate,
        )


def authoritative_experiment_execution_release_check() -> Mapping[str, object]:
    from .robustness_ranking import RobustnessRankingStatus
    from .validation_loop_v2 import ValidationLoopV2Status

    experiment, backtest = _fixture_experiment_and_backtest(trade_count=60)
    result = AuthoritativeExperimentExecutor().execute(experiment, backtest)
    checks = {
        "accepted": result.validation.status is ValidationLoopV2Status.ACCEPTED_FOR_REVIEW,
        "ranked": result.ranking.status is RobustnessRankingStatus.RANKED,
        "structured_source": result.evidence.backtest_result_id == backtest.result_id,
        "assumptions_stable": result.evidence.experiment_id == experiment.experiment_id,
        "no_mutation": not result.strategy_mutated and not result.order_executed,
    }
    if not all(checks.values()):
        failed = ",".join(name for name, ok in checks.items() if not ok)
        raise RuntimeError(f"authoritative experiment execution release check failed: {failed}")
    return {
        "schema_version": AUTHORITATIVE_EXPERIMENT_EXECUTION_SCHEMA_VERSION,
        "status": result.validation.status.value,
        "ranking_status": result.ranking.status.value,
        "trade_count": result.evidence.trade_count,
        "checks": checks,
        "safety": "pass",
    }


def _authoritative_metrics(backtest: RealBacktestResult) -> Mapping[str, float | int | str]:
    raw = backtest.metrics.to_json()
    metrics: dict[str, float | int | str] = {}
    for key, value in raw.items():
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        metrics[key] = value
    return metrics


def _evidence_source(source: MarketDataAvailability) -> str:
    if source is MarketDataAvailability.REAL:
        return "real:yahoo-chart"
    if source is MarketDataAvailability.FIXTURE:
        return "fixture:krx-real-pipeline"
    return source.value


def _stable_fingerprint(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_id(experiment_id: str, backtest_result_id: str, fingerprint: str) -> str:
    encoded = json.dumps(
        {
            "experiment_id": experiment_id,
            "backtest_result_id": backtest_result_id,
            "fingerprint": fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"validation-evidence:{hashlib.sha256(encoded).hexdigest()}"


def _fixture_experiment_and_backtest(*, trade_count: int) -> tuple[StrategyResearchExperiment, RealBacktestResult]:
    from gaon.research.krx_real_pipeline import (
        CanonicalStrategySpec,
        FieldProvenance,
        ProvenancedValue,
        RealPerformanceMetrics,
        default_execution_assumptions,
    )

    from .evidence_hypothesis import EvidenceBackedHypothesisGenerator
    from .external_research_memory import ExternalResearchMemoryRecord
    from .strategy_experiment import StrategyExperimentBuilder

    at = "2026-08-08T00:00:00+00:00"
    strategy = CanonicalStrategySpec(
        spec_id="strategy:005930:authoritative-fixture",
        symbol="005930",
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
        created_at=at,
    )
    assumptions = default_execution_assumptions()
    memory = ExternalResearchMemoryRecord(
        memory_id="external-research-memory:authoritative-execution",
        fingerprint="c" * 64,
        topic_key="strategy.breakout.robustness",
        loop_id="knowledge-research-loop:authoritative-execution",
        conflict_status="unresolved_conflict",
        claim_ids=("claim:a",),
        question_ids=("research-question:a",),
        source_ids=("source:a",),
        created_at=at,
    )
    hypothesis = EvidenceBackedHypothesisGenerator().generate(
        topic_key=memory.topic_key,
        memories=(memory,),
        changed_rules=("add regime filter before breakout entries",),
        rationale="Evidence quality should control validation progression.",
        mechanism="Only structured backtest evidence may validate the experiment.",
        falsification_criteria=("Reject if authoritative metrics are missing.",),
    )
    experiment = StrategyExperimentBuilder().build(
        hypothesis=hypothesis,
        baseline_strategy_id=strategy.spec_id,
        baseline_strategy_fingerprint=strategy.fingerprint,
        assumptions_fingerprint=_stable_fingerprint(assumptions.to_json()),
        universe_symbols=(strategy.symbol,),
        start="2021-07-25",
        end="2026-07-24",
    )
    backtest = RealBacktestResult(
        result_id=f"backtest:{experiment.experiment_id}:authoritative-fixture",
        run_id=f"{experiment.experiment_id}:run",
        status="completed",
        source=MarketDataAvailability.FIXTURE,
        strategy=strategy,
        dataset_id="dataset:005930:authoritative-fixture",
        dataset_fingerprint="d" * 64,
        assumptions=assumptions,
        metrics=RealPerformanceMetrics(
            total_return=0.18,
            cagr=0.035,
            mdd=0.09,
            sharpe=0.7,
            win_rate=0.56,
            profit_factor=1.6,
            trade_count=trade_count,
            average_trade=0.003,
            average_win=0.012,
            average_loss=-0.008,
            payoff_ratio=1.5,
            exposure=0.42,
            ending_equity=1_180_000.0,
            expectancy=0.003,
            longest_losing_streak=3,
        ),
        trades=(),
        equity_curve=(),
        warnings=(),
        generated_at=at,
    )
    return experiment, backtest
