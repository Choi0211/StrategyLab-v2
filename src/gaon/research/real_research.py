"""Real market data and external backtest integration contracts.

Sprint 101-110 makes Gaon ready to connect real market data and external
backtest engines through explicit contracts. The default implementation is
fixture-backed and deterministic. No private repository is imported, no
arbitrary shell is executed, and no live trading side effect is allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
import hashlib
import json
import re
import sqlite3
from typing import Protocol
from uuid import uuid4

from gaon.research.self_improving import ResearchCritic, ResearchQualityScorer, StrategyCandidate


REAL_RESEARCH_SCHEMA_VERSION = 1
ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:\-]{1,127}$")


class DataQualityStatus(str, Enum):
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    FAIL = "fail"


class BacktestRunStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    TIMEOUT = "timeout"


class BacktestResultSource(str, Enum):
    FIXTURE = "fixture"
    EXTERNAL_BACKTEST = "external_backtest"


@dataclass(frozen=True)
class MarketSymbol:
    symbol: str
    name: str
    market: str
    exchange: str = "KRX"

    def __post_init__(self) -> None:
        _validate_id(self.symbol, "symbol")

    def to_json(self) -> dict[str, object]:
        return {"schema_version": REAL_RESEARCH_SCHEMA_VERSION, "symbol": self.symbol, "name": self.name, "market": self.market, "exchange": self.exchange}


@dataclass(frozen=True)
class MarketDataMetadata:
    source: str
    market: str
    timeframe: str
    start_date: str
    end_date: str
    adjusted: bool
    retrieved_at: str
    fixture_backed: bool

    def __post_init__(self) -> None:
        _validate_date(self.start_date)
        _validate_date(self.end_date)
        _validate_utc(self.retrieved_at)
        if self.start_date > self.end_date:
            raise ValueError("metadata start_date must not be after end_date")

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": REAL_RESEARCH_SCHEMA_VERSION,
            "source": self.source,
            "market": self.market,
            "timeframe": self.timeframe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "adjusted": self.adjusted,
            "retrieved_at": self.retrieved_at,
            "fixture_backed": self.fixture_backed,
        }


@dataclass(frozen=True)
class MarketBar:
    timestamp: str
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    trading_value: int

    def __post_init__(self) -> None:
        _validate_date(self.timestamp)
        _validate_id(self.symbol, "symbol")

    def to_json(self) -> dict[str, object]:
        return {"timestamp": self.timestamp, "symbol": self.symbol, "open": self.open, "high": self.high, "low": self.low, "close": self.close, "volume": self.volume, "trading_value": self.trading_value}


@dataclass(frozen=True)
class CorporateAction:
    symbol: str
    effective_date: str
    action_type: str
    ratio: float
    source: str

    def to_json(self) -> dict[str, object]:
        return {"symbol": self.symbol, "effective_date": self.effective_date, "action_type": self.action_type, "ratio": self.ratio, "source": self.source}


@dataclass(frozen=True)
class MarketCalendar:
    market: str
    open_dates: tuple[str, ...]
    closed_dates: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        return {"market": self.market, "open_dates": list(self.open_dates), "closed_dates": list(self.closed_dates)}


@dataclass(frozen=True)
class MarketDataset:
    dataset_id: str
    symbols: tuple[MarketSymbol, ...]
    bars: tuple[MarketBar, ...]
    metadata: MarketDataMetadata
    corporate_actions: tuple[CorporateAction, ...] = ()

    def __post_init__(self) -> None:
        _validate_id(self.dataset_id, "dataset_id")
        object.__setattr__(self, "symbols", tuple(self.symbols))
        object.__setattr__(self, "bars", tuple(self.bars))
        object.__setattr__(self, "corporate_actions", tuple(self.corporate_actions))

    @property
    def fingerprint(self) -> str:
        return _sha(
            {
                "symbols": [item.to_json() for item in self.symbols],
                "bars": [item.to_json() for item in self.bars],
                "metadata": self.metadata.to_json(),
                "corporate_actions": [item.to_json() for item in self.corporate_actions],
            }
        )

    @property
    def checksum(self) -> str:
        return self.fingerprint

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": REAL_RESEARCH_SCHEMA_VERSION,
            "dataset_id": self.dataset_id,
            "fingerprint": self.fingerprint,
            "symbols": [item.to_json() for item in self.symbols],
            "bars": [item.to_json() for item in self.bars],
            "metadata": self.metadata.to_json(),
            "corporate_actions": [item.to_json() for item in self.corporate_actions],
        }


class MarketDataProvider(Protocol):
    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset: ...
    def fetch_universe(self, market: str) -> tuple[MarketSymbol, ...]: ...
    def fetch_trading_calendar(self, market: str, *, start_date: str, end_date: str) -> MarketCalendar: ...
    def validate_dataset(self, dataset: MarketDataset) -> "DataQualityReport": ...


class FixtureMarketDataProvider:
    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        _validate_date(start_date)
        _validate_date(end_date)
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        upper = symbol.upper()
        dates = _date_range(start_date, end_date)
        bars = []
        for index, day in enumerate(dates):
            close = 100.0 + index * 0.7
            bars.append(MarketBar(day, upper, close - 0.5, close + 1.0, close - 1.2, close, 1_000_000 + index * 5_000, 100_000_000_000 + index * 500_000_000))
        market = "KOSPI" if upper.startswith("KS") or upper in {"KOSPI", "005930"} else "KOSDAQ"
        metadata = MarketDataMetadata("fixture:krx-market-data", market, timeframe, start_date, end_date, True, utc_now(), True)
        dataset_id = f"dataset:{upper}:{timeframe}:{start_date}:{end_date}"
        return MarketDataset(dataset_id, (MarketSymbol(upper, upper, market),), tuple(bars), metadata)

    def fetch_universe(self, market: str) -> tuple[MarketSymbol, ...]:
        return (MarketSymbol("005930", "Samsung Electronics", "KOSPI"), MarketSymbol("035420", "NAVER", "KOSPI"), MarketSymbol("091990", "Celltrion Healthcare", "KOSDAQ"))

    def fetch_trading_calendar(self, market: str, *, start_date: str, end_date: str) -> MarketCalendar:
        return MarketCalendar(market, tuple(_date_range(start_date, end_date)), ())

    def validate_dataset(self, dataset: MarketDataset) -> "DataQualityReport":
        return DataQualityEngine().validate(dataset)


@dataclass(frozen=True)
class DataQualityFinding:
    code: str
    severity: str
    message: str

    def to_json(self) -> dict[str, object]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass(frozen=True)
class DataQualityReport:
    report_id: str
    dataset_id: str
    status: DataQualityStatus
    findings: tuple[DataQualityFinding, ...]
    generated_at: str

    def to_json(self) -> dict[str, object]:
        return {"schema_version": REAL_RESEARCH_SCHEMA_VERSION, "report_id": self.report_id, "dataset_id": self.dataset_id, "status": self.status.value, "findings": [item.to_json() for item in self.findings], "generated_at": self.generated_at}


class DataQualityEngine:
    def validate(self, dataset: MarketDataset, *, min_bars: int = 3, max_stale_days: int = 3650) -> DataQualityReport:
        findings: list[DataQualityFinding] = []
        seen: set[tuple[str, str]] = set()
        previous: str | None = None
        expected = {symbol.symbol for symbol in dataset.symbols}
        for bar in dataset.bars:
            key = (bar.symbol, bar.timestamp)
            if key in seen:
                findings.append(DataQualityFinding("duplicate_bars", "error", f"duplicate bar {bar.symbol} {bar.timestamp}"))
            seen.add(key)
            if previous and bar.timestamp < previous:
                findings.append(DataQualityFinding("timestamp_ordering", "error", "bars must be sorted by timestamp"))
            previous = bar.timestamp
            if bar.symbol not in expected:
                findings.append(DataQualityFinding("symbol_mismatch", "error", f"bar symbol {bar.symbol} is not in dataset symbols"))
            if not (bar.low <= bar.open <= bar.high and bar.low <= bar.close <= bar.high):
                findings.append(DataQualityFinding("invalid_ohlc", "error", "OHLC values are inconsistent"))
            if bar.volume < 0 or bar.trading_value < 0:
                findings.append(DataQualityFinding("negative_volume", "error", "volume and trading_value must be non-negative"))
            elif bar.volume == 0:
                findings.append(DataQualityFinding("zero_volume", "warning", "zero volume bar requires review"))
            elif bar.volume > 100_000_000_000:
                findings.append(DataQualityFinding("abnormal_volume", "warning", "abnormally high volume"))
        if len(dataset.bars) < min_bars:
            findings.append(DataQualityFinding("insufficient_lookback", "error", "dataset has insufficient lookback"))
        dates = [bar.timestamp for bar in dataset.bars]
        if dates:
            expected_dates = set(_date_range(min(dates), max(dates)))
            missing = sorted(expected_dates.difference(dates))
            if missing:
                findings.append(DataQualityFinding("missing_dates", "warning", f"missing {len(missing)} calendar dates"))
        try:
            retrieved = datetime.fromisoformat(dataset.metadata.retrieved_at.replace("Z", "+00:00"))
            if datetime.now(UTC) - retrieved > timedelta(days=max_stale_days):
                findings.append(DataQualityFinding("stale_data", "warning", "dataset retrieved_at is stale"))
        except ValueError:
            findings.append(DataQualityFinding("stale_data", "error", "retrieved_at is not valid UTC"))
        severities = {finding.severity for finding in findings}
        status = DataQualityStatus.FAIL if "error" in severities else DataQualityStatus.PASS_WITH_WARNINGS if "warning" in severities else DataQualityStatus.PASS
        return DataQualityReport(f"quality:{dataset.dataset_id}:{uuid4().hex}", dataset.dataset_id, status, tuple(findings), utc_now())


class SQLiteDatasetRegistry:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put_dataset(self, dataset: MarketDataset, quality: DataQualityReport) -> bool:
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT INTO market_datasets(dataset_id, fingerprint, source, symbols_json, timeframe, start_date, end_date, checksum, quality_status, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        dataset.dataset_id,
                        dataset.fingerprint,
                        dataset.metadata.source,
                        _json([symbol.symbol for symbol in dataset.symbols]),
                        dataset.metadata.timeframe,
                        dataset.metadata.start_date,
                        dataset.metadata.end_date,
                        dataset.checksum,
                        quality.status.value,
                        _json(dataset.to_json()),
                        quality.generated_at,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_by_fingerprint(self, fingerprint: str) -> MarketDataset | None:
        row = self._connection.execute("SELECT payload_json FROM market_datasets WHERE fingerprint = ?", (fingerprint,)).fetchone()
        return _dataset_from_json(json.loads(str(row[0]))) if row else None

    def list_datasets(self) -> tuple[MarketDataset, ...]:
        rows = self._connection.execute("SELECT payload_json FROM market_datasets ORDER BY created_at, dataset_id").fetchall()
        return tuple(_dataset_from_json(json.loads(str(row[0]))) for row in rows)


@dataclass(frozen=True)
class StrategyRule:
    field: str
    operator: str
    value: float | int | str | bool

    def __post_init__(self) -> None:
        if self.operator not in {">", ">=", "<", "<=", "==", "crosses_above", "crosses_below"}:
            raise ValueError("unsupported strategy rule operator")

    def to_json(self) -> dict[str, object]:
        return {"field": self.field, "operator": self.operator, "value": self.value}


@dataclass(frozen=True)
class StrategySpec:
    spec_id: str
    version: int
    name: str
    entry_rules: tuple[StrategyRule, ...]
    exit_rules: tuple[StrategyRule, ...]
    filters: tuple[StrategyRule, ...]
    position_sizing: dict[str, float | int | str | bool]
    stop_loss: dict[str, float | int | str | bool]
    take_profit: dict[str, float | int | str | bool]
    universe: tuple[str, ...]
    max_positions: int
    rebalance: str
    timeframe: str

    def __post_init__(self) -> None:
        _validate_id(self.spec_id, "spec_id")
        if self.version != REAL_RESEARCH_SCHEMA_VERSION:
            raise ValueError("unsupported StrategySpec version")
        if self.max_positions < 1 or self.max_positions > 100:
            raise ValueError("max_positions must be bounded")
        object.__setattr__(self, "entry_rules", tuple(self.entry_rules))
        object.__setattr__(self, "exit_rules", tuple(self.exit_rules))
        object.__setattr__(self, "filters", tuple(self.filters))
        object.__setattr__(self, "universe", tuple(sorted(self.universe)))

    @property
    def fingerprint(self) -> str:
        return _sha(self.to_json())

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": REAL_RESEARCH_SCHEMA_VERSION,
            "spec_id": self.spec_id,
            "version": self.version,
            "name": self.name,
            "entry_rules": [item.to_json() for item in self.entry_rules],
            "exit_rules": [item.to_json() for item in self.exit_rules],
            "filters": [item.to_json() for item in self.filters],
            "position_sizing": dict(sorted(self.position_sizing.items())),
            "stop_loss": dict(sorted(self.stop_loss.items())),
            "take_profit": dict(sorted(self.take_profit.items())),
            "universe": list(self.universe),
            "max_positions": self.max_positions,
            "rebalance": self.rebalance,
            "timeframe": self.timeframe,
        }


@dataclass(frozen=True)
class BacktestStrategySpec:
    strategy_spec: StrategySpec

    def to_json(self) -> dict[str, object]:
        return self.strategy_spec.to_json()


@dataclass(frozen=True)
class BacktestDatasetReference:
    dataset_id: str
    dataset_fingerprint: str

    def to_json(self) -> dict[str, object]:
        return {"dataset_id": self.dataset_id, "dataset_fingerprint": self.dataset_fingerprint}


@dataclass(frozen=True)
class BacktestExecutionAssumptions:
    commission: float
    tax: float
    slippage: float
    engine_name: str = "fixture-external-engine"
    engine_version: str = "v1"

    def __post_init__(self) -> None:
        if min(self.commission, self.tax, self.slippage) < 0:
            raise ValueError("cost assumptions must be non-negative")

    @property
    def fingerprint(self) -> str:
        return _sha(self.to_json())

    def to_json(self) -> dict[str, object]:
        return {"commission": self.commission, "tax": self.tax, "slippage": self.slippage, "engine_name": self.engine_name, "engine_version": self.engine_version}


@dataclass(frozen=True)
class BacktestRequest:
    request_id: str
    strategy: BacktestStrategySpec
    dataset: BacktestDatasetReference
    assumptions: BacktestExecutionAssumptions
    created_at: str
    requested_by: str

    @property
    def fingerprint(self) -> str:
        return _sha({"strategy": self.strategy.to_json(), "dataset": self.dataset.to_json(), "assumptions": self.assumptions.to_json(), "request_version": REAL_RESEARCH_SCHEMA_VERSION})

    def to_json(self) -> dict[str, object]:
        return {"schema_version": REAL_RESEARCH_SCHEMA_VERSION, "request_id": self.request_id, "strategy": self.strategy.to_json(), "dataset": self.dataset.to_json(), "assumptions": self.assumptions.to_json(), "created_at": self.created_at, "requested_by": self.requested_by, "fingerprint": self.fingerprint}


@dataclass(frozen=True)
class BacktestTrade:
    trade_id: str
    symbol: str
    entry_at: str
    exit_at: str
    quantity: float
    pnl: float

    def to_json(self) -> dict[str, object]:
        return self.__dict__


@dataclass(frozen=True)
class BacktestEquityPoint:
    timestamp: str
    equity: float

    def to_json(self) -> dict[str, object]:
        return self.__dict__


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    cagr: float
    mdd: float
    win_rate: float
    profit_factor: float
    trade_count: int
    average_trade: float
    exposure: float
    turnover: float

    def to_json(self) -> dict[str, object]:
        return self.__dict__


@dataclass(frozen=True)
class BacktestResult:
    result_id: str
    request_id: str
    status: BacktestRunStatus
    source: BacktestResultSource
    metrics: BacktestMetrics
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[BacktestEquityPoint, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    provenance: dict[str, object]
    generated_at: str

    @property
    def fingerprint(self) -> str:
        return _sha({"request_id": self.request_id, "provenance": self.provenance, "metrics": self.metrics.to_json(), "result_version": REAL_RESEARCH_SCHEMA_VERSION})

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": REAL_RESEARCH_SCHEMA_VERSION,
            "result_id": self.result_id,
            "request_id": self.request_id,
            "status": self.status.value,
            "source": self.source.value,
            "metrics": self.metrics.to_json(),
            "trades": [item.to_json() for item in self.trades],
            "equity_curve": [item.to_json() for item in self.equity_curve],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "provenance": dict(sorted(self.provenance.items())),
            "generated_at": self.generated_at,
            "fingerprint": self.fingerprint,
        }


class ExternalBacktestAdapter(Protocol):
    def run(self, request: BacktestRequest, dataset: MarketDataset) -> BacktestResult: ...
    def health(self) -> tuple[bool, str]: ...


class DeterministicExternalBacktestAdapter:
    def __init__(self, *, fail: bool = False, timeout: bool = False, malformed: bool = False, supported_engine: bool = True) -> None:
        self._fail = fail
        self._timeout = timeout
        self._malformed = malformed
        self._supported_engine = supported_engine

    def health(self) -> tuple[bool, str]:
        return self._supported_engine, "fixture external backtest adapter"

    def run(self, request: BacktestRequest, dataset: MarketDataset) -> BacktestResult:
        if not self._supported_engine:
            return _backtest_failure(request, BacktestRunStatus.REJECTED, ("unsupported engine",))
        if self._timeout:
            return _backtest_failure(request, BacktestRunStatus.TIMEOUT, ("adapter timeout",))
        if self._fail:
            return _backtest_failure(request, BacktestRunStatus.FAILED, ("adapter failure",))
        if self._malformed:
            return _backtest_failure(request, BacktestRunStatus.FAILED, ("malformed response",))
        bars = dataset.bars
        total_return = ((bars[-1].close - bars[0].close) / bars[0].close) if len(bars) > 1 else 0.0
        cost = request.assumptions.commission + request.assumptions.tax + request.assumptions.slippage
        adjusted = max(-0.95, total_return - cost * 4)
        metrics = BacktestMetrics(round(adjusted, 6), round(adjusted * 0.75, 6), 0.08, 0.56, 1.42, max(4, len(bars) // 3), round(adjusted / max(1, len(bars) // 3), 6), 0.55, 1.2)
        provenance = {
            "engine_name": request.assumptions.engine_name,
            "engine_version": request.assumptions.engine_version,
            "dataset_id": dataset.dataset_id,
            "dataset_fingerprint": dataset.fingerprint,
            "strategy_spec_version": request.strategy.strategy_spec.version,
            "strategy_fingerprint": request.strategy.strategy_spec.fingerprint,
            "cost_assumptions": request.assumptions.to_json(),
            "fixture_backed": dataset.metadata.fixture_backed,
            "run_timestamp": utc_now(),
        }
        return BacktestResult(f"real-backtest-result:{request.fingerprint}", request.request_id, BacktestRunStatus.COMPLETED, BacktestResultSource.FIXTURE, metrics, _fixture_trades(dataset), _fixture_equity(dataset), ("fixture adapter; external engine not invoked",), (), provenance, utc_now())


class SQLiteRealResearchRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put_strategy_spec(self, spec: StrategySpec, created_at: str | None = None) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO strategy_specs(spec_id, version, fingerprint, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (spec.spec_id, spec.version, spec.fingerprint, _json(spec.to_json()), created_at or utc_now()),
            )

    def put_backtest(self, request: BacktestRequest, result: BacktestResult) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR IGNORE INTO backtest_runs(run_id, request_fingerprint, strategy_fingerprint, dataset_fingerprint, engine_name, engine_version, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (request.request_id, request.fingerprint, request.strategy.strategy_spec.fingerprint, request.dataset.dataset_fingerprint, request.assumptions.engine_name, request.assumptions.engine_version, _json(request.to_json()), request.created_at),
            )
            self._connection.execute(
                "INSERT OR REPLACE INTO real_backtest_results(result_id, run_id, status, source, result_fingerprint, payload_json, generated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (result.result_id, request.request_id, result.status.value, result.source.value, result.fingerprint, _json(result.to_json()), result.generated_at),
            )

    def get_result(self, result_id: str) -> BacktestResult:
        row = self._connection.execute("SELECT payload_json FROM real_backtest_results WHERE result_id = ?", (result_id,)).fetchone()
        if row is None:
            raise KeyError(result_id)
        return backtest_result_from_json(json.loads(str(row[0])))


@dataclass(frozen=True)
class BacktestComparison:
    baseline_result_id: str
    challenger_result_id: str
    changed_conditions: tuple[str, ...]
    delta: dict[str, float]

    def to_json(self) -> dict[str, object]:
        return {"baseline_result_id": self.baseline_result_id, "challenger_result_id": self.challenger_result_id, "changed_conditions": list(self.changed_conditions), "delta": dict(sorted(self.delta.items()))}


class BacktestComparator:
    def compare(self, baseline: BacktestResult, challenger: BacktestResult) -> BacktestComparison:
        changed = []
        for key in ("dataset_fingerprint", "strategy_fingerprint", "engine_version", "cost_assumptions"):
            if baseline.provenance.get(key) != challenger.provenance.get(key):
                changed.append(key)
        delta = {
            "total_return": challenger.metrics.total_return - baseline.metrics.total_return,
            "cagr": challenger.metrics.cagr - baseline.metrics.cagr,
            "mdd": challenger.metrics.mdd - baseline.metrics.mdd,
            "profit_factor": challenger.metrics.profit_factor - baseline.metrics.profit_factor,
        }
        return BacktestComparison(baseline.result_id, challenger.result_id, tuple(changed), {k: round(v, 6) for k, v in delta.items()})


@dataclass(frozen=True)
class RealResearchRequest:
    request_id: str
    symbol: str
    start_date: str
    end_date: str
    strategy_family: str = "turtle_breakout"


@dataclass(frozen=True)
class RealResearchReport:
    report_id: str
    dataset: MarketDataset
    data_quality: DataQualityReport
    strategy_spec: StrategySpec
    backtest_request: BacktestRequest
    backtest_result: BacktestResult
    critique: dict[str, object]
    quality: dict[str, object]
    comparison: BacktestComparison
    final_summary: str
    warnings: tuple[str, ...]
    generated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": REAL_RESEARCH_SCHEMA_VERSION,
            "report_id": self.report_id,
            "dataset": self.dataset.to_json(),
            "data_quality": self.data_quality.to_json(),
            "strategy_spec": self.strategy_spec.to_json(),
            "backtest_request": self.backtest_request.to_json(),
            "backtest_result": self.backtest_result.to_json(),
            "critique": self.critique,
            "quality": self.quality,
            "comparison": self.comparison.to_json(),
            "final_summary": self.final_summary,
            "warnings": list(self.warnings),
            "generated_at": self.generated_at,
        }


class RealResearchGateway:
    def __init__(self, *, provider: MarketDataProvider | None = None, adapter: ExternalBacktestAdapter | None = None, connection: sqlite3.Connection | None = None) -> None:
        self._provider = provider or FixtureMarketDataProvider()
        self._adapter = adapter or DeterministicExternalBacktestAdapter()
        self._connection = connection

    def run(self, request: RealResearchRequest, *, generated_at: str | None = None) -> RealResearchReport:
        at = generated_at or utc_now()
        dataset = self._provider.fetch_bars(request.symbol, start_date=request.start_date, end_date=request.end_date)
        quality = self._provider.validate_dataset(dataset)
        spec = turtle_strategy_spec(symbol=request.symbol)
        assumptions = BacktestExecutionAssumptions(commission=0.00015, tax=0.0018, slippage=0.0005)
        bt_request = BacktestRequest(f"real-research:{request.request_id}", BacktestStrategySpec(spec), BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint), assumptions, at, "gaon")
        result = self._adapter.run(bt_request, dataset) if quality.status is not DataQualityStatus.FAIL else _backtest_failure(bt_request, BacktestRunStatus.REJECTED, ("data quality failed",))
        baseline_request = BacktestRequest(f"real-research:{request.request_id}:baseline", BacktestStrategySpec(spec), BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint), BacktestExecutionAssumptions(0.0, 0.0, 0.0), at, "gaon")
        baseline = DeterministicExternalBacktestAdapter().run(baseline_request, dataset)
        comparison = BacktestComparator().compare(baseline, result)
        candidate = _candidate_from_backtest(spec, dataset, result, request)
        critique = ResearchCritic().evaluate(candidate, created_at=at).to_json()
        score = ResearchQualityScorer().score(candidate, created_at=at).to_json()
        warnings = ("fixture_backed=true unless an approved external provider is configured", "no live order, Champion promotion, deployment, shell, arbitrary SQL, or private repository dependency")
        report = RealResearchReport(f"real-research-report:{request.request_id}", dataset, quality, spec, bt_request, result, critique, score, comparison, f"Real research gateway completed with source={result.source.value} quality={quality.status.value}.", warnings, at)
        if self._connection is not None:
            registry = SQLiteDatasetRegistry(self._connection)
            registry.put_dataset(dataset, quality)
            repository = SQLiteRealResearchRepository(self._connection)
            repository.put_strategy_spec(spec, at)
            repository.put_backtest(bt_request, result)
            with self._connection:
                self._connection.execute(
                    "INSERT OR REPLACE INTO real_research_reports(report_id, request_id, payload_json, generated_at) VALUES (?, ?, ?, ?)",
                    (report.report_id, request.request_id, _json(report.to_json()), at),
                )
        return report


def turtle_strategy_spec(symbol: str = "005930") -> StrategySpec:
    return StrategySpec(
        "strategy-spec:turtle-breakout:v1",
        REAL_RESEARCH_SCHEMA_VERSION,
        "Turtle Breakout Fixture",
        (StrategyRule("close", ">", "high_20d"), StrategyRule("close", ">", "ma20"), StrategyRule("ma20", ">", "ma60")),
        (StrategyRule("close", "<", "low_10d"),),
        (StrategyRule("volume", ">=", "volume_ma20"),),
        {"method": "fixed_fractional", "risk_pct": 1.0},
        {"type": "percent", "value": 5.0},
        {"type": "none", "value": 0.0},
        (symbol.upper(),),
        2,
        "daily",
        "daily",
    )


def market_data_status_payload(connection: sqlite3.Connection) -> dict[str, object]:
    count = connection.execute("SELECT COUNT(*) FROM market_datasets").fetchone()[0]
    return {"provider": "sqlite:market_datasets", "datasets": int(count), "fixture_status": "available", "real_data_status": "optional_provider_not_configured"}


def dataset_lookup_payload(connection: sqlite3.Connection, fingerprint: str | None = None) -> dict[str, object]:
    registry = SQLiteDatasetRegistry(connection)
    if fingerprint:
        dataset = registry.get_by_fingerprint(fingerprint)
        return {"dataset": dataset.to_json() if dataset else None}
    return {"datasets": [item.to_json() for item in registry.list_datasets()[:10]]}


def data_quality_payload(symbol: str = "005930") -> dict[str, object]:
    dataset = FixtureMarketDataProvider().fetch_bars(symbol, start_date="2026-07-01", end_date="2026-07-10")
    return {"dataset": dataset.to_json(), "quality": DataQualityEngine().validate(dataset).to_json()}


def backtest_strategy_payload(symbol: str = "005930") -> dict[str, object]:
    report = RealResearchGateway().run(RealResearchRequest(f"tool:{uuid4().hex}", symbol, "2026-07-01", "2026-07-10"))
    return {"request": report.backtest_request.to_json(), "result": report.backtest_result.to_json(), "automatic_promotion": False}


def compare_backtests_payload() -> dict[str, object]:
    provider = FixtureMarketDataProvider()
    dataset = provider.fetch_bars("005930", start_date="2026-07-01", end_date="2026-07-10")
    spec = turtle_strategy_spec("005930")
    baseline_request = BacktestRequest("compare:baseline", BacktestStrategySpec(spec), BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint), BacktestExecutionAssumptions(0.0, 0.0, 0.0), utc_now(), "tool")
    challenger_request = BacktestRequest("compare:challenger", BacktestStrategySpec(spec), BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint), BacktestExecutionAssumptions(0.00015, 0.0018, 0.0005), utc_now(), "tool")
    adapter = DeterministicExternalBacktestAdapter()
    return {"comparison": BacktestComparator().compare(adapter.run(baseline_request, dataset), adapter.run(challenger_request, dataset)).to_json(), "automatic_promotion": False}


def backtest_result_from_json(payload: dict[str, object]) -> BacktestResult:
    if int(payload.get("schema_version", -1)) != REAL_RESEARCH_SCHEMA_VERSION:
        raise ValueError("unsupported backtest result schema")
    metrics = BacktestMetrics(**payload["metrics"])  # type: ignore[arg-type]
    trades = tuple(BacktestTrade(**item) for item in payload["trades"])  # type: ignore[index]
    equity = tuple(BacktestEquityPoint(**item) for item in payload["equity_curve"])  # type: ignore[index]
    return BacktestResult(str(payload["result_id"]), str(payload["request_id"]), BacktestRunStatus(str(payload["status"])), BacktestResultSource(str(payload["source"])), metrics, trades, equity, tuple(str(item) for item in payload["warnings"]), tuple(str(item) for item in payload["errors"]), dict(payload["provenance"]), str(payload["generated_at"]))  # type: ignore[arg-type]


def _candidate_from_backtest(spec: StrategySpec, dataset: MarketDataset, result: BacktestResult, request: RealResearchRequest) -> StrategyCandidate:
    metrics = {
        "in_sample_sharpe": 1.1,
        "out_of_sample_sharpe": max(0.1, result.metrics.profit_factor - 0.3),
        "sample_size": len(dataset.bars) * 20,
        "trade_count": result.metrics.trade_count,
        "walk_forward_stability": 0.68,
        "monte_carlo_robustness": 0.66,
        "max_drawdown": result.metrics.mdd,
        "parameter_stability": 0.7,
        "regime_dependency": 0.45,
        "liquidity_score": 0.75,
        "feature_complexity": 0.35,
        "profit_factor": result.metrics.profit_factor,
    }
    return StrategyCandidate(spec.spec_id, request.strategy_family, dataset.metadata.market, dataset.metadata.timeframe, spec.name, {"max_positions": spec.max_positions}, metrics, ("breakout", "volume_filter"), ("bull", "sideways"), (dataset.metadata.source, result.source.value))


def _backtest_failure(request: BacktestRequest, status: BacktestRunStatus, errors: tuple[str, ...]) -> BacktestResult:
    return BacktestResult(f"real-backtest-result:{request.fingerprint}", request.request_id, status, BacktestResultSource.FIXTURE, BacktestMetrics(0.0, 0.0, 1.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0), (), (), (), errors, {"engine_name": request.assumptions.engine_name, "engine_version": request.assumptions.engine_version, "dataset_id": request.dataset.dataset_id, "dataset_fingerprint": request.dataset.dataset_fingerprint, "strategy_fingerprint": request.strategy.strategy_spec.fingerprint, "cost_assumptions": request.assumptions.to_json(), "fixture_backed": True, "run_timestamp": utc_now()}, utc_now())


def _fixture_trades(dataset: MarketDataset) -> tuple[BacktestTrade, ...]:
    bars = dataset.bars
    if len(bars) < 2:
        return ()
    return (BacktestTrade("trade:fixture:1", bars[0].symbol, bars[0].timestamp, bars[-1].timestamp, 10.0, round((bars[-1].close - bars[0].close) * 10.0, 4)),)


def _fixture_equity(dataset: MarketDataset) -> tuple[BacktestEquityPoint, ...]:
    if not dataset.bars:
        return ()
    start = dataset.bars[0].close
    return tuple(BacktestEquityPoint(bar.timestamp, round(1_000_000 * (bar.close / start), 4)) for bar in dataset.bars)


def _dataset_from_json(payload: dict[str, object]) -> MarketDataset:
    if int(payload.get("schema_version", -1)) != REAL_RESEARCH_SCHEMA_VERSION:
        raise ValueError("unsupported dataset schema")
    metadata = MarketDataMetadata(**{k: v for k, v in payload["metadata"].items() if k != "schema_version"})  # type: ignore[union-attr]
    symbols = tuple(MarketSymbol(**{k: v for k, v in item.items() if k != "schema_version"}) for item in payload["symbols"])  # type: ignore[index]
    bars = tuple(MarketBar(**item) for item in payload["bars"])  # type: ignore[index]
    actions = tuple(CorporateAction(**item) for item in payload.get("corporate_actions", ()))  # type: ignore[arg-type]
    return MarketDataset(str(payload["dataset_id"]), symbols, bars, metadata, actions)


def _date_range(start: str, end: str) -> list[str]:
    _validate_date(start)
    _validate_date(end)
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    days = []
    current = s
    while current <= e:
        days.append(current.date().isoformat())
        current += timedelta(days=1)
    return days


def _validate_date(value: str) -> None:
    if DATE_ONLY.fullmatch(value) is None:
        raise ValueError("date must use YYYY-MM-DD")


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC")


def _validate_id(value: str, label: str) -> None:
    if SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")


def _sha(payload: dict[str, object]) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
