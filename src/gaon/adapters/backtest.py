"""Safe v1 backtest adapter boundary.

This module defines v2 contracts for invoking a future v1 backtest engine.
It does not import private repositories or execute arbitrary user supplied code.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
import sqlite3
from typing import Any, Protocol

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REF_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.\-]{1,63}$")
MAX_OUTPUT_BYTES = 64_000
DEFAULT_SUPPORTED_STRATEGIES = ("turtle_v5", "turtle_v6_candidate")


class BacktestStatus(str, Enum):
    REQUESTED = "requested"
    VALIDATED = "validated"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


@dataclass(frozen=True)
class BacktestStrategyRef:
    strategy_id: str
    version: str = "v1"

    def __post_init__(self) -> None:
        _validate_ref(self.strategy_id, "strategy id")
        _validate_ref(self.version, "strategy version")


@dataclass(frozen=True)
class BacktestDatasetRef:
    dataset_id: str
    version: str = "fixture"

    def __post_init__(self) -> None:
        _validate_ref(self.dataset_id, "dataset id")
        _validate_ref(self.version, "dataset version")


@dataclass(frozen=True)
class BacktestPeriod:
    start_date: str
    end_date: str

    def __post_init__(self) -> None:
        if DATE_ONLY.fullmatch(self.start_date) is None or DATE_ONLY.fullmatch(self.end_date) is None:
            raise ValueError("backtest period dates must use YYYY-MM-DD")
        if self.start_date >= self.end_date:
            raise ValueError("backtest period start_date must be before end_date")


@dataclass(frozen=True)
class BacktestRequest:
    request_id: str
    strategy: BacktestStrategyRef
    dataset: BacktestDatasetRef
    period: BacktestPeriod
    parameters: dict[str, float | int | str | bool]
    actor_ref: str
    created_at: str
    engine_version: str = "v1-fixture"

    def __post_init__(self) -> None:
        if not self.request_id or not self.actor_ref:
            raise ValueError("backtest request requires id and actor")
        _validate_ref(self.request_id.replace(":", "-"), "request id")
        _validate_utc(self.created_at)
        _validate_ref(self.engine_version, "engine version")

    @property
    def fingerprint(self) -> str:
        material = {
            "strategy": self.strategy.__dict__,
            "dataset": self.dataset.__dict__,
            "period": self.period.__dict__,
            "parameters": self.parameters,
            "engine_version": self.engine_version,
        }
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:24]

    def to_json(self) -> str:
        return json.dumps(
            {
                "request_id": self.request_id,
                "strategy": self.strategy.__dict__,
                "dataset": self.dataset.__dict__,
                "period": self.period.__dict__,
                "parameters": self.parameters,
                "actor_ref": self.actor_ref,
                "created_at": self.created_at,
                "engine_version": self.engine_version,
                "fingerprint": self.fingerprint,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class BacktestExecutionContext:
    timeout_seconds: int
    max_output_bytes: int
    generated_at: str

    def __post_init__(self) -> None:
        _validate_utc(self.generated_at)
        if self.timeout_seconds < 1 or self.timeout_seconds > 300:
            raise ValueError("backtest timeout must be bounded")
        if self.max_output_bytes < 1024 or self.max_output_bytes > MAX_OUTPUT_BYTES:
            raise ValueError("backtest output bound is invalid")


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float | None = None
    annualized_return: float | None = None
    max_drawdown: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    sharpe_ratio: float | None = None
    trade_count: int | None = None
    average_trade_return: float | None = None
    exposure: float | None = None
    start_date: str | None = None
    end_date: str | None = None


@dataclass(frozen=True)
class BacktestTradeSummary:
    trade_count: int
    winning_trades: int | None = None
    losing_trades: int | None = None
    gross_profit: float | None = None
    gross_loss: float | None = None

    def __post_init__(self) -> None:
        if self.trade_count < 0:
            raise ValueError("trade_count must be non-negative")


@dataclass(frozen=True)
class BacktestResult:
    result_id: str
    request_id: str
    status: BacktestStatus
    fingerprint: str
    strategy: BacktestStrategyRef
    dataset: BacktestDatasetRef
    period: BacktestPeriod
    metrics: BacktestMetrics
    trade_summary: BacktestTradeSummary
    raw_engine_version: str
    parameters: dict[str, float | int | str | bool]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    generated_at: str
    duration_ms: int
    reproducibility: dict[str, str]

    def __post_init__(self) -> None:
        _validate_utc(self.generated_at)
        if self.duration_ms < 0:
            raise ValueError("duration_ms must be non-negative")

    def to_json(self) -> str:
        return json.dumps(
            {
                "result_id": self.result_id,
                "request_id": self.request_id,
                "status": self.status.value,
                "fingerprint": self.fingerprint,
                "strategy": self.strategy.__dict__,
                "dataset": self.dataset.__dict__,
                "period": self.period.__dict__,
                "metrics": self.metrics.__dict__,
                "trade_summary": self.trade_summary.__dict__,
                "raw_engine_version": self.raw_engine_version,
                "parameters": self.parameters,
                "warnings": list(self.warnings),
                "errors": list(self.errors),
                "generated_at": self.generated_at,
                "duration_ms": self.duration_ms,
                "reproducibility": self.reproducibility,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class BacktestAdapter(Protocol):
    def validate_request(self, request: BacktestRequest) -> tuple[bool, tuple[str, ...]]: ...
    def run_backtest(self, request: BacktestRequest, context: BacktestExecutionContext) -> BacktestResult: ...
    def health_check(self) -> tuple[bool, str]: ...
    def get_supported_strategies(self) -> tuple[str, ...]: ...


@dataclass(frozen=True)
class LocalProcessResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False


class FixedBacktestInvoker(Protocol):
    def invoke(self, request_json: str, *, timeout_seconds: int, max_output_bytes: int) -> LocalProcessResult: ...


class FakeBacktestAdapter:
    def __init__(self, supported_strategies: tuple[str, ...] = DEFAULT_SUPPORTED_STRATEGIES, *, fail: bool = False) -> None:
        self._supported = tuple(sorted(supported_strategies))
        self._fail = fail

    def validate_request(self, request: BacktestRequest) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if request.strategy.strategy_id not in self._supported:
            reasons.append("unsupported strategy")
        return not reasons, tuple(reasons)

    def run_backtest(self, request: BacktestRequest, context: BacktestExecutionContext) -> BacktestResult:
        valid, reasons = self.validate_request(request)
        if not valid:
            return _failed_result(request, BacktestStatus.REJECTED, reasons, context.generated_at, 0)
        if self._fail:
            return _failed_result(request, BacktestStatus.FAILED, ("fake backtest failure",), context.generated_at, 1)
        raw = {
            "engine_version": request.engine_version,
            "strategy_version": request.strategy.version,
            "dataset_version": request.dataset.version,
            "metrics": {
                "total_return": 0.1234,
                "max_drawdown": -0.045,
                "win_rate": 0.55,
                "profit_factor": 1.42,
                "trade_count": 12,
                "start_date": request.period.start_date,
                "end_date": request.period.end_date,
            },
            "warnings": ["fixture result; real v1 engine not invoked"],
            "errors": [],
            "duration_ms": 7,
        }
        return normalize_v1_backtest_result(request, raw, generated_at=context.generated_at)

    def health_check(self) -> tuple[bool, str]:
        return True, "fake backtest adapter ready; real v1 engine not required"

    def get_supported_strategies(self) -> tuple[str, ...]:
        return self._supported


class LocalProcessBacktestAdapter:
    def __init__(self, invoker: FixedBacktestInvoker, supported_strategies: tuple[str, ...] = DEFAULT_SUPPORTED_STRATEGIES) -> None:
        self._invoker = invoker
        self._supported = tuple(sorted(supported_strategies))

    def validate_request(self, request: BacktestRequest) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if request.strategy.strategy_id not in self._supported:
            reasons.append("unsupported strategy")
        return not reasons, tuple(reasons)

    def run_backtest(self, request: BacktestRequest, context: BacktestExecutionContext) -> BacktestResult:
        valid, reasons = self.validate_request(request)
        if not valid:
            return _failed_result(request, BacktestStatus.REJECTED, reasons, context.generated_at, 0)
        process = self._invoker.invoke(request.to_json(), timeout_seconds=context.timeout_seconds, max_output_bytes=context.max_output_bytes)
        if process.timed_out:
            return _failed_result(request, BacktestStatus.TIMEOUT, ("v1 backtest invocation timed out",), context.generated_at, process.duration_ms)
        if len(process.stdout.encode("utf-8")) > context.max_output_bytes:
            return _failed_result(request, BacktestStatus.FAILED, ("v1 backtest output exceeded bound",), context.generated_at, process.duration_ms)
        if process.exit_code != 0:
            return _failed_result(request, BacktestStatus.FAILED, ("v1 backtest exited non-zero",), context.generated_at, process.duration_ms)
        try:
            raw = json.loads(process.stdout)
        except json.JSONDecodeError:
            return _failed_result(request, BacktestStatus.FAILED, ("v1 backtest returned invalid JSON",), context.generated_at, process.duration_ms)
        return normalize_v1_backtest_result(request, raw, generated_at=context.generated_at, duration_ms=process.duration_ms)

    def health_check(self) -> tuple[bool, str]:
        return True, "local process boundary configured; executable entrypoint is fixed by caller"

    def get_supported_strategies(self) -> tuple[str, ...]:
        return self._supported


def normalize_v1_backtest_result(request: BacktestRequest, raw: dict[str, Any], *, generated_at: str, duration_ms: int | None = None) -> BacktestResult:
    metrics_payload = raw.get("metrics", {})
    if not isinstance(metrics_payload, dict):
        metrics_payload = {}
    metrics = BacktestMetrics(
        total_return=_optional_float(metrics_payload.get("total_return")),
        annualized_return=_optional_float(metrics_payload.get("annualized_return")),
        max_drawdown=_optional_float(metrics_payload.get("max_drawdown")),
        win_rate=_optional_float(metrics_payload.get("win_rate")),
        profit_factor=_optional_float(metrics_payload.get("profit_factor")),
        sharpe_ratio=_optional_float(metrics_payload.get("sharpe_ratio")),
        trade_count=_optional_int(metrics_payload.get("trade_count")),
        average_trade_return=_optional_float(metrics_payload.get("average_trade_return")),
        exposure=_optional_float(metrics_payload.get("exposure")),
        start_date=str(metrics_payload["start_date"]) if "start_date" in metrics_payload else None,
        end_date=str(metrics_payload["end_date"]) if "end_date" in metrics_payload else None,
    )
    trade_count = metrics.trade_count if metrics.trade_count is not None else 0
    return BacktestResult(
        result_id=f"backtest-result:{request.fingerprint}",
        request_id=request.request_id,
        status=BacktestStatus.COMPLETED,
        fingerprint=request.fingerprint,
        strategy=request.strategy,
        dataset=request.dataset,
        period=request.period,
        metrics=metrics,
        trade_summary=BacktestTradeSummary(trade_count=trade_count),
        raw_engine_version=str(raw.get("engine_version", request.engine_version)),
        parameters=dict(request.parameters),
        warnings=tuple(str(item) for item in raw.get("warnings", ())),
        errors=tuple(str(item) for item in raw.get("errors", ())),
        generated_at=generated_at,
        duration_ms=int(duration_ms if duration_ms is not None else raw.get("duration_ms", 0)),
        reproducibility={"fingerprint": request.fingerprint, "strategy_id": request.strategy.strategy_id, "dataset_id": request.dataset.dataset_id},
    )


class SQLiteBacktestRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_request(self, request: BacktestRequest) -> bool:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO backtest_requests(request_id, fingerprint, strategy_id, dataset_id, period_start, period_end, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (request.request_id, request.fingerprint, request.strategy.strategy_id, request.dataset.dataset_id, request.period.start_date, request.period.end_date, request.to_json(), request.created_at),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def add_result(self, result: BacktestResult) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO backtest_results(result_id, request_id, status, fingerprint, payload_json, generated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (result.result_id, result.request_id, result.status.value, result.fingerprint, result.to_json(), result.generated_at),
            )

    def get_result(self, result_id: str) -> BacktestResult:
        row = self._connection.execute("SELECT payload_json FROM backtest_results WHERE result_id = ?", (result_id,)).fetchone()
        if row is None:
            raise KeyError(result_id)
        return result_from_json(str(row[0]))

    def list_results(self) -> tuple[BacktestResult, ...]:
        rows = self._connection.execute("SELECT payload_json FROM backtest_results ORDER BY generated_at, result_id").fetchall()
        return tuple(result_from_json(str(row[0])) for row in rows)


class BacktestExecutionService:
    def __init__(self, adapter: BacktestAdapter, *, repository: SQLiteBacktestRepository | None = None, event_store: Any | None = None, metrics: Any | None = None) -> None:
        self._adapter = adapter
        self._repository = repository
        self._event_store = event_store
        self._metrics = metrics

    def run(self, request: BacktestRequest, context: BacktestExecutionContext) -> BacktestResult:
        if self._repository is not None and not self._repository.add_request(request):
            result = _failed_result(request, BacktestStatus.REJECTED, ("duplicate backtest request",), context.generated_at, 0)
            self._record("BacktestRejected", request, result)
            _increment(self._metrics, "gaon_backtest_rejections_total")
            self._repository.add_result(result)
            return result
        self._record("BacktestRequested", request, None)
        _increment(self._metrics, "gaon_backtest_requests_total")
        valid, reasons = self._adapter.validate_request(request)
        if not valid:
            result = _failed_result(request, BacktestStatus.REJECTED, reasons, context.generated_at, 0)
            self._record("BacktestRejected", request, result)
            _increment(self._metrics, "gaon_backtest_rejections_total")
            if self._repository is not None:
                self._repository.add_result(result)
            return result
        self._record("BacktestStarted", request, None)
        result = self._adapter.run_backtest(request, context)
        if result.status == BacktestStatus.COMPLETED:
            self._record("BacktestCompleted", request, result)
            _increment(self._metrics, "gaon_backtest_runs_total")
        else:
            self._record("BacktestFailed", request, result)
            _increment(self._metrics, "gaon_backtest_failures_total")
        if self._repository is not None:
            self._repository.add_result(result)
        return result

    def _record(self, event_type: str, request: BacktestRequest, result: BacktestResult | None) -> None:
        if self._event_store is not None:
            self._event_store.append(backtest_event(event_type, request, result))


def backtest_event(event_type: str, request: BacktestRequest, result: BacktestResult | None):
    from gaon.runtime.event_store import DurableEvent

    return DurableEvent(
        event_id=f"event:backtest:{event_type}:{request.request_id}:{result.result_id if result else request.created_at}",
        event_type=event_type,
        occurred_at=result.generated_at if result else request.created_at,
        actor_ref=request.actor_ref,
        correlation_id=request.request_id,
        causation_id=None,
        scope="backtest",
        project="StrategyLab",
        strategy=request.strategy.strategy_id,
        market="N/A",
        payload={"request_id": request.request_id, "status": result.status.value if result else BacktestStatus.REQUESTED.value, "fingerprint": request.fingerprint},
        evidence_refs=(),
        audit_refs=(),
        appended_at=result.generated_at if result else request.created_at,
    )


def result_from_json(value: str) -> BacktestResult:
    payload = json.loads(value)
    metrics = BacktestMetrics(**payload["metrics"])
    summary = BacktestTradeSummary(**payload["trade_summary"])
    return BacktestResult(
        result_id=str(payload["result_id"]),
        request_id=str(payload["request_id"]),
        status=BacktestStatus(str(payload["status"])),
        fingerprint=str(payload["fingerprint"]),
        strategy=BacktestStrategyRef(**payload["strategy"]),
        dataset=BacktestDatasetRef(**payload["dataset"]),
        period=BacktestPeriod(**payload["period"]),
        metrics=metrics,
        trade_summary=summary,
        raw_engine_version=str(payload["raw_engine_version"]),
        parameters=dict(payload["parameters"]),
        warnings=tuple(str(item) for item in payload["warnings"]),
        errors=tuple(str(item) for item in payload["errors"]),
        generated_at=str(payload["generated_at"]),
        duration_ms=int(payload["duration_ms"]),
        reproducibility={str(k): str(v) for k, v in payload["reproducibility"].items()},
    )


def build_backtest_request(request_id: str, strategy_id: str, dataset_id: str, start: str, end: str, *, actor_ref: str, created_at: str, parameters: dict[str, float | int | str | bool] | None = None) -> BacktestRequest:
    return BacktestRequest(request_id, BacktestStrategyRef(strategy_id), BacktestDatasetRef(dataset_id), BacktestPeriod(start, end), parameters or {}, actor_ref, created_at)


def _failed_result(request: BacktestRequest, status: BacktestStatus, errors: tuple[str, ...], generated_at: str, duration_ms: int) -> BacktestResult:
    return BacktestResult(
        result_id=f"backtest-result:{request.fingerprint}",
        request_id=request.request_id,
        status=status,
        fingerprint=request.fingerprint,
        strategy=request.strategy,
        dataset=request.dataset,
        period=request.period,
        metrics=BacktestMetrics(start_date=request.period.start_date, end_date=request.period.end_date),
        trade_summary=BacktestTradeSummary(0),
        raw_engine_version=request.engine_version,
        parameters=dict(request.parameters),
        warnings=(),
        errors=errors,
        generated_at=generated_at,
        duration_ms=duration_ms,
        reproducibility={"fingerprint": request.fingerprint, "strategy_id": request.strategy.strategy_id, "dataset_id": request.dataset.dataset_id},
    )


def _validate_ref(value: str, label: str) -> None:
    if REF_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name, component="backtest")
