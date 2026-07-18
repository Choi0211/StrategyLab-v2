"""Gaon v5 release-candidate pipeline orchestration.

The pipeline stitches existing StrategyLab components together for deterministic
RC verification. It preserves approval boundaries and uses fake/bounded adapters
in automated tests.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
import re
import sqlite3
from typing import Any

from gaon.adapters.backtest import BacktestDatasetRef, BacktestMetrics, BacktestPeriod, BacktestResult, BacktestStatus, BacktestStrategyRef, BacktestTradeSummary, SQLiteBacktestRepository
from gaon.adapters.champion import ChampionChallengerDecision, ChampionChallengerEvaluationEngine, ChampionChallengerPolicy, SQLiteChampionChallengerRepository, build_champion_challenger_request
from gaon.adapters.champion_registry import ChampionRegistryService, SQLiteChampionRegistryRepository
from gaon.adapters.paper_forward import PaperTradingForwardTestService, SQLitePaperTradingSessionRepository
from gaon.adapters.paper_revalidation import PaperRevalidationEngine, PaperRevalidationPolicy, PaperRevalidationStatus, SQLitePaperRevalidationRepository, build_paper_revalidation_request
from gaon.adapters.strategy_deployment import FakeStrategyDeploymentAdapter, SQLiteStrategyDeploymentRepository, StrategyDeploymentAdapter, StrategyDeploymentService, StrategyDeploymentStatus, build_strategy_deployment_request
from gaon.adapters.strategy_handoff import SQLiteStrategyHandoffRepository, StrategyHandoffService, StrategyHandoffStatus, build_strategy_handoff_request
from gaon.adapters.trading import SQLiteTradingRepository
from gaon.adapters.validation import SQLiteValidationRepository, StrategyValidationEngine, ValidationPolicy, ValidationStatus, build_validation_request
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.metrics import MetricsCollector


ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class GaonV5PipelineStage(str, Enum):
    RESEARCH = "research"
    BACKTEST = "backtest"
    VALIDATION = "validation"
    CHAMPION_EVALUATION = "champion_evaluation"
    PROMOTION_APPROVAL = "promotion_approval"
    CHAMPION_ACTIVATION = "champion_activation"
    PAPER_FORWARD_TEST = "paper_forward_test"
    PAPER_REVALIDATION = "paper_revalidation"
    HANDOFF_PACKAGE = "handoff_package"
    DEPLOYMENT_APPROVAL = "deployment_approval"
    DEPLOYMENT = "deployment"
    VERIFICATION = "verification"
    COMPLETED = "completed"


class GaonV5PipelineStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass(frozen=True)
class GaonV5PipelineRequest:
    run_id: str
    correlation_id: str
    actor_ref: str
    requested_at: str
    approve_promotion: bool = False
    approve_deployment: bool = False
    scenario: str = "success"

    def __post_init__(self) -> None:
        if not self.run_id or not self.correlation_id or not self.actor_ref:
            raise ValueError("v5 pipeline request requires run, correlation, and actor")
        if ISO_UTC.fullmatch(self.requested_at) is None:
            raise ValueError("timestamp must use ISO 8601 UTC format")


@dataclass(frozen=True)
class GaonV5PipelineRun:
    run_id: str
    correlation_id: str
    status: GaonV5PipelineStatus
    current_stage: GaonV5PipelineStage
    completed_stages: tuple[GaonV5PipelineStage, ...]
    source_refs: dict[str, str]
    failure_stage: GaonV5PipelineStage | None
    approval_waiting_stage: GaonV5PipelineStage | None
    message: str
    created_at: str
    updated_at: str

    def to_json(self) -> str:
        return _dumps(
            {
                "run_id": self.run_id,
                "correlation_id": self.correlation_id,
                "status": self.status.value,
                "current_stage": self.current_stage.value,
                "completed_stages": [stage.value for stage in self.completed_stages],
                "source_refs": dict(sorted(self.source_refs.items())),
                "failure_stage": self.failure_stage.value if self.failure_stage else None,
                "approval_waiting_stage": self.approval_waiting_stage.value if self.approval_waiting_stage else None,
                "message": self.message,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )


@dataclass(frozen=True)
class GaonV5PipelineReport:
    run_id: str
    status: GaonV5PipelineStatus
    current_stage: GaonV5PipelineStage
    completed_stages: tuple[GaonV5PipelineStage, ...]
    source_refs: dict[str, str]
    message: str

    def to_json(self) -> str:
        return _dumps({"run_id": self.run_id, "status": self.status.value, "current_stage": self.current_stage.value, "completed_stages": [stage.value for stage in self.completed_stages], "source_refs": dict(sorted(self.source_refs.items())), "message": self.message})


class SQLiteGaonV5PipelineRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put_run(self, run: GaonV5PipelineRun) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO gaon_v5_pipeline_runs(run_id, correlation_id, status, current_stage, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, current_stage = excluded.current_stage, payload_json = excluded.payload_json, updated_at = excluded.updated_at",
                (run.run_id, run.correlation_id, run.status.value, run.current_stage.value, run.to_json(), run.created_at, run.updated_at),
            )

    def get_run(self, run_id: str) -> GaonV5PipelineRun:
        row = self._connection.execute("SELECT payload_json FROM gaon_v5_pipeline_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return run_from_json(str(row[0]))

    def list_runs(self) -> tuple[GaonV5PipelineRun, ...]:
        rows = self._connection.execute("SELECT payload_json FROM gaon_v5_pipeline_runs ORDER BY created_at, run_id").fetchall()
        return tuple(run_from_json(str(row[0])) for row in rows)

    def checkpoint(self, run: GaonV5PipelineRun, stage: GaonV5PipelineStage) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO gaon_v5_pipeline_checkpoints(checkpoint_id, run_id, stage, status, source_refs_json, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"checkpoint:{run.run_id}:{stage.value}", run.run_id, stage.value, run.status.value, _dumps(run.source_refs), run.to_json(), run.updated_at),
            )


class GaonV5PipelineOrchestrator:
    def __init__(self, connection: sqlite3.Connection, *, adapter: StrategyDeploymentAdapter | None = None, event_store: SQLiteEventStore | None = None, metrics: MetricsCollector | None = None) -> None:
        self._connection = connection
        self._repository = SQLiteGaonV5PipelineRepository(connection)
        self._event_store = event_store
        self._metrics = metrics
        self._adapter = adapter or FakeStrategyDeploymentAdapter()

    def run_demo(self, request: GaonV5PipelineRequest) -> GaonV5PipelineReport:
        existing = self._load_or_create(request)
        if existing.status == GaonV5PipelineStatus.COMPLETED:
            return _report(existing)
        if existing.status == GaonV5PipelineStatus.WAITING_FOR_APPROVAL:
            if existing.approval_waiting_stage == GaonV5PipelineStage.PROMOTION_APPROVAL and not request.approve_promotion:
                return _report(existing)
            if existing.approval_waiting_stage == GaonV5PipelineStage.DEPLOYMENT_APPROVAL and not request.approve_deployment:
                return _report(existing)
        run = replace(existing, status=GaonV5PipelineStatus.RUNNING, updated_at=request.requested_at)
        self._record("GaonV5PipelineStarted", run, request.actor_ref)
        try:
            run = self._research(run, request)
            active_before = SQLiteChampionRegistryRepository(self._connection).get_active()
            active_backtest = None
            if active_before is not None:
                try:
                    active_backtest = SQLiteBacktestRepository(self._connection).get_result(active_before.source_backtest_id)
                except KeyError:
                    active_backtest = None
            champion, challenger = _fixture_backtests(request.scenario, request.requested_at, request.run_id, active_backtest)
            SQLiteBacktestRepository(self._connection).add_result(champion)
            SQLiteBacktestRepository(self._connection).add_result(challenger)
            run = self._complete(run, GaonV5PipelineStage.BACKTEST, request.requested_at, {"champion_backtest_id": champion.result_id, "challenger_backtest_id": challenger.result_id})

            validation_id = f"{request.run_id}:validation"
            validation = StrategyValidationEngine(_validation_policy(request.scenario), repository=SQLiteValidationRepository(self._connection), event_store=self._event_store, metrics=self._metrics).validate(build_validation_request(validation_id, (challenger,), actor_ref=request.actor_ref, requested_at=request.requested_at), (challenger,), generated_at=request.requested_at)
            if validation.overall_status != ValidationStatus.PASS:
                return self._blocked(run, GaonV5PipelineStage.VALIDATION, request, "validation did not pass", {"validation_id": validation.validation_id})
            run = self._complete(run, GaonV5PipelineStage.VALIDATION, request.requested_at, {"validation_id": validation.validation_id})

            registry_service = ChampionRegistryService(SQLiteChampionRegistryRepository(self._connection), SQLiteChampionChallengerRepository(self._connection), event_store=self._event_store, metrics=self._metrics)
            if SQLiteChampionRegistryRepository(self._connection).get_active() is None:
                registry_service.bootstrap(strategy_ref=champion.strategy.strategy_id, fingerprint=champion.fingerprint, backtest_id=champion.result_id, actor_ref=request.actor_ref, activated_at=request.requested_at)
            evaluation_id = f"{request.run_id}:evaluation"
            evaluation = ChampionChallengerEvaluationEngine(_champion_policy(request.scenario), repository=SQLiteChampionChallengerRepository(self._connection), event_store=self._event_store, metrics=self._metrics).evaluate(build_champion_challenger_request(evaluation_id, champion=champion, challenger=challenger, validation=validation, actor_ref=request.actor_ref, requested_at=request.requested_at), champion=champion, challenger=challenger, validation=validation, generated_at=request.requested_at)
            if evaluation.decision != ChampionChallengerDecision.PROMOTION_CANDIDATE:
                return self._blocked(run, GaonV5PipelineStage.CHAMPION_EVALUATION, request, "Champion evaluation did not create a promotion candidate", {"evaluation_id": evaluation.evaluation_id})
            run = self._complete(run, GaonV5PipelineStage.CHAMPION_EVALUATION, request.requested_at, {"evaluation_id": evaluation.evaluation_id})

            promotion = registry_service.request_promotion(f"{request.run_id}:promotion", evaluation.evaluation_id, actor_ref=request.actor_ref, requested_at=request.requested_at)
            if request.scenario == "promotion_rejected":
                registry_service.reject(promotion.promotion_id, actor_ref=request.actor_ref, decided_at=request.requested_at)
                return self._blocked(run, GaonV5PipelineStage.PROMOTION_APPROVAL, request, "promotion rejected", {"promotion_id": promotion.promotion_id})
            if not request.approve_promotion:
                return self._waiting(run, GaonV5PipelineStage.PROMOTION_APPROVAL, request, {"promotion_id": promotion.promotion_id})
            active = registry_service.approve(promotion.promotion_id, actor_ref=request.actor_ref, decided_at=request.requested_at)
            run = self._complete(run, GaonV5PipelineStage.PROMOTION_APPROVAL, request.requested_at, {"promotion_id": promotion.promotion_id})
            run = self._complete(run, GaonV5PipelineStage.CHAMPION_ACTIVATION, request.requested_at, {"champion_version_id": active.active_version_id})

            paper = PaperTradingForwardTestService(SQLitePaperTradingSessionRepository(self._connection), SQLiteChampionRegistryRepository(self._connection), trading_repository=SQLiteTradingRepository(self._connection), event_store=self._event_store, metrics=self._metrics)
            session = paper.create_session(f"{request.run_id}:paper-session", actor_ref=request.actor_ref, created_at=request.requested_at)
            paper.start(session.session_id, actor_ref=request.actor_ref, at=request.requested_at)
            for index in range(20):
                paper.simulate_order(session.session_id, symbol=f"PAPER{index}", quantity=1, price=100 + index, side="buy", actor_ref=request.actor_ref, at=request.requested_at)
            session = paper.complete(session.session_id, actor_ref=request.actor_ref, at=request.requested_at)
            summary = SQLitePaperTradingSessionRepository(self._connection).get_summary(session.session_id)
            summary = replace(summary, realized_paper_pnl=0.0, unrealized_paper_pnl=0.0, max_paper_drawdown=0.01, exposure=0.5)
            if request.scenario == "paper_kill":
                summary = replace(summary, failed_simulated_orders=1, errors=("fixture critical paper failure",))
            run = self._complete(run, GaonV5PipelineStage.PAPER_FORWARD_TEST, request.requested_at, {"paper_session_id": session.session_id})

            revalidation = PaperRevalidationEngine(_paper_policy(request.scenario), repository=SQLitePaperRevalidationRepository(self._connection), event_store=self._event_store, metrics=self._metrics).revalidate(build_paper_revalidation_request(f"{request.run_id}:paper-revalidation", session=session, actor_ref=request.actor_ref, requested_at=request.requested_at), active=active, session=session, summary=summary, generated_at=request.requested_at)
            if revalidation.status != PaperRevalidationStatus.LIVE_ELIGIBLE:
                return self._blocked(run, GaonV5PipelineStage.PAPER_REVALIDATION, request, f"paper revalidation {revalidation.status.value}", {"paper_revalidation_id": revalidation.revalidation_id})
            run = self._complete(run, GaonV5PipelineStage.PAPER_REVALIDATION, request.requested_at, {"paper_revalidation_id": revalidation.revalidation_id})

            handoff_service = StrategyHandoffService(SQLiteStrategyHandoffRepository(self._connection), SQLiteChampionRegistryRepository(self._connection), SQLitePaperRevalidationRepository(self._connection), SQLiteBacktestRepository(self._connection), event_store=self._event_store, metrics=self._metrics)
            package = handoff_service.create(build_strategy_handoff_request(f"{request.run_id}:handoff", revalidation_id=revalidation.revalidation_id, actor_ref=request.actor_ref, requested_at=request.requested_at))
            run = self._complete(run, GaonV5PipelineStage.HANDOFF_PACKAGE, request.requested_at, {"handoff_package_id": package.package_id})
            if not request.approve_deployment:
                return self._waiting(run, GaonV5PipelineStage.DEPLOYMENT_APPROVAL, request, {"handoff_package_id": package.package_id})
            package = handoff_service.approve(package.package_id, approver_ref=request.actor_ref, decided_at=request.requested_at)
            if package.status != StrategyHandoffStatus.APPROVED_FOR_DEPLOYMENT:
                return self._blocked(run, GaonV5PipelineStage.DEPLOYMENT_APPROVAL, request, "deployment approval failed", {"handoff_package_id": package.package_id})
            run = self._complete(run, GaonV5PipelineStage.DEPLOYMENT_APPROVAL, request.requested_at, {"handoff_package_id": package.package_id})

            deployment = StrategyDeploymentService(SQLiteStrategyDeploymentRepository(self._connection), SQLiteStrategyHandoffRepository(self._connection), SQLiteChampionRegistryRepository(self._connection), self._adapter, event_store=self._event_store, metrics=self._metrics)
            plan = deployment.plan(build_strategy_deployment_request(f"{request.run_id}:deployment", package_id=package.package_id, actor_ref=request.actor_ref, requested_at=request.requested_at))
            deployed = deployment.run(plan.plan_id, actor_ref=request.actor_ref, at=request.requested_at)
            if deployed.status != StrategyDeploymentStatus.SUCCEEDED:
                return self._blocked(run, GaonV5PipelineStage.DEPLOYMENT, request, f"deployment {deployed.status.value}", {"deployment_run_id": deployed.run_id})
            run = self._complete(run, GaonV5PipelineStage.DEPLOYMENT, request.requested_at, {"deployment_run_id": deployed.run_id})
            run = self._complete(run, GaonV5PipelineStage.VERIFICATION, request.requested_at, {"deployment_run_id": deployed.run_id})
            run = replace(run, status=GaonV5PipelineStatus.COMPLETED, current_stage=GaonV5PipelineStage.COMPLETED, completed_stages=_append_stage(run.completed_stages, GaonV5PipelineStage.COMPLETED), message="Gaon v5 RC pipeline completed", updated_at=request.requested_at)
            self._persist(run, GaonV5PipelineStage.COMPLETED)
            self._record("GaonV5PipelineCompleted", run, request.actor_ref)
            _increment(self._metrics, "gaon_v5_pipeline_completed_total")
            return _report(run)
        except Exception as exc:  # noqa: BLE001 - RC pipeline failures must be persisted.
            failed = replace(run, status=GaonV5PipelineStatus.FAILED, failure_stage=run.current_stage, message=exc.__class__.__name__, updated_at=request.requested_at)
            self._persist(failed, run.current_stage)
            self._record("GaonV5PipelineFailed", failed, request.actor_ref)
            _increment(self._metrics, "gaon_v5_pipeline_failed_total")
            return _report(failed)

    def _load_or_create(self, request: GaonV5PipelineRequest) -> GaonV5PipelineRun:
        try:
            return self._repository.get_run(request.run_id)
        except KeyError:
            run = GaonV5PipelineRun(request.run_id, request.correlation_id, GaonV5PipelineStatus.CREATED, GaonV5PipelineStage.RESEARCH, (), {}, None, None, "created", request.requested_at, request.requested_at)
            self._persist(run, GaonV5PipelineStage.RESEARCH)
            _increment(self._metrics, "gaon_v5_pipeline_runs_total")
            return run

    def _research(self, run: GaonV5PipelineRun, request: GaonV5PipelineRequest) -> GaonV5PipelineRun:
        return self._complete(run, GaonV5PipelineStage.RESEARCH, request.requested_at, {"research_fixture": "v5-deterministic"})

    def _complete(self, run: GaonV5PipelineRun, stage: GaonV5PipelineStage, at: str, refs: dict[str, str]) -> GaonV5PipelineRun:
        if stage in run.completed_stages:
            return run
        updated = replace(run, current_stage=stage, completed_stages=_append_stage(run.completed_stages, stage), source_refs=run.source_refs | refs, message=f"{stage.value} completed", updated_at=at)
        self._persist(updated, stage)
        self._record("GaonV5PipelineStageCompleted", updated, "actor:redacted")
        return updated

    def _waiting(self, run: GaonV5PipelineRun, stage: GaonV5PipelineStage, request: GaonV5PipelineRequest, refs: dict[str, str]) -> GaonV5PipelineReport:
        waiting = replace(run, status=GaonV5PipelineStatus.WAITING_FOR_APPROVAL, current_stage=stage, approval_waiting_stage=stage, source_refs=run.source_refs | refs, message=f"waiting for explicit approval at {stage.value}", updated_at=request.requested_at)
        self._persist(waiting, stage)
        self._record("GaonV5PipelineWaitingForApproval", waiting, request.actor_ref)
        _increment(self._metrics, "gaon_v5_pipeline_waiting_approval_total")
        return _report(waiting)

    def _blocked(self, run: GaonV5PipelineRun, stage: GaonV5PipelineStage, request: GaonV5PipelineRequest, message: str, refs: dict[str, str]) -> GaonV5PipelineReport:
        blocked = replace(run, status=GaonV5PipelineStatus.BLOCKED, current_stage=stage, failure_stage=stage, source_refs=run.source_refs | refs, message=message, updated_at=request.requested_at)
        self._persist(blocked, stage)
        self._record("GaonV5PipelineBlocked", blocked, request.actor_ref)
        _increment(self._metrics, "gaon_v5_pipeline_blocked_total")
        return _report(blocked)

    def _persist(self, run: GaonV5PipelineRun, stage: GaonV5PipelineStage) -> None:
        self._repository.put_run(run)
        self._repository.checkpoint(run, stage)

    def _record(self, event_type: str, run: GaonV5PipelineRun, actor_ref: str) -> None:
        if self._event_store is None:
            return
        try:
            self._event_store.append(DurableEvent(f"event:v5:{event_type}:{run.run_id}:{run.current_stage.value}", event_type, run.updated_at, actor_ref, run.run_id, run.correlation_id, "gaon_v5_pipeline", "StrategyLab", "N/A", "N/A", {"run_id": run.run_id, "status": run.status.value, "stage": run.current_stage.value}, tuple(run.source_refs.values()), (), run.updated_at))
        except sqlite3.IntegrityError:
            return


def run_from_json(value: str) -> GaonV5PipelineRun:
    payload = json.loads(value)
    return GaonV5PipelineRun(
        run_id=str(payload["run_id"]),
        correlation_id=str(payload["correlation_id"]),
        status=GaonV5PipelineStatus(str(payload["status"])),
        current_stage=GaonV5PipelineStage(str(payload["current_stage"])),
        completed_stages=tuple(GaonV5PipelineStage(str(stage)) for stage in payload["completed_stages"]),
        source_refs={str(key): str(value) for key, value in payload["source_refs"].items()},
        failure_stage=GaonV5PipelineStage(str(payload["failure_stage"])) if payload.get("failure_stage") else None,
        approval_waiting_stage=GaonV5PipelineStage(str(payload["approval_waiting_stage"])) if payload.get("approval_waiting_stage") else None,
        message=str(payload["message"]),
        created_at=str(payload["created_at"]),
        updated_at=str(payload["updated_at"]),
    )


def _fixture_backtests(scenario: str, at: str, run_id: str, active_champion: BacktestResult | None = None) -> tuple[BacktestResult, BacktestResult]:
    champion = active_champion or _backtest(f"{run_id}:champion-backtest", f"{run_id}:champion-request", "turtle_v5", f"fp-{_safe_id(run_id)}-champion", 0.08, 1.2, 40, at)
    champion_return = champion.metrics.total_return if champion.metrics.total_return is not None else 0.08
    champion_profit_factor = champion.metrics.profit_factor if champion.metrics.profit_factor is not None else 1.2
    challenger_return = champion_return - 0.01 if scenario == "keep_champion" else champion_return + 0.10
    challenger = _backtest(f"{run_id}:challenger-backtest", f"{run_id}:challenger-request", "turtle_v5", f"fp-{_safe_id(run_id)}-challenger", challenger_return, champion_profit_factor + 0.50, 50, at)
    return champion, challenger


def _backtest(result_id: str, request_id: str, strategy_id: str, fingerprint: str, total_return: float, profit_factor: float, trade_count: int, at: str) -> BacktestResult:
    return BacktestResult(result_id, request_id, BacktestStatus.COMPLETED, fingerprint, BacktestStrategyRef(strategy_id, "v1"), BacktestDatasetRef("v5_fixture", "v1"), BacktestPeriod("2025-01-01", "2025-12-31"), BacktestMetrics(total_return=total_return, annualized_return=total_return, max_drawdown=-0.05, win_rate=0.55, profit_factor=profit_factor, trade_count=trade_count, exposure=0.5, start_date="2025-01-01", end_date="2025-12-31"), BacktestTradeSummary(trade_count), "v1-fixture", {"lookback": 20, "risk_pct": 0.02}, (), (), at, 1, {"fingerprint": fingerprint, "strategy_id": strategy_id, "dataset_id": "v5_fixture"})


def _validation_policy(scenario: str) -> ValidationPolicy:
    return ValidationPolicy(min_trade_count=999 if scenario == "validation_fail" else 10, min_profit_factor=1.1, min_total_return=0.0)


def _champion_policy(scenario: str) -> ChampionChallengerPolicy:
    return ChampionChallengerPolicy(minimum_return_improvement=0.50 if scenario == "keep_champion" else 0.05)


def _paper_policy(scenario: str) -> PaperRevalidationPolicy:
    if scenario == "paper_hold":
        return PaperRevalidationPolicy(minimum_simulated_trades=999)
    if scenario == "paper_kill":
        return PaperRevalidationPolicy(minimum_simulated_trades=10, maximum_rejection_rate=0.0)
    return PaperRevalidationPolicy(minimum_simulated_trades=10)


def _append_stage(stages: tuple[GaonV5PipelineStage, ...], stage: GaonV5PipelineStage) -> tuple[GaonV5PipelineStage, ...]:
    return stages if stage in stages else stages + (stage,)


def _report(run: GaonV5PipelineRun) -> GaonV5PipelineReport:
    return GaonV5PipelineReport(run.run_id, run.status, run.current_stage, run.completed_stages, run.source_refs, run.message)


def _increment(metrics: MetricsCollector | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name)


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "-", value)[:96]
