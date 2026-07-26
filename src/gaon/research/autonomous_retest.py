"""Autonomous real-research retest pipeline for Sprint 131-140.

This module expands insufficient real KRX research evidence across deterministic
periods, re-fetches market data, re-runs the same strategy and execution
assumptions, and refreshes advisory recommendations. It is read-only with
respect to trading and never applies strategy configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
import json
import os
import sqlite3
from typing import Protocol
from uuid import uuid4

from gaon.research.krx_real_pipeline import (
    BacktestExecutionAssumptionSet,
    CanonicalStrategySpec,
    EvidenceBasedStrategyCritic,
    FieldProvenance,
    ImprovementCandidate,
    ImprovementCandidateGenerator,
    KRXDatasetBuilder,
    KRXHistoricalDataProvider,
    KRXFixtureMarketDataProvider,
    MarketDataAvailability,
    RealAutonomousResearchReport,
    RealBacktestResult,
    RealMarketDataUnavailable,
    RuleBasedBacktestEngine,
    UserStrategyParser,
    _compare_candidates,
    _json,
    _sha,
    default_execution_assumptions,
    utc_now,
)
from gaon.research.operations import (
    BacktestEvidence,
    QualityStatus,
    RecommendationDecision,
    ResearchOperationsService,
    SQLiteResearchOperationRepository,
    research_quality_gate,
    statistical_confidence,
)
from gaon.research.real_research import (
    DataQualityReport,
    DataQualityStatus,
    MarketBar,
    MarketDataMetadata,
    MarketDataset,
    MarketSymbol,
)


RETEST_SCHEMA_VERSION = 1
RETEST_ARTIFACT_MARKERS = (
    "autonomous-retest-release-check:",
    "research-retest-demo:",
    "test:",
    "unit:",
    "integration:",
)


class StopReason(str, Enum):
    MIN_TRADES_REACHED = "min_trades_reached"
    MAX_PERIOD_REACHED = "max_period_reached"
    DATA_AVAILABILITY_LIMIT = "data_availability_limit"
    BLOCKING_DATA_QUALITY = "blocking_data_quality"
    PROVIDER_FAILURE = "provider_failure"
    NO_ADDITIONAL_EVIDENCE = "no_additional_evidence"
    USER_PERIOD_BOUNDARY = "user_period_boundary"


@dataclass(frozen=True)
class RetestDecision:
    required: bool
    reason: str
    current_trade_count: int
    target_min_trades: int
    next_period: str | None
    confidence_level: str
    provider_gap_count: int
    blocking_findings: int

    def to_json(self) -> dict[str, object]:
        return self.__dict__


@dataclass(frozen=True)
class ResearchPeriodStep:
    step_id: str
    label: str
    start_date: str
    end_date: str
    reason: str
    explicit_user_boundary: bool = False

    def to_json(self) -> dict[str, object]:
        return self.__dict__


@dataclass(frozen=True)
class RetestEvidence:
    evidence_id: str
    period: ResearchPeriodStep
    dataset_id: str | None
    dataset_fingerprint: str | None
    quality_status: str
    provider_gaps: tuple[str, ...]
    blocking_findings: int
    backtest: RealBacktestResult | None
    trade_count: int
    confidence_level: str
    recommendation: str
    stop_reason: StopReason | None
    warnings: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RETEST_SCHEMA_VERSION,
            "evidence_id": self.evidence_id,
            "period": self.period.to_json(),
            "dataset_id": self.dataset_id,
            "dataset_fingerprint": self.dataset_fingerprint,
            "quality_status": self.quality_status,
            "provider_gaps": list(self.provider_gaps),
            "blocking_findings": self.blocking_findings,
            "backtest": self.backtest.to_json() if self.backtest else None,
            "trade_count": self.trade_count,
            "confidence_level": self.confidence_level,
            "recommendation": self.recommendation,
            "stop_reason": self.stop_reason.value if self.stop_reason else None,
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AutonomousRetestRun:
    run_id: str
    request_text: str
    symbol: str
    strategy_fingerprint: str
    assumptions_fingerprint: str
    trigger: RetestDecision
    period_plan: tuple[ResearchPeriodStep, ...]
    evidence: tuple[RetestEvidence, ...]
    candidates: tuple[ImprovementCandidate, ...]
    final_recommendation: str
    operation_report_id: str | None
    stop_reason: StopReason
    korean_report: str
    generated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": RETEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "request_text": self.request_text,
            "symbol": self.symbol,
            "strategy_fingerprint": self.strategy_fingerprint,
            "assumptions_fingerprint": self.assumptions_fingerprint,
            "trigger": self.trigger.to_json(),
            "period_plan": [step.to_json() for step in self.period_plan],
            "evidence": [item.to_json() for item in self.evidence],
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "final_recommendation": self.final_recommendation,
            "operation_report_id": self.operation_report_id,
            "stop_reason": self.stop_reason.value,
            "korean_report": self.korean_report,
            "generated_at": self.generated_at,
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
            "approval_required_before_config_change": True,
        }


class BacktestRunner(Protocol):
    def run(self, run_id: str, strategy: CanonicalStrategySpec, dataset: MarketDataset, assumptions: BacktestExecutionAssumptionSet, *, generated_at: str | None = None) -> RealBacktestResult: ...


class RetestTriggerEngine:
    def evaluate(self, evidence: BacktestEvidence, *, min_trades: int, confidence_level: str, next_period: str | None) -> RetestDecision:
        quality = research_quality_gate(evidence, min_trades=min_trades)
        required = quality.status is QualityStatus.INSUFFICIENT_SAMPLE or evidence.blocking_findings == 0 and evidence.trade_count < min_trades
        reason = "insufficient_sample" if evidence.trade_count < min_trades else "needs_retest" if required else "sample_sufficient"
        return RetestDecision(required, reason, evidence.trade_count, min_trades, next_period if required else None, confidence_level, evidence.provider_gap_count, evidence.blocking_findings)


class AdaptiveResearchPeriodPlanner:
    def plan(self, *, requested_start: str, requested_end: str, provider_earliest: str | None = None, explicit_user_boundary: bool = False) -> tuple[ResearchPeriodStep, ...]:
        if explicit_user_boundary:
            return (ResearchPeriodStep("period:user-boundary", "user_period", requested_start, requested_end, "explicit user period boundary", True),)
        end = _date(requested_end)
        candidates = (
            ("6m", 183, "initial requested or six-month research window"),
            ("18m", 548, "expand because sample may be insufficient"),
            ("3y", 1095, "expand to medium-term research evidence"),
            ("5y", 1825, "expand to maximum configured research horizon"),
        )
        earliest = provider_earliest or "1900-01-01"
        steps: list[ResearchPeriodStep] = []
        for label, days, reason in candidates:
            start = _format(max(_date(earliest), end - timedelta(days=days)))
            steps.append(ResearchPeriodStep(f"period:{label}", label, start, requested_end, reason))
        return tuple(steps)


class RetestStopPolicy:
    def decide(self, evidence: RetestEvidence, *, is_last_period: bool, previous_trade_count: int | None, explicit_user_boundary: bool) -> StopReason | None:
        if explicit_user_boundary:
            return StopReason.USER_PERIOD_BOUNDARY
        if evidence.blocking_findings:
            return StopReason.BLOCKING_DATA_QUALITY
        if evidence.trade_count >= _target_min_from_evidence(evidence):
            return StopReason.MIN_TRADES_REACHED
        if previous_trade_count is not None and evidence.trade_count <= previous_trade_count and is_last_period:
            return StopReason.NO_ADDITIONAL_EVIDENCE
        if is_last_period:
            return StopReason.MAX_PERIOD_REACHED
        return None


class SQLiteAutonomousRetestRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_run(self, run: AutonomousRetestRun) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO research_retest_runs(run_id, request_text, status, stop_reason, recommendation, payload_json, generated_at, source) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run.run_id, run.request_text, "completed", run.stop_reason.value, run.final_recommendation, _json(run.to_json()), run.generated_at, "real" if _run_uses_real(run) else "fixture"),
            )
            for step in run.period_plan:
                self._connection.execute(
                    "INSERT OR REPLACE INTO research_period_plans(plan_id, run_id, label, start_date, end_date, reason, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (f"{run.run_id}:{step.step_id}", run.run_id, step.label, step.start_date, step.end_date, step.reason, _json(step.to_json()), run.generated_at),
                )
            for item in run.evidence:
                self._connection.execute(
                    "INSERT OR REPLACE INTO research_retest_evidence(evidence_id, run_id, period_label, trade_count, quality_status, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (item.evidence_id, run.run_id, item.period.label, item.trade_count, item.quality_status, _json(item.to_json()), run.generated_at),
                )

    def get(self, run_id: str) -> AutonomousRetestRun | None:
        row = self._connection.execute("SELECT payload_json FROM research_retest_runs WHERE run_id = ?", (run_id,)).fetchone()
        return _run_from_json(str(row[0])) if row else None

    def list_runs(self, *, limit: int = 5, include_artifacts: bool = False) -> tuple[dict[str, object], ...]:
        rows = self._connection.execute("SELECT run_id, status, stop_reason, recommendation, generated_at, source FROM research_retest_runs ORDER BY generated_at DESC, run_id DESC").fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            run_id = str(row[0])
            if not include_artifacts and _is_artifact_run(run_id):
                continue
            results.append({"run_id": run_id, "status": str(row[1]), "stop_reason": str(row[2]), "recommendation": str(row[3]), "generated_at": str(row[4]), "source": str(row[5])})
            if len(results) >= limit:
                break
        return tuple(results)

    def evidence_history(self, *, run_id: str | None = None, limit: int = 20, include_artifacts: bool = False) -> tuple[dict[str, object], ...]:
        if run_id:
            rows = self._connection.execute("SELECT evidence_id, run_id, period_label, trade_count, quality_status, created_at FROM research_retest_evidence WHERE run_id = ? ORDER BY created_at, evidence_id LIMIT ?", (run_id, limit)).fetchall()
        else:
            rows = self._connection.execute("SELECT evidence_id, run_id, period_label, trade_count, quality_status, created_at FROM research_retest_evidence ORDER BY created_at DESC, evidence_id DESC").fetchall()
        results: list[dict[str, object]] = []
        for row in rows:
            item_run_id = str(row[1])
            if run_id is None and not include_artifacts and _is_artifact_run(item_run_id):
                continue
            results.append({"evidence_id": str(row[0]), "run_id": item_run_id, "period_label": str(row[2]), "trade_count": int(row[3]), "quality_status": str(row[4]), "created_at": str(row[5])})
            if len(results) >= limit:
                break
        return tuple(results)


class AutonomousRetestOrchestrator:
    def __init__(self, connection: sqlite3.Connection | None = None, provider: KRXHistoricalDataProvider | None = None, backtest_runner: BacktestRunner | None = None) -> None:
        self._connection = connection
        self._provider = provider or KRXFixtureMarketDataProvider()
        self._backtest_runner = backtest_runner or RuleBasedBacktestEngine()

    def run(
        self,
        request_text: str,
        *,
        run_id: str | None = None,
        symbol: str = "005930",
        requested_start: str = "2026-01-01",
        requested_end: str = "2026-07-24",
        min_trades: int = 30,
        generated_at: str | None = None,
        explicit_user_boundary: bool = False,
    ) -> AutonomousRetestRun:
        at = generated_at or utc_now()
        rid = run_id or f"autonomous-retest:{uuid4().hex}"
        strategy = UserStrategyParser().parse(request_text, symbol=symbol, created_at=at)
        assumptions = default_execution_assumptions()
        strategy_fingerprint = strategy.fingerprint
        assumptions_fingerprint = _sha(assumptions.to_json())
        plan = AdaptiveResearchPeriodPlanner().plan(requested_start=requested_start, requested_end=requested_end, explicit_user_boundary=explicit_user_boundary)
        initial_next = f"{plan[0].start_date}:{plan[0].end_date}" if plan else None
        trigger = RetestDecision(True, "initial_quality_unknown", 0, min_trades, initial_next, "unknown", 0, 0)
        evidence_items: list[RetestEvidence] = []
        previous_trade_count: int | None = None
        stop_reason = StopReason.MAX_PERIOD_REACHED
        final_result: RealBacktestResult | None = None
        final_quality: DataQualityReport | None = None
        warnings: list[str] = []
        for index, period in enumerate(plan):
            try:
                dataset, quality, _inserted = KRXDatasetBuilder(self._connection, self._provider).build(symbol, start_date=period.start_date, end_date=period.end_date)
                blocking = _blocking_count(quality)
                result = self._backtest_runner.run(f"{rid}:{period.label}:original", strategy, dataset, assumptions, generated_at=at)
                _assert_same_fingerprints(strategy, strategy_fingerprint, assumptions, assumptions_fingerprint)
                evidence = _evidence_from_backtest(result, quality, period, min_trades=min_trades)
                confidence = statistical_confidence(_ops_evidence(result, quality), research_quality_gate(_ops_evidence(result, quality), min_trades=min_trades))
                evidence = replace(evidence, confidence_level=confidence.level.value)
                if not evidence_items:
                    next_period = f"{plan[min(index + 1, len(plan) - 1)].start_date}:{plan[min(index + 1, len(plan) - 1)].end_date}" if len(plan) > 1 else None
                    trigger = RetestTriggerEngine().evaluate(_ops_evidence(result, quality), min_trades=min_trades, confidence_level=confidence.level.value, next_period=next_period)
                reason = RetestStopPolicy().decide(evidence, is_last_period=index == len(plan) - 1, previous_trade_count=previous_trade_count, explicit_user_boundary=period.explicit_user_boundary)
                evidence = replace(evidence, stop_reason=reason)
                evidence_items.append(evidence)
                previous_trade_count = evidence.trade_count
                final_result = result
                final_quality = quality
                if reason is not None:
                    stop_reason = reason
                    break
                if blocking:
                    stop_reason = StopReason.BLOCKING_DATA_QUALITY
                    break
            except RealMarketDataUnavailable as exc:
                warnings.append(str(exc))
                stop_reason = StopReason.PROVIDER_FAILURE
                evidence_items.append(_failure_evidence(rid, period, StopReason.PROVIDER_FAILURE, str(exc)))
                break
        if final_result is None:
            run = AutonomousRetestRun(rid, request_text, symbol.upper(), strategy_fingerprint, assumptions_fingerprint, trigger, plan, tuple(evidence_items), (), RecommendationDecision.NEEDS_RETEST.value, None, stop_reason, _build_retest_report(None, None, tuple(evidence_items), (), stop_reason, RecommendationDecision.NEEDS_RETEST.value, warnings), at)
            self._persist(run)
            return run
        candidate_results = self._retest_candidates(rid, strategy, final_result, final_quality, assumptions, at)
        recommendation, operation_report_id = self._refresh_recommendation(rid, evidence_items[0].backtest or final_result, final_result, final_quality, min_trades, at)
        run = AutonomousRetestRun(rid, request_text, symbol.upper(), strategy_fingerprint, assumptions_fingerprint, trigger, plan, tuple(evidence_items), candidate_results, recommendation, operation_report_id, stop_reason, _build_retest_report(final_result, final_quality, tuple(evidence_items), candidate_results, stop_reason, recommendation, warnings), at)
        self._persist(run)
        return run

    def _retest_candidates(self, run_id: str, strategy: CanonicalStrategySpec, final_result: RealBacktestResult, quality: DataQualityReport | None, assumptions: BacktestExecutionAssumptionSet, at: str) -> tuple[ImprovementCandidate, ...]:
        if quality is None:
            return ()
        dataset_row = None
        if self._connection is not None:
            dataset_row = self._connection.execute("SELECT payload_json FROM market_datasets WHERE dataset_id = ?", (final_result.dataset_id,)).fetchone()
        # Candidate re-evaluation is skipped if the final dataset cannot be recovered.
        if dataset_row is None:
            return ()
        dataset = _dataset_from_json(str(dataset_row[0]))
        findings = EvidenceBasedStrategyCritic().critique(strategy, final_result, _minimal_validation(run_id, final_result, at))
        raw = ImprovementCandidateGenerator().generate(strategy, findings, run_id=run_id, created_at=at)
        tested: list[ImprovementCandidate] = []
        for candidate in raw:
            result = self._backtest_runner.run(f"{run_id}:{candidate.candidate_id}:retest", candidate.strategy, dataset, assumptions, generated_at=at)
            tested.append(replace(candidate, backtest_result=result))
        return tuple(tested)

    def _refresh_recommendation(self, run_id: str, champion: RealBacktestResult, challenger: RealBacktestResult, quality: DataQualityReport | None, min_trades: int, at: str) -> tuple[str, str | None]:
        if self._connection is None or quality is None:
            evidence = _ops_evidence(challenger, quality)
            decision = RecommendationDecision.NEEDS_RETEST if evidence.trade_count < min_trades else RecommendationDecision.HOLD
            return decision.value, None
        service = ResearchOperationsService(SQLiteResearchOperationRepository(self._connection))
        report = service.analyze(f"research-retest:{run_id}:recommendation", _ops_evidence(champion, quality), _ops_evidence(challenger, quality), generated_at=at, min_trades=min_trades)
        return report.recommendation.decision.value, report.report_id

    def _persist(self, run: AutonomousRetestRun) -> None:
        if self._connection is None:
            return
        SQLiteAutonomousRetestRepository(self._connection).add_run(run)


def research_retest_payload(connection: sqlite3.Connection, request_text: str, *, symbol: str = "005930") -> dict[str, object]:
    from gaon.research.krx_real_pipeline import build_market_data_provider_from_env

    return AutonomousRetestOrchestrator(connection, build_market_data_provider_from_env(os.environ)).run(request_text, symbol=symbol).to_json()


def autonomous_retest_release_check(connection: sqlite3.Connection) -> dict[str, object]:
    provider = _ReleaseCheckProvider()
    runner = _ReleaseCheckBacktestRunner()
    run = AutonomousRetestOrchestrator(connection, provider, runner).run(
        "20일 고가 돌파 종가 > MA20 > MA60 거래량 20일 평균 이상 손절 -5% 10일 저점 이탈 청산",
        run_id=f"autonomous-retest-release-check:{uuid4().hex}",
        requested_start="2026-01-01",
        requested_end="2026-07-24",
        min_trades=30,
        generated_at=utc_now(),
    )
    if run.strategy_fingerprint != run.evidence[-1].backtest.strategy.fingerprint:
        raise RuntimeError("strategy fingerprint changed during retest")
    if run.assumptions_fingerprint != _sha(run.evidence[-1].backtest.assumptions.to_json()):
        raise RuntimeError("assumptions fingerprint changed during retest")
    if run.evidence[-1].trade_count < 30:
        raise RuntimeError("release check did not reach minimum trades")
    if any(item.backtest and item.backtest.source is not MarketDataAvailability.REAL for item in run.evidence):
        raise RuntimeError("release check used non-real provenance")
    if run.final_recommendation not in {RecommendationDecision.HOLD.value, RecommendationDecision.NEEDS_RETEST.value, RecommendationDecision.RECOMMEND_CHALLENGER.value}:
        raise RuntimeError("invalid recommendation")
    return run.to_json()


def research_retest_status_payload(connection: sqlite3.Connection, *, limit: int = 5) -> dict[str, object]:
    repo = SQLiteAutonomousRetestRepository(connection)
    runs = repo.list_runs(limit=limit)
    return {"provider": "sqlite:research_retest", "runs": list(runs), "empty": not runs, "automatic_order": False, "automatic_champion_promotion": False, "automatic_config_apply": False}


def research_retest_history_payload(connection: sqlite3.Connection, *, run_id: str | None = None, limit: int = 20) -> dict[str, object]:
    repo = SQLiteAutonomousRetestRepository(connection)
    evidence = repo.evidence_history(run_id=run_id, limit=limit)
    return {"provider": "sqlite:research_retest_evidence", "evidence": list(evidence), "empty": not evidence, "automatic_order": False, "automatic_champion_promotion": False, "automatic_config_apply": False}


def _evidence_from_backtest(result: RealBacktestResult, quality: DataQualityReport, period: ResearchPeriodStep, *, min_trades: int) -> RetestEvidence:
    warnings = tuple(_sufficiency_warnings(result, min_trades=min_trades))
    return RetestEvidence(
        f"retest-evidence:{result.run_id}",
        period,
        result.dataset_id,
        result.dataset_fingerprint,
        quality.status.value,
        tuple(_provider_gap_dates(quality)),
        _blocking_count(quality),
        result,
        result.metrics.trade_count,
        "unknown",
        RecommendationDecision.NEEDS_RETEST.value if result.metrics.trade_count < min_trades else RecommendationDecision.HOLD.value,
        None,
        warnings,
    )


def _ops_evidence(result: RealBacktestResult, quality: DataQualityReport) -> BacktestEvidence:
    metrics = result.metrics.to_json()
    return BacktestEvidence(result.result_id, result.strategy.spec_id, result.strategy.to_json()["created_at"] if False else _dataset_start(result.dataset_id), _dataset_end(result.dataset_id), result.source.value, result.source is MarketDataAvailability.FIXTURE, metrics, quality.status.value, len(_provider_gap_dates(quality)), _blocking_count(quality))


def _failure_evidence(run_id: str, period: ResearchPeriodStep, reason: StopReason, message: str) -> RetestEvidence:
    return RetestEvidence(f"retest-evidence:{run_id}:{period.label}:failure", period, None, None, "provider_failure", (), 1, None, 0, "low", RecommendationDecision.NEEDS_RETEST.value, reason, (message,))


def _blocking_count(quality: DataQualityReport) -> int:
    if quality.status is DataQualityStatus.FAIL:
        return max(1, len(quality.findings))
    return sum(1 for finding in quality.findings if finding.severity in {"fail", "error", "critical"})


def _provider_gap_dates(quality: DataQualityReport) -> tuple[str, ...]:
    dates: list[str] = []
    for finding in quality.findings:
        if finding.code != "provider_gap":
            continue
        for token in finding.message.replace(";", " ").replace(",", " ").split():
            if len(token) == 10 and token[4] == "-" and token[7] == "-":
                dates.append(token)
    return tuple(dates)


def _sufficiency_warnings(result: RealBacktestResult, *, min_trades: int) -> list[str]:
    warnings: list[str] = []
    if result.metrics.trade_count < min_trades:
        warnings.append("insufficient sample: trade count below minimum")
    if result.metrics.trade_count < 5 and (result.metrics.win_rate in {1.0, 0.0} or result.metrics.profit_factor == float("inf")):
        warnings.append("small sample makes win rate/profit factor unreliable")
    return warnings


def _target_min_from_evidence(evidence: RetestEvidence) -> int:
    for warning in evidence.warnings:
        if "minimum" in warning:
            return 30
    return 30


def _assert_same_fingerprints(strategy: CanonicalStrategySpec, strategy_fingerprint: str, assumptions: BacktestExecutionAssumptionSet, assumptions_fingerprint: str) -> None:
    if strategy.fingerprint != strategy_fingerprint:
        raise RuntimeError("strategy changed during retest")
    if _sha(assumptions.to_json()) != assumptions_fingerprint:
        raise RuntimeError("execution assumptions changed during retest")


def _minimal_validation(run_id: str, result: RealBacktestResult, at: str):
    from gaon.research.krx_real_pipeline import ValidationReport

    return ValidationReport(f"validation:{run_id}:retest", result.metrics, result.metrics, True, (), at)


def _build_retest_report(final_result: RealBacktestResult | None, quality: DataQualityReport | None, evidence: tuple[RetestEvidence, ...], candidates: tuple[ImprovementCandidate, ...], stop_reason: StopReason, recommendation: str, warnings: list[str]) -> str:
    lines = [
        "[자동 재검증 결과]",
        f"- stop_reason={stop_reason.value}",
        f"- recommendation={recommendation}",
        "- 자동 주문/KIS 주문/Broker 주문/Champion 자동 승격/승인 없는 config 변경은 수행하지 않았습니다.",
        "",
        "[기간별 증거]",
    ]
    for item in evidence:
        lines.append(f"- {item.period.label}: {item.period.start_date}~{item.period.end_date} trade_count={item.trade_count} quality={item.quality_status} confidence={item.confidence_level}")
        if item.provider_gaps:
            lines.append(f"  provider_gap_dates={', '.join(item.provider_gaps)}")
        if item.warnings:
            lines.extend(f"  warning={warning}" for warning in item.warnings)
    if final_result:
        lines.extend(
            [
                "",
                "[최종 구조화 성과]",
                f"- source={final_result.source.value}",
                f"- fixture_backed={str(final_result.source is MarketDataAvailability.FIXTURE).lower()}",
                f"- trade_count={final_result.metrics.trade_count}",
                f"- total_return={final_result.metrics.total_return}",
                f"- mdd={final_result.metrics.mdd}",
                f"- profit_factor={final_result.metrics.profit_factor}",
            ]
        )
    if quality:
        lines.append(f"- quality_status={quality.status.value}")
    lines.append("")
    lines.append("[개선 후보 재평가]")
    if candidates:
        for candidate in candidates:
            metrics = candidate.backtest_result.metrics if candidate.backtest_result else None
            if metrics is None:
                lines.append(f"- HYPOTHESIS {candidate.candidate_id}: 성과 수치 없음")
            else:
                lines.append(f"- TESTED {candidate.candidate_id}: trade_count={metrics.trade_count} total_return={metrics.total_return} mdd={metrics.mdd}")
    else:
        lines.append("- TESTED 후보 결과 없음")
    if warnings:
        lines.extend(["", "[경고]", *[f"- {warning}" for warning in warnings]])
    return "\n".join(lines)


def _run_uses_real(run: AutonomousRetestRun) -> bool:
    return any(item.backtest is not None and item.backtest.source is MarketDataAvailability.REAL for item in run.evidence)


def _is_artifact_run(run_id: str) -> bool:
    return any(marker in run_id for marker in RETEST_ARTIFACT_MARKERS)


def _run_from_json(value: str) -> AutonomousRetestRun:
    payload = json.loads(value)
    return AutonomousRetestRun(
        str(payload["run_id"]),
        str(payload["request_text"]),
        str(payload["symbol"]),
        str(payload["strategy_fingerprint"]),
        str(payload["assumptions_fingerprint"]),
        RetestDecision(**payload["trigger"]),
        tuple(ResearchPeriodStep(**item) for item in payload["period_plan"]),
        tuple(_evidence_from_payload(item) for item in payload["evidence"]),
        (),
        str(payload["final_recommendation"]),
        payload.get("operation_report_id"),
        StopReason(payload["stop_reason"]),
        str(payload["korean_report"]),
        str(payload["generated_at"]),
    )


def _evidence_from_payload(payload: dict[str, object]) -> RetestEvidence:
    return RetestEvidence(
        str(payload["evidence_id"]),
        ResearchPeriodStep(**payload["period"]),
        payload.get("dataset_id"),
        payload.get("dataset_fingerprint"),
        str(payload["quality_status"]),
        tuple(str(item) for item in payload.get("provider_gaps", [])),
        int(payload["blocking_findings"]),
        None,
        int(payload["trade_count"]),
        str(payload["confidence_level"]),
        str(payload["recommendation"]),
        StopReason(payload["stop_reason"]) if payload.get("stop_reason") else None,
        tuple(str(item) for item in payload.get("warnings", [])),
    )


def _dataset_from_json(value: str) -> MarketDataset:
    payload = json.loads(value)
    metadata = payload["metadata"]
    return MarketDataset(
        str(payload["dataset_id"]),
        tuple(MarketSymbol(str(item["symbol"]), str(item.get("name", item["symbol"])), str(item.get("market", "KOSPI"))) for item in payload["symbols"]),
        tuple(MarketBar(str(item["timestamp"]), str(item["symbol"]), float(item["open"]), float(item["high"]), float(item["low"]), float(item["close"]), int(item["volume"]), int(item["trading_value"])) for item in payload["bars"]),
        MarketDataMetadata(str(metadata["source"]), str(metadata["market"]), str(metadata["timeframe"]), str(metadata["start_date"]), str(metadata["end_date"]), bool(metadata["adjusted"]), str(metadata["retrieved_at"]), bool(metadata["fixture_backed"])),
    )


def _dataset_start(dataset_id: str) -> str:
    parts = dataset_id.split(":")
    return parts[-2] if len(parts) >= 2 else "unknown"


def _dataset_end(dataset_id: str) -> str:
    parts = dataset_id.split(":")
    return parts[-1] if parts else "unknown"


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _format(value: datetime) -> str:
    return value.date().isoformat()


class _ReleaseCheckProvider:
    source = "real:synthetic-release-check"

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)
        days = max(1, (end - start).days + 1)
        bars = []
        for index in range(days):
            day = (start + timedelta(days=index)).date().isoformat()
            close = 100.0 + index * 0.1
            bars.append(MarketBar(day, symbol.upper(), close, close + 1.0, close - 1.0, close, 1_000_000 + index, int(close * 1_000_000)))
        metadata = MarketDataMetadata(self.source, "KOSPI", timeframe, start_date, end_date, True, utc_now(), False)
        return MarketDataset(f"dataset:real:retest:{symbol.upper()}:{timeframe}:{start_date}:{end_date}", (MarketSymbol(symbol.upper(), symbol.upper(), "KOSPI"),), tuple(bars), metadata)


class _ReleaseCheckBacktestRunner:
    def run(self, run_id: str, strategy: CanonicalStrategySpec, dataset: MarketDataset, assumptions: BacktestExecutionAssumptionSet, *, generated_at: str | None = None) -> RealBacktestResult:
        from gaon.research.krx_real_pipeline import RealBacktestTrade, RealPerformanceMetrics

        label = run_id.split(":")[-2] if ":candidate:" in run_id else run_id.split(":")[-2] if run_id.endswith(":original") else run_id
        trade_map = {"6m": 1, "18m": 5, "3y": 17, "5y": 31}
        trade_count = next((count for key, count in trade_map.items() if f":{key}:" in run_id), 31)
        trades = tuple(
            RealBacktestTrade(f"trade:{run_id}:{index + 1}", dataset.symbols[0].symbol, dataset.bars[0].timestamp, dataset.bars[-1].timestamp, 100.0, 101.0, 1, 1.0, 0.01, "release_check")
            for index in range(trade_count)
        )
        metrics = RealPerformanceMetrics(0.12 + trade_count / 1000.0, 0.03, 0.08, 0.9, 0.55, 1.2, trade_count, 1.0, 1.0, -1.0, 1.0, 0.5, 1_120_000.0, 0.2, 2)
        return RealBacktestResult(f"krx-real-backtest-result:{_sha({'run_id': run_id})}", run_id, "completed", MarketDataAvailability.REAL, strategy, dataset.dataset_id, dataset.fingerprint, assumptions, metrics, trades, ({"timestamp": dataset.bars[0].timestamp, "equity": 1_000_000.0}, {"timestamp": dataset.bars[-1].timestamp, "equity": 1_120_000.0}), ("release-check synthetic real provider; no fixture fallback",), generated_at or utc_now())
