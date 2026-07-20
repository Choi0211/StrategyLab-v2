"""Bounded autonomous strategy research workflow.

This module researches strategy ideas, not live trading actions. It creates
challengers, runs deterministic fixture backtests, validates results, compares
against the current champion, and returns a recommendation that still requires
human approval before any promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
import json
import re
import sqlite3

from gaon.adapters.backtest import BacktestDatasetRef, BacktestMetrics, BacktestPeriod, BacktestResult, BacktestStatus, BacktestStrategyRef, BacktestTradeSummary, SQLiteBacktestRepository
from gaon.adapters.champion_registry import SQLiteChampionRegistryRepository
from gaon.adapters.validation import SQLiteValidationRepository, StrategyValidationEngine, ValidationPolicy, ValidationStatus, build_validation_request
from gaon.runtime.external_research import ExternalResearchTool


ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class ResearchPlanStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    APPROVAL_REQUIRED = "approval_required"


class ResearchRecommendation(str, Enum):
    RECOMMEND = "recommend"
    REJECT = "reject"
    NEEDS_MORE_VALIDATION = "needs_more_validation"
    DATA_UNAVAILABLE = "data_unavailable"


@dataclass(frozen=True)
class StrategyResearchPlan:
    plan_id: str
    request_text: str
    steps: tuple[str, ...]
    status: ResearchPlanStatus
    created_at: str

    def __post_init__(self) -> None:
        _validate_utc(self.created_at)
        if not self.plan_id or not self.request_text or not self.steps:
            raise ValueError("research plan requires id, request, and steps")

    def to_json(self) -> dict[str, object]:
        return {"plan_id": self.plan_id, "request_text": self.request_text, "steps": list(self.steps), "status": self.status.value, "created_at": self.created_at}


@dataclass(frozen=True)
class StrategyExperiment:
    experiment_id: str
    parent_strategy: str
    hypothesis: str
    parameter_changes: dict[str, float | int | str | bool]
    dataset: str
    period: str
    created_at: str
    result_ref: str | None = None

    def __post_init__(self) -> None:
        _validate_utc(self.created_at)
        if not self.experiment_id or not self.parent_strategy or not self.hypothesis:
            raise ValueError("strategy experiment requires id, parent strategy, and hypothesis")

    def to_json(self) -> dict[str, object]:
        return {
            "experiment_id": self.experiment_id,
            "parent_strategy": self.parent_strategy,
            "hypothesis": self.hypothesis,
            "parameter_changes": dict(sorted(self.parameter_changes.items())),
            "dataset": self.dataset,
            "period": self.period,
            "created_at": self.created_at,
            "result_ref": self.result_ref,
        }


@dataclass(frozen=True)
class StrategyResearchReport:
    report_id: str
    plan_id: str
    recommendation: ResearchRecommendation
    research_goal: str
    data_sources: tuple[str, ...]
    external_sources: tuple[str, ...]
    strategy_hypothesis: str
    parameter_changes: dict[str, float | int | str | bool]
    backtest_result_id: str | None
    validation_id: str | None
    champion_comparison: dict[str, object]
    overfitting_risk: str
    limitations: tuple[str, ...]
    generated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "plan_id": self.plan_id,
            "recommendation": self.recommendation.value,
            "research_goal": self.research_goal,
            "data_sources": list(self.data_sources),
            "external_sources": list(self.external_sources),
            "strategy_hypothesis": self.strategy_hypothesis,
            "parameter_changes": dict(sorted(self.parameter_changes.items())),
            "backtest_result_id": self.backtest_result_id,
            "validation_id": self.validation_id,
            "champion_comparison": self.champion_comparison,
            "overfitting_risk": self.overfitting_risk,
            "limitations": list(self.limitations),
            "generated_at": self.generated_at,
        }


class SQLiteStrategyResearchRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put_plan(self, plan: StrategyResearchPlan) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO strategy_research_plans(plan_id, status, request_text, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(plan_id) DO UPDATE SET status=excluded.status, payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (plan.plan_id, plan.status.value, plan.request_text, _dumps(plan.to_json()), plan.created_at, plan.created_at),
            )

    def put_experiment(self, experiment: StrategyExperiment) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO strategy_research_experiments(experiment_id, plan_id, parent_strategy, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(experiment_id) DO UPDATE SET payload_json=excluded.payload_json, updated_at=excluded.updated_at",
                (experiment.experiment_id, experiment.experiment_id.split(":experiment:", 1)[0], experiment.parent_strategy, _dumps(experiment.to_json()), experiment.created_at, experiment.created_at),
            )

    def put_report(self, report: StrategyResearchReport) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO strategy_research_reports(report_id, plan_id, recommendation, payload_json, generated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(report_id) DO UPDATE SET recommendation=excluded.recommendation, payload_json=excluded.payload_json, generated_at=excluded.generated_at",
                (report.report_id, report.plan_id, report.recommendation.value, _dumps(report.to_json()), report.generated_at),
            )

    def list_reports(self) -> tuple[StrategyResearchReport, ...]:
        rows = self._connection.execute("SELECT payload_json FROM strategy_research_reports ORDER BY generated_at, report_id").fetchall()
        return tuple(_report_from_json(json.loads(str(row[0]))) for row in rows)


class StrategyResearchPlanner:
    def create_plan(self, request_text: str, *, created_at: str, plan_id: str = "strategy-research-plan") -> StrategyResearchPlan:
        steps = (
            "read_current_champion",
            "collect_external_context",
            "create_strategy_hypothesis",
            "define_challenger_experiments",
            "run_bounded_backtests",
            "validate_results",
            "compare_with_champion",
            "write_research_report",
        )
        return StrategyResearchPlan(plan_id, request_text, steps, ResearchPlanStatus.CREATED, created_at)


class StrategyResearchOrchestrator:
    def __init__(self, connection: sqlite3.Connection, *, repository: SQLiteStrategyResearchRepository | None = None, external_tool: ExternalResearchTool | None = None, max_experiments: int = 3) -> None:
        if max_experiments < 1 or max_experiments > 10:
            raise ValueError("max_experiments must be bounded")
        self._connection = connection
        self._repository = repository or SQLiteStrategyResearchRepository(connection)
        self._external = external_tool or ExternalResearchTool()
        self._max_experiments = max_experiments

    def run(self, request_text: str, *, run_id: str, actor_ref: str, requested_at: str, timeframe: str = "daily") -> StrategyResearchReport:
        _validate_utc(requested_at)
        plan = StrategyResearchPlanner().create_plan(request_text, created_at=requested_at, plan_id=f"{run_id}:plan")
        self._repository.put_plan(plan)
        if timeframe in {"1m", "3m", "5m", "intraday"}:
            report = self._data_unavailable(plan, run_id, request_text, requested_at, timeframe)
            self._repository.put_report(report)
            return report
        search = self._external.search(request_text, max_results=3, retrieved_at=requested_at)
        experiment = self._experiment(plan, run_id, requested_at)
        result = self._backtest(experiment, requested_at)
        SQLiteBacktestRepository(self._connection).add_result(result)
        experiment = StrategyExperiment(experiment.experiment_id, experiment.parent_strategy, experiment.hypothesis, experiment.parameter_changes, experiment.dataset, experiment.period, experiment.created_at, result.result_id)
        self._repository.put_experiment(experiment)
        validation = StrategyValidationEngine(ValidationPolicy(min_trade_count=10, min_profit_factor=1.1), repository=SQLiteValidationRepository(self._connection)).validate(
            build_validation_request(f"{run_id}:validation", (result,), actor_ref=actor_ref, requested_at=requested_at),
            (result,),
            generated_at=requested_at,
        )
        comparison = self._compare_with_champion(result)
        recommendation = _recommend(validation.overall_status, comparison)
        report = StrategyResearchReport(
            report_id=f"{run_id}:report",
            plan_id=plan.plan_id,
            recommendation=recommendation,
            research_goal=request_text,
            data_sources=("daily_fixture",),
            external_sources=tuple(str(item["url"]) for item in search["results"]),  # type: ignore[index]
            strategy_hypothesis=experiment.hypothesis,
            parameter_changes=experiment.parameter_changes,
            backtest_result_id=result.result_id,
            validation_id=validation.validation_id,
            champion_comparison=comparison,
            overfitting_risk="medium" if result.metrics.trade_count and result.metrics.trade_count < 50 else "low",
            limitations=("fixture backtest only", "no automatic champion promotion", "external provider defaults to fixture unless configured"),
            generated_at=requested_at,
        )
        self._repository.put_report(report)
        self._repository.put_plan(StrategyResearchPlan(plan.plan_id, plan.request_text, plan.steps, ResearchPlanStatus.COMPLETED, plan.created_at))
        return report

    def _experiment(self, plan: StrategyResearchPlan, run_id: str, at: str) -> StrategyExperiment:
        return StrategyExperiment(
            experiment_id=f"{run_id}:experiment:breakout-volume",
            parent_strategy="turtle_v5",
            hypothesis="Volume confirmation may reduce false breakouts without changing the champion.",
            parameter_changes={"breakout_period": 20, "volume_filter": "above_20d_average", "risk_pct": 0.02},
            dataset="daily_fixture",
            period="2025-01-01/2025-12-31",
            created_at=at,
        )

    def _backtest(self, experiment: StrategyExperiment, at: str) -> BacktestResult:
        fingerprint = f"fp-{_safe_id(experiment.experiment_id)}"
        return BacktestResult(
            result_id=f"{experiment.experiment_id}:backtest",
            request_id=f"{experiment.experiment_id}:request",
            status=BacktestStatus.COMPLETED,
            fingerprint=fingerprint,
            strategy=BacktestStrategyRef("turtle_v5", "v1"),
            dataset=BacktestDatasetRef("daily_fixture", "v1"),
            period=BacktestPeriod("2025-01-01", "2025-12-31"),
            metrics=BacktestMetrics(total_return=0.16, annualized_return=0.16, max_drawdown=-0.08, win_rate=0.54, profit_factor=1.45, sharpe_ratio=1.2, trade_count=64, average_trade_return=0.0025, exposure=0.45),
            trade_summary=BacktestTradeSummary(64, winning_trades=35, losing_trades=29, gross_profit=0.22, gross_loss=-0.12),
            raw_engine_version="v1-fixture",
            parameters=experiment.parameter_changes,
            warnings=("commission=0.00015; tax/slippage modeled as fixture assumptions",),
            errors=(),
            generated_at=at,
            duration_ms=1,
            reproducibility={"fingerprint": fingerprint, "look_ahead_bias": "blocked_by_static_fixture", "survivorship_bias": "documented_limit"},
        )

    def _compare_with_champion(self, result: BacktestResult) -> dict[str, object]:
        active = SQLiteChampionRegistryRepository(self._connection).get_active()
        baseline_return = 0.08
        baseline_profit_factor = 1.2
        if active is not None:
            try:
                champion = SQLiteBacktestRepository(self._connection).get_result(active.source_backtest_id)
                baseline_return = champion.metrics.total_return or baseline_return
                baseline_profit_factor = champion.metrics.profit_factor or baseline_profit_factor
            except KeyError:
                pass
        total_return = result.metrics.total_return or 0.0
        profit_factor = result.metrics.profit_factor or 0.0
        return {
            "champion_total_return": baseline_return,
            "challenger_total_return": total_return,
            "return_delta": round(total_return - baseline_return, 6),
            "champion_profit_factor": baseline_profit_factor,
            "challenger_profit_factor": profit_factor,
            "risk_adjusted_preferred": profit_factor >= baseline_profit_factor and (result.metrics.max_drawdown or -1.0) >= -0.20,
            "automatic_promotion": False,
        }

    def _data_unavailable(self, plan: StrategyResearchPlan, run_id: str, request_text: str, at: str, timeframe: str) -> StrategyResearchReport:
        return StrategyResearchReport(
            f"{run_id}:report",
            plan.plan_id,
            ResearchRecommendation.DATA_UNAVAILABLE,
            request_text,
            (timeframe,),
            (),
            "Intraday strategy research requires verified minute data.",
            {},
            None,
            None,
            {"automatic_promotion": False},
            "unknown",
            ("intraday data unavailable", "no fabricated backtest result was generated"),
            at,
        )


def _recommend(status: ValidationStatus, comparison: dict[str, object]) -> ResearchRecommendation:
    if status is ValidationStatus.FAIL:
        return ResearchRecommendation.REJECT
    if status is ValidationStatus.REVIEW:
        return ResearchRecommendation.NEEDS_MORE_VALIDATION
    return ResearchRecommendation.RECOMMEND if comparison.get("risk_adjusted_preferred") is True else ResearchRecommendation.NEEDS_MORE_VALIDATION


def _report_from_json(payload: dict[str, object]) -> StrategyResearchReport:
    return StrategyResearchReport(
        str(payload["report_id"]),
        str(payload["plan_id"]),
        ResearchRecommendation(str(payload["recommendation"])),
        str(payload["research_goal"]),
        tuple(str(item) for item in payload["data_sources"]),
        tuple(str(item) for item in payload["external_sources"]),
        str(payload["strategy_hypothesis"]),
        dict(payload["parameter_changes"]),  # type: ignore[arg-type]
        str(payload["backtest_result_id"]) if payload.get("backtest_result_id") else None,
        str(payload["validation_id"]) if payload.get("validation_id") else None,
        dict(payload["champion_comparison"]),  # type: ignore[arg-type]
        str(payload["overfitting_risk"]),
        tuple(str(item) for item in payload["limitations"]),
        str(payload["generated_at"]),
    )


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "-", value)[:96]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
