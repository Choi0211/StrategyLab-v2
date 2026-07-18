"""Strategy execution runtime with safe mode gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import re
import sqlite3
from typing import Any

from gaon.adapters.champion_registry import DEFAULT_CHAMPION_SLOT, ChampionRegistryEntry, SQLiteChampionRegistryRepository
from gaon.adapters.paper_revalidation import PaperRevalidationReport, PaperRevalidationStatus, SQLitePaperRevalidationRepository
from gaon.adapters.trading import PaperTradingAdapter, SQLiteTradingRepository, TradingExecutionService, TradingIntent, TradingRiskPolicy, TradingStatus, build_trading_request


STRATEGY_EXECUTION_POLICY_VERSION = "strategy_execution_policy_v1"
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class StrategyExecutionMode(str, Enum):
    DISABLED = "disabled"
    PAPER = "paper"
    LIVE = "live"


class StrategyExecutionStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StrategyExecutionPolicy:
    policy_version: str = STRATEGY_EXECUTION_POLICY_VERSION
    default_mode: StrategyExecutionMode = StrategyExecutionMode.DISABLED
    live_trading_enabled: bool = False
    broker_adapter_available: bool = False


@dataclass(frozen=True)
class StrategyExecutionRequest:
    request_id: str
    mode: StrategyExecutionMode
    slot: str
    champion_version_id: str | None
    fingerprint: str | None
    revalidation_id: str | None
    actor_ref: str
    requested_at: str


@dataclass(frozen=True)
class StrategyExecutionDecision:
    status: StrategyExecutionStatus
    reason: str
    approval_required: bool = False


@dataclass(frozen=True)
class StrategyExecutionPlan:
    plan_id: str
    request_id: str
    mode: StrategyExecutionMode
    champion_version_id: str
    strategy_ref: str
    fingerprint: str
    revalidation_id: str | None
    status: StrategyExecutionStatus
    decision: StrategyExecutionDecision
    policy_version: str
    created_at: str

    def to_json(self) -> str:
        return _dumps(
            {
                "plan_id": self.plan_id,
                "request_id": self.request_id,
                "mode": self.mode.value,
                "champion_version_id": self.champion_version_id,
                "strategy_ref": self.strategy_ref,
                "fingerprint": self.fingerprint,
                "revalidation_id": self.revalidation_id,
                "status": self.status.value,
                "decision": self.decision.__dict__ | {"status": self.decision.status.value},
                "policy_version": self.policy_version,
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True)
class StrategyExecutionRun:
    run_id: str
    plan_id: str
    mode: StrategyExecutionMode
    champion_version_id: str
    fingerprint: str
    status: StrategyExecutionStatus
    result_ref: str | None
    block_reason: str | None
    started_at: str
    completed_at: str | None

    def to_json(self) -> str:
        return _dumps(self.__dict__ | {"mode": self.mode.value, "status": self.status.value})


class SQLiteStrategyExecutionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_plan(self, plan: StrategyExecutionPlan) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO strategy_execution_plans(plan_id, mode, champion_version_id, fingerprint, status, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (plan.plan_id, plan.mode.value, plan.champion_version_id, plan.fingerprint, plan.status.value, plan.to_json(), plan.created_at),
            )

    def get_plan(self, plan_id: str) -> StrategyExecutionPlan:
        row = self._connection.execute("SELECT payload_json FROM strategy_execution_plans WHERE plan_id = ?", (plan_id,)).fetchone()
        if row is None:
            raise KeyError(plan_id)
        return plan_from_json(str(row[0]))

    def list_plans(self) -> tuple[StrategyExecutionPlan, ...]:
        rows = self._connection.execute("SELECT payload_json FROM strategy_execution_plans ORDER BY created_at, plan_id").fetchall()
        return tuple(plan_from_json(str(row[0])) for row in rows)

    def add_run(self, run: StrategyExecutionRun) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO strategy_execution_runs(run_id, plan_id, mode, champion_version_id, fingerprint, status, payload_json, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run.run_id, run.plan_id, run.mode.value, run.champion_version_id, run.fingerprint, run.status.value, run.to_json(), run.started_at, run.completed_at),
            )

    def get_run(self, run_id: str) -> StrategyExecutionRun:
        row = self._connection.execute("SELECT payload_json FROM strategy_execution_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return run_from_json(str(row[0]))

    def list_runs(self) -> tuple[StrategyExecutionRun, ...]:
        rows = self._connection.execute("SELECT payload_json FROM strategy_execution_runs ORDER BY started_at, run_id").fetchall()
        return tuple(run_from_json(str(row[0])) for row in rows)

    def has_active_run(self, champion_version_id: str, mode: StrategyExecutionMode) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM strategy_execution_runs WHERE champion_version_id = ? AND mode = ? AND status IN ('created','ready','running') LIMIT 1",
            (champion_version_id, mode.value),
        ).fetchone()
        return row is not None


class StrategyExecutionRuntime:
    def __init__(self, repository: SQLiteStrategyExecutionRepository, registry: SQLiteChampionRegistryRepository, *, revalidations: SQLitePaperRevalidationRepository | None = None, trading_repository: SQLiteTradingRepository | None = None, event_store: Any | None = None, metrics: Any | None = None, policy: StrategyExecutionPolicy | None = None) -> None:
        self._repository = repository
        self._registry = registry
        self._revalidations = revalidations
        self._trading_repository = trading_repository
        self._event_store = event_store
        self._metrics = metrics
        self._policy = policy or StrategyExecutionPolicy()

    @property
    def policy(self) -> StrategyExecutionPolicy:
        return self._policy

    def plan(self, request: StrategyExecutionRequest) -> StrategyExecutionPlan:
        _validate_utc(request.requested_at)
        active = self._registry.get_active(request.slot)
        _increment(self._metrics, "gaon_strategy_execution_requests_total")
        if active is None:
            return self._blocked_plan(request, "active champion is required")
        if request.champion_version_id and request.champion_version_id != active.active_version_id:
            return self._blocked_plan(request, "stale champion execution blocked", active)
        if request.fingerprint and request.fingerprint != active.fingerprint:
            return self._blocked_plan(request, "champion fingerprint mismatch", active)
        decision = self._decision(request, active)
        plan = StrategyExecutionPlan(f"execution-plan:{request.request_id}", request.request_id, request.mode, active.active_version_id, active.strategy_ref, active.fingerprint, request.revalidation_id, StrategyExecutionStatus.READY if decision.status == StrategyExecutionStatus.READY else StrategyExecutionStatus.BLOCKED, decision, self._policy.policy_version, request.requested_at)
        self._repository.add_plan(plan)
        self._record("StrategyExecutionPlanned" if plan.status == StrategyExecutionStatus.READY else "StrategyExecutionBlocked", plan.plan_id, request.actor_ref, request.requested_at, {"mode": plan.mode.value, "reason": decision.reason})
        if plan.status == StrategyExecutionStatus.BLOCKED:
            _increment(self._metrics, "gaon_strategy_execution_blocked_total")
        return plan

    def run(self, plan_id: str, *, actor_ref: str, at: str) -> StrategyExecutionRun:
        plan = self._repository.get_plan(plan_id)
        active = self._registry.get_active(DEFAULT_CHAMPION_SLOT)
        if active is None or active.active_version_id != plan.champion_version_id or active.fingerprint != plan.fingerprint:
            run = StrategyExecutionRun(f"execution-run:{plan.plan_id}", plan.plan_id, plan.mode, plan.champion_version_id, plan.fingerprint, StrategyExecutionStatus.BLOCKED, None, "stale champion execution blocked", at, at)
            self._repository.add_run(run)
            self._record("StaleChampionExecutionBlocked", run.run_id, actor_ref, at, {"plan_id": plan.plan_id})
            return run
        if plan.status == StrategyExecutionStatus.BLOCKED:
            run = StrategyExecutionRun(f"execution-run:{plan.plan_id}", plan.plan_id, plan.mode, plan.champion_version_id, plan.fingerprint, StrategyExecutionStatus.BLOCKED, None, plan.decision.reason, at, at)
            self._repository.add_run(run)
            return run
        if self._repository.has_active_run(plan.champion_version_id, plan.mode):
            run = StrategyExecutionRun(f"execution-run:{plan.plan_id}:duplicate", plan.plan_id, plan.mode, plan.champion_version_id, plan.fingerprint, StrategyExecutionStatus.BLOCKED, None, "duplicate active execution", at, at)
            self._repository.add_run(run)
            return run
        self._record("StrategyExecutionStarted", plan.plan_id, actor_ref, at, {"mode": plan.mode.value})
        _increment(self._metrics, "gaon_strategy_execution_runs_total")
        if plan.mode == StrategyExecutionMode.LIVE:
            run = StrategyExecutionRun(f"execution-run:{plan.plan_id}", plan.plan_id, plan.mode, plan.champion_version_id, plan.fingerprint, StrategyExecutionStatus.BLOCKED, None, "live broker adapter unavailable", at, at)
            self._repository.add_run(run)
            self._record("LiveExecutionBlocked", run.run_id, actor_ref, at, {"reason": run.block_reason or ""})
            _increment(self._metrics, "gaon_live_execution_blocked_total")
            return run
        result = TradingExecutionService(PaperTradingAdapter(), TradingRiskPolicy(), repository=self._trading_repository, event_store=self._event_store, metrics=self._metrics).execute(build_trading_request(f"strategy-execution:{plan.plan_id}", TradingIntent.SIMULATE_BUY, symbol="PAPER", quantity=1, price=1.0, actor_ref=actor_ref, created_at=at, idempotency_key=f"strategy-execution:{plan.plan_id}"))
        status = StrategyExecutionStatus.COMPLETED if result.status == TradingStatus.SIMULATED else StrategyExecutionStatus.FAILED
        run = StrategyExecutionRun(f"execution-run:{plan.plan_id}", plan.plan_id, plan.mode, plan.champion_version_id, plan.fingerprint, status, result.result_id, None if status == StrategyExecutionStatus.COMPLETED else result.message, at, at)
        self._repository.add_run(run)
        self._record("StrategyExecutionCompleted" if status == StrategyExecutionStatus.COMPLETED else "StrategyExecutionFailed", run.run_id, actor_ref, at, {"result_ref": result.result_id})
        _increment(self._metrics, "gaon_paper_execution_runs_total")
        return run

    def _decision(self, request: StrategyExecutionRequest, active: ChampionRegistryEntry) -> StrategyExecutionDecision:
        if request.mode == StrategyExecutionMode.DISABLED:
            return StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, "execution mode disabled")
        if request.mode == StrategyExecutionMode.PAPER:
            return StrategyExecutionDecision(StrategyExecutionStatus.READY, "paper execution allowed for active Champion")
        report = self._load_revalidation(request.revalidation_id)
        if report is None:
            return StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, "live execution requires revalidation")
        if report.status == PaperRevalidationStatus.KILL:
            return StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, "KILL revalidation blocks execution")
        if report.status == PaperRevalidationStatus.ROLLBACK_RECOMMENDED:
            return StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, "rollback recommended blocks live execution")
        if report.status == PaperRevalidationStatus.HOLD:
            return StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, "HOLD revalidation blocks live execution")
        if report.status != PaperRevalidationStatus.LIVE_ELIGIBLE:
            return StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, "revalidation is not live eligible")
        if not self._policy.live_trading_enabled:
            return StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, "live trading disabled by policy")
        return StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, "live broker adapter unavailable", approval_required=True)

    def _load_revalidation(self, revalidation_id: str | None) -> PaperRevalidationReport | None:
        if revalidation_id is None or self._revalidations is None:
            return None
        return self._revalidations.get_report(revalidation_id)

    def _blocked_plan(self, request: StrategyExecutionRequest, reason: str, active: ChampionRegistryEntry | None = None) -> StrategyExecutionPlan:
        fallback = active or ChampionRegistryEntry(request.slot, "missing", "missing", "missing", "missing", "missing", "missing", request.requested_at, 1, None)
        plan = StrategyExecutionPlan(f"execution-plan:{request.request_id}", request.request_id, request.mode, fallback.active_version_id, fallback.strategy_ref, fallback.fingerprint, request.revalidation_id, StrategyExecutionStatus.BLOCKED, StrategyExecutionDecision(StrategyExecutionStatus.BLOCKED, reason), self._policy.policy_version, request.requested_at)
        self._repository.add_plan(plan)
        return plan

    def _record(self, event_type: str, correlation_id: str, actor_ref: str, at: str, payload: dict[str, object]) -> None:
        if self._event_store is not None:
            from gaon.runtime.event_store import DurableEvent

            try:
                self._event_store.append(DurableEvent(f"event:strategy-execution:{event_type}:{correlation_id}", event_type, at, actor_ref, correlation_id, None, "strategy_execution", "StrategyLab", "N/A", "N/A", payload, (), (), at))
            except sqlite3.IntegrityError:
                return


def build_strategy_execution_request(request_id: str, mode: StrategyExecutionMode, *, actor_ref: str, requested_at: str, slot: str = DEFAULT_CHAMPION_SLOT, champion_version_id: str | None = None, fingerprint: str | None = None, revalidation_id: str | None = None) -> StrategyExecutionRequest:
    return StrategyExecutionRequest(request_id, mode, slot, champion_version_id, fingerprint, revalidation_id, actor_ref, requested_at)


def plan_from_json(value: str) -> StrategyExecutionPlan:
    payload = json.loads(value)
    decision = payload["decision"]
    return StrategyExecutionPlan(str(payload["plan_id"]), str(payload["request_id"]), StrategyExecutionMode(str(payload["mode"])), str(payload["champion_version_id"]), str(payload["strategy_ref"]), str(payload["fingerprint"]), payload.get("revalidation_id"), StrategyExecutionStatus(str(payload["status"])), StrategyExecutionDecision(StrategyExecutionStatus(str(decision["status"])), str(decision["reason"]), bool(decision["approval_required"])), str(payload["policy_version"]), str(payload["created_at"]))


def run_from_json(value: str) -> StrategyExecutionRun:
    payload = json.loads(value)
    return StrategyExecutionRun(str(payload["run_id"]), str(payload["plan_id"]), StrategyExecutionMode(str(payload["mode"])), str(payload["champion_version_id"]), str(payload["fingerprint"]), StrategyExecutionStatus(str(payload["status"])), payload.get("result_ref"), payload.get("block_reason"), str(payload["started_at"]), payload.get("completed_at"))


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name, component="strategy_execution")


def _dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
