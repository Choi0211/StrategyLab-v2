"""KRX real-research pipeline foundation for Sprint 111-120.

The implementation is deterministic, advisory, and read-only. It can run on
fixture-backed KRX-shaped data for tests, but it never labels fixture data as
real and never places orders, promotes Champions, executes generated code, or
uses a private repository.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import Enum
import hashlib
import json
import os
import re
import sqlite3
from typing import Callable, Protocol
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import uuid4
from zoneinfo import ZoneInfo

from gaon.research.real_research import (
    DataQualityEngine,
    DataQualityFinding,
    DataQualityReport,
    DataQualityStatus,
    MarketBar,
    MarketDataMetadata,
    MarketDataset,
    MarketSymbol,
    SQLiteDatasetRegistry,
    TradingCalendar,
)
from gaon.research.self_improving import ResearchMemoryEntry, SQLiteResearchMemoryRepository


KRX_REAL_PIPELINE_SCHEMA_VERSION = 1
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
YAHOO_CHART_ENDPOINT = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HttpOpener = Callable[[Request, float], object]
ALLOWED_RELEASE_WARNING_CODES = frozenset({"provider_gap", "provider_ohlc_anomaly", "provider_zero_volume_anomaly"})
KRX_WON_FLOAT_DRIFT_TOLERANCE = 0.01


class FieldProvenance(str, Enum):
    USER_PROVIDED = "user_provided"
    DEFAULT = "default"
    DERIVED = "derived"
    FIXTURE = "fixture"
    REAL = "real"
    RESEARCH_CANDIDATE = "research_candidate"


class MarketDataAvailability(str, Enum):
    REAL = "real"
    FIXTURE = "fixture"
    REAL_DATA_UNAVAILABLE = "real_data_unavailable"


@dataclass(frozen=True)
class ProvenancedValue:
    value: float | int | str | bool
    provenance: FieldProvenance

    def to_json(self) -> dict[str, object]:
        return {"value": self.value, "provenance": self.provenance.value}


@dataclass(frozen=True)
class CanonicalStrategySpec:
    spec_id: str
    symbol: str
    entry: dict[str, ProvenancedValue]
    exit: dict[str, ProvenancedValue]
    filters: dict[str, ProvenancedValue]
    source_text: str
    created_at: str

    @property
    def fingerprint(self) -> str:
        return _sha(self.to_json(include_fingerprint=False))

    def to_json(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload = {
            "schema_version": KRX_REAL_PIPELINE_SCHEMA_VERSION,
            "spec_id": self.spec_id,
            "symbol": self.symbol,
            "entry": {key: value.to_json() for key, value in sorted(self.entry.items())},
            "exit": {key: value.to_json() for key, value in sorted(self.exit.items())},
            "filters": {key: value.to_json() for key, value in sorted(self.filters.items())},
            "source_text": self.source_text,
            "created_at": self.created_at,
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True)
class BacktestExecutionAssumptionSet:
    commission: ProvenancedValue
    tax: ProvenancedValue
    slippage: ProvenancedValue
    execution_timing: ProvenancedValue
    position_sizing: ProvenancedValue
    initial_capital: ProvenancedValue

    def to_json(self) -> dict[str, object]:
        return {
            "commission": self.commission.to_json(),
            "tax": self.tax.to_json(),
            "slippage": self.slippage.to_json(),
            "execution_timing": self.execution_timing.to_json(),
            "position_sizing": self.position_sizing.to_json(),
            "initial_capital": self.initial_capital.to_json(),
        }


@dataclass(frozen=True)
class RealBacktestTrade:
    trade_id: str
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl: float
    return_pct: float
    exit_reason: str

    def to_json(self) -> dict[str, object]:
        return self.__dict__


@dataclass(frozen=True)
class RealPerformanceMetrics:
    total_return: float
    cagr: float | None
    mdd: float
    sharpe: float | None
    win_rate: float | None
    profit_factor: float | None
    trade_count: int
    average_trade: float | None
    average_win: float | None
    average_loss: float | None
    payoff_ratio: float | None
    exposure: float
    ending_equity: float
    expectancy: float | None
    longest_losing_streak: int

    def to_json(self) -> dict[str, object]:
        return self.__dict__


@dataclass(frozen=True)
class RealBacktestResult:
    result_id: str
    run_id: str
    status: str
    source: MarketDataAvailability
    strategy: CanonicalStrategySpec
    dataset_id: str
    dataset_fingerprint: str
    assumptions: BacktestExecutionAssumptionSet
    metrics: RealPerformanceMetrics
    trades: tuple[RealBacktestTrade, ...]
    equity_curve: tuple[dict[str, float | str], ...]
    warnings: tuple[str, ...]
    generated_at: str

    @property
    def fingerprint(self) -> str:
        return _sha(self.to_json(include_fingerprint=False))

    def to_json(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload = {
            "schema_version": KRX_REAL_PIPELINE_SCHEMA_VERSION,
            "result_id": self.result_id,
            "run_id": self.run_id,
            "status": self.status,
            "source": self.source.value,
            "strategy": self.strategy.to_json(),
            "dataset_id": self.dataset_id,
            "dataset_fingerprint": self.dataset_fingerprint,
            "assumptions": self.assumptions.to_json(),
            "metrics": self.metrics.to_json(),
            "trades": [trade.to_json() for trade in self.trades],
            "equity_curve": [dict(point) for point in self.equity_curve],
            "warnings": list(self.warnings),
            "generated_at": self.generated_at,
            "automatic_order": False,
            "automatic_champion_promotion": False,
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True)
class ValidationReport:
    validation_id: str
    train_metrics: RealPerformanceMetrics
    test_metrics: RealPerformanceMetrics
    passed: bool
    findings: tuple[str, ...]
    generated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "validation_id": self.validation_id,
            "train_metrics": self.train_metrics.to_json(),
            "test_metrics": self.test_metrics.to_json(),
            "passed": self.passed,
            "findings": list(self.findings),
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True)
class CriticFinding:
    code: str
    message_ko: str
    evidence_refs: tuple[str, ...]
    severity: str

    def to_json(self) -> dict[str, object]:
        return {"code": self.code, "message_ko": self.message_ko, "evidence_refs": list(self.evidence_refs), "severity": self.severity}


@dataclass(frozen=True)
class ImprovementCandidate:
    candidate_id: str
    parent_strategy_id: str
    strategy: CanonicalStrategySpec
    changed_fields: tuple[str, ...]
    reason_ko: str
    provenance: FieldProvenance
    backtest_result: RealBacktestResult | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "parent_strategy_id": self.parent_strategy_id,
            "strategy": self.strategy.to_json(),
            "changed_fields": list(self.changed_fields),
            "reason_ko": self.reason_ko,
            "provenance": self.provenance.value,
            "backtest_result": self.backtest_result.to_json() if self.backtest_result else None,
        }


@dataclass(frozen=True)
class CandidateComparison:
    original_result_id: str
    rows: tuple[dict[str, object], ...]

    def to_json(self) -> dict[str, object]:
        return {"original_result_id": self.original_result_id, "rows": [dict(row) for row in self.rows]}


@dataclass(frozen=True)
class RealAutonomousResearchReport:
    report_id: str
    run_id: str
    request_text: str
    dataset: MarketDataset
    quality: DataQualityReport
    strategy: CanonicalStrategySpec
    assumptions: BacktestExecutionAssumptionSet
    backtest: RealBacktestResult
    validation: ValidationReport
    critic_findings: tuple[CriticFinding, ...]
    candidates: tuple[ImprovementCandidate, ...]
    comparison: CandidateComparison
    memory_id: str | None
    korean_report: str
    generated_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": KRX_REAL_PIPELINE_SCHEMA_VERSION,
            "report_id": self.report_id,
            "run_id": self.run_id,
            "request_text": self.request_text,
            "dataset": self.dataset.to_json(),
            "quality": self.quality.to_json(),
            "strategy": self.strategy.to_json(),
            "assumptions": self.assumptions.to_json(),
            "backtest": self.backtest.to_json(),
            "validation": self.validation.to_json(),
            "critic_findings": [finding.to_json() for finding in self.critic_findings],
            "candidates": [candidate.to_json() for candidate in self.candidates],
            "comparison": self.comparison.to_json(),
            "memory_id": self.memory_id,
            "korean_report": self.korean_report,
            "generated_at": self.generated_at,
            "automatic_order": False,
            "automatic_champion_promotion": False,
        }


class KRXHistoricalDataProvider(Protocol):
    source: str

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset: ...


class KRXRealMarketDataProvider:
    """Public-data adapter boundary.

    The production network fetch is intentionally not implemented in this
    public repository. It reports explicit unavailability instead of silently
    substituting fixtures.
    """

    source = "krx-public"

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        raise RealMarketDataUnavailable("real_data_unavailable: configure an approved public KRX fetcher")


class YahooKRXHistoricalDataProvider:
    """Public historical OHLCV provider for KRX-listed symbols.

    Yahoo's chart endpoint is used as a free public historical-data source. The
    provider is explicit about provenance and never falls back to fixtures.
    """

    source = "real:yahoo-chart"

    def __init__(self, *, opener: HttpOpener | None = None, timeout_seconds: float = 20.0) -> None:
        self._opener = opener or _default_urlopen
        self._timeout = timeout_seconds

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        _validate_date(start_date)
        _validate_date(end_date)
        if timeframe != "daily":
            raise RealMarketDataUnavailable("real_data_unavailable: only daily timeframe is supported")
        yahoo_symbol = _to_yahoo_symbol(symbol)
        period1 = int(datetime.fromisoformat(start_date).replace(tzinfo=UTC).timestamp())
        period2 = int((datetime.fromisoformat(end_date) + timedelta(days=1)).replace(tzinfo=UTC).timestamp())
        query = urlencode({"period1": period1, "period2": period2, "interval": "1d", "events": "history", "includeAdjustedClose": "true"})
        url = f"{YAHOO_CHART_ENDPOINT.format(symbol=yahoo_symbol)}?{query}"
        request = Request(url, headers={"User-Agent": "StrategyLab-v2 Gaon research data check"})
        try:
            response = self._opener(request, self._timeout)
            raw = response.read().decode("utf-8")
            payload = json.loads(raw)
        except Exception as exc:  # noqa: BLE001 - converted to explicit provider state.
            raise RealMarketDataUnavailable(f"real_data_unavailable: {exc.__class__.__name__}") from exc
        bars = _parse_yahoo_chart_payload(payload, symbol.upper())
        if not bars:
            raise RealMarketDataUnavailable("real_data_unavailable: provider returned no usable bars")
        filtered = tuple(bar for bar in bars if start_date <= bar.timestamp <= end_date)
        if not filtered:
            raise RealMarketDataUnavailable("real_data_unavailable: no bars in requested period")
        metadata = MarketDataMetadata(self.source, "KOSPI" if yahoo_symbol.endswith(".KS") else "KOSDAQ", timeframe, filtered[0].timestamp, filtered[-1].timestamp, True, utc_now(), False)
        dataset_id = f"dataset:real:{self.source}:{symbol.upper()}:{timeframe}:{filtered[0].timestamp}:{filtered[-1].timestamp}"
        return MarketDataset(dataset_id, (MarketSymbol(symbol.upper(), symbol.upper(), metadata.market),), filtered, metadata)


class RealMarketDataUnavailable(RuntimeError):
    """Raised when real public market data is not configured."""


class KRXTradingCalendar(TradingCalendar):
    """Deterministic KRX daily calendar for quality checks.

    This local calendar models KRX market closures with explicit annual
    overrides for government holidays, election days, Labor Day, temporary
    holidays, KRX-designated closures, and year-end exchange holidays. It is
    intentionally replaceable by an official KRX calendar provider later.
    """

    market = "KRX"
    annual_closed_dates = {
        2021: frozenset(
            {
                "2021-01-01",
                "2021-02-11",
                "2021-02-12",
                "2021-03-01",
                "2021-05-05",
                "2021-05-19",
                "2021-08-16",
                "2021-09-20",
                "2021-09-21",
                "2021-09-22",
                "2021-10-04",
                "2021-10-11",
                "2021-12-31",
            }
        ),
        2022: frozenset(
            {
                "2022-01-31",
                "2022-02-01",
                "2022-02-02",
                "2022-03-01",
                "2022-03-09",
                "2022-05-05",
                "2022-06-01",
                "2022-06-06",
                "2022-08-15",
                "2022-09-09",
                "2022-09-12",
                "2022-10-03",
                "2022-10-10",
                "2022-12-30",
            }
        ),
        2023: frozenset(
            {
                "2023-01-23",
                "2023-01-24",
                "2023-03-01",
                "2023-05-01",
                "2023-05-05",
                "2023-05-29",
                "2023-06-06",
                "2023-08-15",
                "2023-09-28",
                "2023-09-29",
                "2023-10-02",
                "2023-10-03",
                "2023-10-09",
                "2023-12-25",
                "2023-12-29",
            }
        ),
        2024: frozenset(
            {
                "2024-01-01",
                "2024-02-09",
                "2024-02-12",
                "2024-03-01",
                "2024-04-10",
                "2024-05-01",
                "2024-05-06",
                "2024-05-15",
                "2024-06-06",
                "2024-08-15",
                "2024-09-16",
                "2024-09-17",
                "2024-09-18",
                "2024-10-01",
                "2024-10-03",
                "2024-10-09",
                "2024-12-25",
                "2024-12-31",
            }
        ),
        2025: frozenset(
            {
            "2025-01-01",
            "2025-01-27",
            "2025-01-28",
            "2025-01-29",
            "2025-01-30",
            "2025-03-03",
            "2025-05-01",
            "2025-05-05",
            "2025-05-06",
            "2025-06-03",
            "2025-06-06",
            "2025-08-15",
            "2025-10-03",
            "2025-10-06",
            "2025-10-07",
            "2025-10-08",
            "2025-10-09",
            "2025-12-25",
            "2025-12-31",
            }
        ),
        2026: frozenset(
            {
            "2026-01-01",
            "2026-02-16",
            "2026-02-17",
            "2026-02-18",
            "2026-03-02",
            "2026-05-01",
            "2026-05-05",
            "2026-05-25",
            "2026-06-03",
            "2026-07-17",
            "2026-08-17",
            "2026-09-24",
            "2026-09-25",
            "2026-10-05",
            "2026-10-09",
            "2026-12-25",
            "2026-12-31",
            }
        ),
    }
    closed_dates = frozenset(day for days in annual_closed_dates.values() for day in days)

    def expected_open_dates(self, *, start_date: str, end_date: str) -> tuple[str, ...]:
        _validate_date(start_date)
        _validate_date(end_date)
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        dates = []
        for day in _date_range(start_date, end_date):
            current = datetime.fromisoformat(day)
            if current.weekday() >= 5 or day in self.closed_dates:
                continue
            dates.append(day)
        return tuple(dates)

    def is_open(self, day: str) -> bool:
        return day in self.expected_open_dates(start_date=day, end_date=day)


@dataclass(frozen=True)
class ProviderAnomalyPolicy:
    provider: str
    provider_gap_dates: frozenset[str]
    symbol_provider_gap_dates: dict[str, frozenset[str]]
    provider_ohlc_anomaly_dates: dict[str, frozenset[str]]
    provider_zero_volume_anomaly_dates: dict[str, frozenset[str]]
    evidence: str

    def classify_missing_date(self, day: str, *, symbol: str) -> DataQualityFinding:
        _validate_date(day)
        symbol_upper = symbol.upper()
        symbol_gaps = self.symbol_provider_gap_dates.get(symbol_upper, frozenset())
        if day in self.provider_gap_dates or day in symbol_gaps:
            return DataQualityFinding("provider_gap", "warning", f"{self.provider} missing bar on open KRX date {day}; evidence={self.evidence}")
        zero_volume_anomalies = self.provider_zero_volume_anomaly_dates.get(symbol_upper, frozenset())
        if day in zero_volume_anomalies:
            return DataQualityFinding("provider_zero_volume_anomaly", "warning", f"{self.provider} zero-volume bar for {symbol_upper} on open KRX date {day}; bar excluded from backtest input; evidence={self.evidence}")
        symbol_anomalies = self.provider_ohlc_anomaly_dates.get(symbol_upper, frozenset())
        if day in symbol_anomalies:
            return DataQualityFinding("provider_ohlc_anomaly", "warning", f"{self.provider} returned inconsistent same-index OHLC for {symbol_upper} on open KRX date {day}; bar excluded; evidence={self.evidence}")
        return DataQualityFinding("unknown_missing_trading_day", "warning", f"missing KRX trading date {day} is not explained by calendar or provider anomaly registry")

    def classify_zero_volume(self, bar: MarketBar) -> DataQualityFinding:
        symbol_upper = bar.symbol.upper()
        symbol_anomalies = self.provider_zero_volume_anomaly_dates.get(symbol_upper, frozenset())
        if bar.timestamp in symbol_anomalies:
            return DataQualityFinding("provider_zero_volume_anomaly", "warning", f"{self.provider} zero-volume bar for {symbol_upper} on open KRX date {bar.timestamp}; evidence={self.evidence}")
        return DataQualityFinding("zero_volume", "warning", f"zero volume bar requires provider review: provider={self.provider} symbol={symbol_upper} date={bar.timestamp} open={bar.open} high={bar.high} low={bar.low} close={bar.close}")


YAHOO_KRX_ANOMALY_POLICY = ProviderAnomalyPolicy(
    "real:yahoo-chart",
    frozenset({"2025-09-19"}),
    {
        "005930": frozenset({"2022-01-03", "2022-05-09"}),
    },
    {
        "005930": frozenset({"2024-10-14"}),
        "000660": frozenset({"2024-10-14"}),
        "005380": frozenset({"2024-01-15"}),
        "051910": frozenset({"2024-10-14", "2024-11-07"}),
    },
    {
        "005930": frozenset(
            {
                "2022-01-26",
                "2022-02-08",
                "2022-02-09",
                "2022-02-21",
                "2022-02-22",
                "2022-02-23",
                "2022-02-28",
                "2022-03-04",
                "2022-03-10",
                "2022-03-15",
                "2022-03-17",
            }
        ),
    },
    "multi-symbol Yahoo KRX raw chart audit: 005930,000660,005380,035420,051910; production 005930 5y inspection recorded same-index OHLC rows with volume=0/trading_value=0",
)


class KRXFixtureMarketDataProvider:
    source = "fixture"

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        _validate_date(start_date)
        _validate_date(end_date)
        if start_date > end_date:
            raise ValueError("start_date must not be after end_date")
        bars: list[MarketBar] = []
        base = 100.0
        dates = _date_range(start_date, end_date)
        for index, day in enumerate(dates):
            trend = index * 0.18
            cycle = ((index % 9) - 4) * 0.16
            jump = 4.0 if index in {65, 92} else 0.0
            close = round(base + trend + cycle + jump, 4)
            high = round(close + 0.8 + (0.4 if index in {64, 91} else 0.0), 4)
            low = round(close - 0.9, 4)
            open_ = round(close - 0.25, 4)
            volume = 900_000 + index * 4_000 + (500_000 if index in {65, 92} else 0)
            bars.append(MarketBar(day, symbol.upper(), open_, high, low, close, volume, int(volume * close)))
        metadata = MarketDataMetadata("fixture:krx-real-research", "KOSPI", timeframe, start_date, end_date, True, f"{end_date}T00:00:00Z", True)
        return MarketDataset(f"dataset:{symbol.upper()}:{timeframe}:{start_date}:{end_date}", (MarketSymbol(symbol.upper(), symbol.upper(), "KOSPI"),), tuple(bars), metadata)

    def validate_dataset(self, dataset: MarketDataset) -> DataQualityReport:
        return _validate_krx_daily_dataset(dataset, min_bars=60)


class KRXDatasetBuilder:
    def __init__(self, connection: sqlite3.Connection | None = None, provider: KRXHistoricalDataProvider | None = None) -> None:
        self._connection = connection
        self._provider = provider or KRXFixtureMarketDataProvider()

    def build(self, symbol: str, *, start_date: str, end_date: str) -> tuple[MarketDataset, DataQualityReport, bool]:
        dataset = self._provider.fetch_bars(symbol, start_date=start_date, end_date=end_date)
        dataset = _exclude_registered_provider_zero_volume_bars(dataset)
        quality = _validate_krx_daily_dataset(dataset, min_bars=60)
        inserted = False
        if self._connection is not None:
            inserted = SQLiteDatasetRegistry(self._connection).put_dataset(dataset, quality)
        return dataset, quality, inserted


class UserStrategyParser:
    def parse(self, text: str, *, symbol: str = "005930", created_at: str | None = None) -> CanonicalStrategySpec:
        normalized = text.casefold()
        entry: dict[str, ProvenancedValue] = {}
        exit_rules: dict[str, ProvenancedValue] = {}
        filters: dict[str, ProvenancedValue] = {}
        if "20" in normalized and ("고가" in text or "high" in normalized or "breakout" in normalized or "돌파" in text):
            entry["breakout_lookback"] = ProvenancedValue(20, FieldProvenance.USER_PROVIDED)
        if "ma20" in normalized or "20일" in text:
            entry["close_gt_ma20"] = ProvenancedValue(True, FieldProvenance.USER_PROVIDED)
        if "ma60" in normalized or "60일" in text:
            entry["ma20_gt_ma60"] = ProvenancedValue(True, FieldProvenance.USER_PROVIDED)
        if "거래량" in text or "volume" in normalized:
            filters["volume_gte_ma20"] = ProvenancedValue(True, FieldProvenance.USER_PROVIDED)
        if "-5" in normalized or "손절" in text or "stop" in normalized:
            exit_rules["protective_stop_pct"] = ProvenancedValue(-5.0, FieldProvenance.USER_PROVIDED)
        if "10" in normalized and ("저점" in text or "low" in normalized or "청산" in text):
            exit_rules["channel_exit_lookback"] = ProvenancedValue(10, FieldProvenance.USER_PROVIDED)
        if "breakout_lookback" not in entry:
            entry["breakout_lookback"] = ProvenancedValue(20, FieldProvenance.DEFAULT)
        if "protective_stop_pct" not in exit_rules:
            exit_rules["protective_stop_pct"] = ProvenancedValue(-5.0, FieldProvenance.DEFAULT)
        return CanonicalStrategySpec(f"canonical-strategy:{uuid4().hex}", symbol.upper(), entry, exit_rules, filters, text, created_at or utc_now())


def default_execution_assumptions() -> BacktestExecutionAssumptionSet:
    return BacktestExecutionAssumptionSet(
        ProvenancedValue(0.00015, FieldProvenance.DEFAULT),
        ProvenancedValue(0.0018, FieldProvenance.DEFAULT),
        ProvenancedValue(0.0005, FieldProvenance.DEFAULT),
        ProvenancedValue("next_close", FieldProvenance.DEFAULT),
        ProvenancedValue("single_position_all_cash", FieldProvenance.DEFAULT),
        ProvenancedValue(1_000_000.0, FieldProvenance.DEFAULT),
    )


class RuleBasedBacktestEngine:
    engine_name = "gaon-rule-backtest"
    engine_version = "v1"

    def run(self, run_id: str, strategy: CanonicalStrategySpec, dataset: MarketDataset, assumptions: BacktestExecutionAssumptionSet, *, generated_at: str | None = None) -> RealBacktestResult:
        at = generated_at or utc_now()
        bars = tuple(sorted(dataset.bars, key=lambda bar: bar.timestamp))
        if len(bars) < 61:
            return _empty_result(run_id, strategy, dataset, assumptions, "rejected", ("insufficient bars for MA60 and breakout lookback",), at)
        initial_capital = float(assumptions.initial_capital.value)
        cash = initial_capital
        quantity = 0
        entry_price = 0.0
        entry_date = ""
        entry_index = -1
        trades: list[RealBacktestTrade] = []
        equity_curve: list[dict[str, float | str]] = []
        invested_days = 0
        cost_rate = float(assumptions.commission.value) + float(assumptions.tax.value) + float(assumptions.slippage.value)
        breakout_n = int(strategy.entry["breakout_lookback"].value)
        exit_n = int(strategy.exit.get("channel_exit_lookback", ProvenancedValue(10, FieldProvenance.DEFAULT)).value)
        stop_pct = abs(float(strategy.exit["protective_stop_pct"].value)) / 100.0
        for index, bar in enumerate(bars):
            if quantity:
                invested_days += 1
            equity = cash + quantity * bar.close
            equity_curve.append({"timestamp": bar.timestamp, "equity": round(equity, 4)})
            if index < max(60, breakout_n, exit_n):
                continue
            prior = bars[:index]
            prior_high = max(item.high for item in prior[-breakout_n:])
            ma20 = sum(item.close for item in prior[-20:]) / 20
            ma60 = sum(item.close for item in prior[-60:]) / 60
            volume_ma20 = sum(item.volume for item in prior[-20:]) / 20
            prior_low = min(item.low for item in prior[-exit_n:])
            if quantity == 0:
                entry_ok = bar.close > prior_high and (not strategy.entry.get("close_gt_ma20") or bar.close > ma20) and (not strategy.entry.get("ma20_gt_ma60") or ma20 > ma60)
                volume_ok = not strategy.filters.get("volume_gte_ma20") or bar.volume >= volume_ma20
                if entry_ok and volume_ok:
                    fill = bar.close * (1.0 + cost_rate)
                    quantity = int(cash // fill)
                    if quantity > 0:
                        entry_price = fill
                        entry_date = bar.timestamp
                        entry_index = index
                        cash -= quantity * fill
            else:
                stop_price = entry_price * (1.0 - stop_pct)
                exit_reason = ""
                if bar.close <= stop_price:
                    exit_reason = "protective_stop"
                elif bar.close < prior_low:
                    exit_reason = "channel_low_exit"
                elif index == len(bars) - 1:
                    exit_reason = "end_of_dataset"
                if exit_reason:
                    fill = bar.close * (1.0 - cost_rate)
                    pnl = (fill - entry_price) * quantity
                    cash += quantity * fill
                    trades.append(RealBacktestTrade(f"trade:{run_id}:{len(trades) + 1}", bar.symbol, entry_date, bar.timestamp, round(entry_price, 4), round(fill, 4), quantity, round(pnl, 4), round((fill - entry_price) / entry_price, 6), exit_reason))
                    quantity = 0
                    entry_price = 0.0
                    entry_date = ""
                    entry_index = -1
        if quantity:
            last = bars[-1]
            fill = last.close * (1.0 - cost_rate)
            pnl = (fill - entry_price) * quantity
            cash += quantity * fill
            trades.append(RealBacktestTrade(f"trade:{run_id}:{len(trades) + 1}", last.symbol, entry_date, last.timestamp, round(entry_price, 4), round(fill, 4), quantity, round(pnl, 4), round((fill - entry_price) / entry_price, 6), "end_of_dataset"))
            equity_curve[-1] = {"timestamp": last.timestamp, "equity": round(cash, 4)}
        metrics = PerformanceMetricsCalculator().calculate(tuple(equity_curve), tuple(trades), initial_capital, bars[0].timestamp, bars[-1].timestamp, invested_days, len(bars))
        source = MarketDataAvailability.FIXTURE if dataset.metadata.fixture_backed else MarketDataAvailability.REAL
        warnings = ("fixture source disclosed; not real KRX data" if source is MarketDataAvailability.FIXTURE else "real public data source; verify freshness before decisions",)
        return RealBacktestResult(f"krx-real-backtest-result:{_sha({'run_id': run_id, 'strategy': strategy.fingerprint, 'dataset': dataset.fingerprint})}", run_id, "completed", source, strategy, dataset.dataset_id, dataset.fingerprint, assumptions, metrics, tuple(trades), tuple(equity_curve), warnings, at)


class PerformanceMetricsCalculator:
    def calculate(self, equity_curve: tuple[dict[str, float | str], ...], trades: tuple[RealBacktestTrade, ...], initial_capital: float, start_date: str, end_date: str, invested_days: int, total_days: int) -> RealPerformanceMetrics:
        ending = float(equity_curve[-1]["equity"]) if equity_curve else initial_capital
        total_return = (ending / initial_capital) - 1.0 if initial_capital else 0.0
        years = max(1.0 / 365.0, (datetime.fromisoformat(end_date) - datetime.fromisoformat(start_date)).days / 365.0)
        cagr = (ending / initial_capital) ** (1 / years) - 1 if initial_capital > 0 and ending > 0 else None
        equities = [float(point["equity"]) for point in equity_curve]
        mdd = _max_drawdown(equities)
        returns = [(equities[i] / equities[i - 1] - 1.0) for i in range(1, len(equities)) if equities[i - 1] > 0]
        sharpe = _sharpe(returns)
        wins = [trade.pnl for trade in trades if trade.pnl > 0]
        losses = [trade.pnl for trade in trades if trade.pnl < 0]
        trade_count = len(trades)
        win_rate = len(wins) / trade_count if trade_count else None
        profit_factor = sum(wins) / abs(sum(losses)) if losses else (None if not wins else float("inf"))
        avg_trade = sum(trade.pnl for trade in trades) / trade_count if trade_count else None
        avg_win = sum(wins) / len(wins) if wins else None
        avg_loss = sum(losses) / len(losses) if losses else None
        payoff = abs(avg_win / avg_loss) if avg_win is not None and avg_loss not in (None, 0) else None
        expectancy = ((win_rate or 0.0) * (avg_win or 0.0) + (1 - (win_rate or 0.0)) * (avg_loss or 0.0)) if trade_count else None
        return RealPerformanceMetrics(round(total_return, 6), round(cagr, 6) if cagr is not None else None, round(mdd, 6), round(sharpe, 6) if sharpe is not None else None, round(win_rate, 6) if win_rate is not None else None, round(profit_factor, 6) if profit_factor not in (None, float("inf")) else profit_factor, trade_count, round(avg_trade, 6) if avg_trade is not None else None, round(avg_win, 6) if avg_win is not None else None, round(avg_loss, 6) if avg_loss is not None else None, round(payoff, 6) if payoff is not None else None, round(invested_days / max(1, total_days), 6), round(ending, 4), round(expectancy, 6) if expectancy is not None else None, _longest_losing_streak(trades))


class WalkForwardValidator:
    def validate(self, strategy: CanonicalStrategySpec, dataset: MarketDataset, assumptions: BacktestExecutionAssumptionSet, *, run_id: str, generated_at: str | None = None) -> ValidationReport:
        at = generated_at or utc_now()
        bars = tuple(sorted(dataset.bars, key=lambda bar: bar.timestamp))
        split = max(70, int(len(bars) * 0.65))
        train = replace(dataset, dataset_id=f"{dataset.dataset_id}:train", bars=bars[:split])
        test = replace(dataset, dataset_id=f"{dataset.dataset_id}:test", bars=bars[split - 60 :])
        engine = RuleBasedBacktestEngine()
        train_result = engine.run(f"{run_id}:train", strategy, train, assumptions, generated_at=at)
        test_result = engine.run(f"{run_id}:test", strategy, test, assumptions, generated_at=at)
        findings = []
        if test_result.metrics.trade_count == 0:
            findings.append("표본 외 구간에서 거래가 발생하지 않았습니다.")
        if train_result.metrics.total_return > 0 and test_result.metrics.total_return < 0:
            findings.append("표본 내 성과와 표본 외 성과 방향이 다릅니다.")
        passed = not findings and test_result.status == "completed"
        return ValidationReport(f"validation:{run_id}", train_result.metrics, test_result.metrics, passed, tuple(findings), at)


class EvidenceBasedStrategyCritic:
    def critique(self, strategy: CanonicalStrategySpec, backtest: RealBacktestResult, validation: ValidationReport) -> tuple[CriticFinding, ...]:
        findings: list[CriticFinding] = [
            CriticFinding("strategy_structure", "20일 고가 돌파, MA20/MA60 필터, 거래량 필터, 손절 및 10일 저점 이탈 청산 구조는 추세 추종형 전략입니다.", (strategy.fingerprint,), "info"),
            CriticFinding("false_breakout_risk", "돌파 조건은 횡보장에서 거짓 돌파가 발생할 수 있어 거래량 확인과 표본 외 검증이 중요합니다.", (strategy.fingerprint,), "warning"),
            CriticFinding("ma_lag", "MA20/MA60 필터는 추세 확인에는 도움이 되지만 진입이 늦어질 수 있습니다.", (strategy.fingerprint,), "warning"),
            CriticFinding("giveback", "10일 저점 이탈 청산은 수익 일부를 되돌린 뒤 청산될 가능성이 있습니다.", (strategy.fingerprint,), "warning"),
        ]
        if backtest.metrics.trade_count:
            findings.append(CriticFinding("backtest_mdd", f"백테스트 결과 MDD는 {backtest.metrics.mdd:.2%}입니다.", (backtest.result_id,), "info"))
        else:
            findings.append(CriticFinding("low_trade_count", "현재 데이터 구간에서는 거래 수가 부족해 통계적 판단이 제한됩니다.", (backtest.result_id,), "warning"))
        if not validation.passed:
            findings.append(CriticFinding("oos_validation", "표본 외 검증에서 추가 확인이 필요한 항목이 있습니다.", (validation.validation_id,), "warning"))
        return tuple(findings)


class ImprovementCandidateGenerator:
    def generate(self, strategy: CanonicalStrategySpec, findings: tuple[CriticFinding, ...], *, run_id: str, created_at: str | None = None) -> tuple[ImprovementCandidate, ...]:
        at = created_at or utc_now()
        candidates: list[ImprovementCandidate] = []
        entry_a = dict(strategy.entry)
        entry_a["breakout_lookback"] = ProvenancedValue(30, FieldProvenance.RESEARCH_CANDIDATE)
        candidates.append(ImprovementCandidate(f"{run_id}:candidate:a", strategy.spec_id, replace(strategy, spec_id=f"{strategy.spec_id}:breakout30", entry=entry_a, created_at=at), ("entry.breakout_lookback",), "거짓 돌파를 줄이기 위해 돌파 기준을 20일에서 30일로 늘립니다.", FieldProvenance.RESEARCH_CANDIDATE))
        exit_b = dict(strategy.exit)
        exit_b["channel_exit_lookback"] = ProvenancedValue(15, FieldProvenance.RESEARCH_CANDIDATE)
        candidates.append(ImprovementCandidate(f"{run_id}:candidate:b", strategy.spec_id, replace(strategy, spec_id=f"{strategy.spec_id}:exit15", exit=exit_b, created_at=at), ("exit.channel_exit_lookback",), "수익 반납을 줄이는지 확인하기 위해 청산 저점 기준을 15일로 완화합니다.", FieldProvenance.RESEARCH_CANDIDATE))
        filters_c = dict(strategy.filters)
        filters_c["volume_gte_ma20"] = ProvenancedValue(False, FieldProvenance.RESEARCH_CANDIDATE)
        candidates.append(ImprovementCandidate(f"{run_id}:candidate:c", strategy.spec_id, replace(strategy, spec_id=f"{strategy.spec_id}:volume-off", filters=filters_c, created_at=at), ("filters.volume_gte_ma20",), "거래량 필터가 지나치게 선택적인지 확인하기 위해 필터 제거 후보를 비교합니다.", FieldProvenance.RESEARCH_CANDIDATE))
        return tuple(candidates)


class RealAutonomousResearchPipeline:
    def __init__(self, connection: sqlite3.Connection | None = None, provider: KRXHistoricalDataProvider | None = None) -> None:
        self._connection = connection
        self._provider = provider or KRXFixtureMarketDataProvider()

    def run(self, request_text: str, *, run_id: str | None = None, symbol: str = "005930", start_date: str = "2026-01-01", end_date: str = "2026-07-10", generated_at: str | None = None) -> RealAutonomousResearchReport:
        at = generated_at or utc_now()
        rid = run_id or f"krx-real-research:{uuid4().hex}"
        dataset, quality, _inserted = KRXDatasetBuilder(self._connection, self._provider).build(symbol, start_date=start_date, end_date=end_date)
        strategy = UserStrategyParser().parse(request_text, symbol=symbol, created_at=at)
        assumptions = default_execution_assumptions()
        engine = RuleBasedBacktestEngine()
        backtest = engine.run(f"{rid}:original", strategy, dataset, assumptions, generated_at=at) if quality.status is not DataQualityStatus.FAIL else _empty_result(f"{rid}:original", strategy, dataset, assumptions, "rejected", ("data quality failed",), at)
        validation = WalkForwardValidator().validate(strategy, dataset, assumptions, run_id=rid, generated_at=at)
        findings = EvidenceBasedStrategyCritic().critique(strategy, backtest, validation)
        raw_candidates = ImprovementCandidateGenerator().generate(strategy, findings, run_id=rid, created_at=at)
        tested_candidates = []
        for candidate in raw_candidates:
            result = engine.run(f"{rid}:{candidate.candidate_id}", candidate.strategy, dataset, assumptions, generated_at=at)
            tested_candidates.append(replace(candidate, backtest_result=result))
        comparison = _compare_candidates(backtest, tuple(tested_candidates))
        memory_id = self._persist(rid, request_text, strategy, dataset, backtest, findings, tuple(tested_candidates), comparison, at)
        korean_report = _build_korean_report(request_text, dataset, quality, strategy, assumptions, backtest, validation, findings, tuple(tested_candidates), comparison)
        report = RealAutonomousResearchReport(f"krx-real-research-report:{rid}", rid, request_text, dataset, quality, strategy, assumptions, backtest, validation, findings, tuple(tested_candidates), comparison, memory_id, korean_report, at)
        if self._connection is not None:
            with self._connection:
                self._connection.execute(
                    "INSERT OR REPLACE INTO real_research_reports(report_id, request_id, payload_json, generated_at) VALUES (?, ?, ?, ?)",
                    (report.report_id, rid, _json(report.to_json()), at),
                )
        return report

    def _persist(self, run_id: str, request_text: str, strategy: CanonicalStrategySpec, dataset: MarketDataset, backtest: RealBacktestResult, findings: tuple[CriticFinding, ...], candidates: tuple[ImprovementCandidate, ...], comparison: CandidateComparison, at: str) -> str | None:
        if self._connection is None:
            return None
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO krx_real_research_memories(memory_id, strategy_fingerprint, dataset_fingerprint, backtest_run_id, payload_json, created_at, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"krx-memory:{run_id}", strategy.fingerprint, dataset.fingerprint, backtest.run_id, _json({"strategy": strategy.to_json(), "backtest": backtest.to_json(), "findings": [item.to_json() for item in findings], "candidates": [item.to_json() for item in candidates], "comparison": comparison.to_json()}), at, backtest.source.value),
            )
        memory = ResearchMemoryEntry(
            f"memory:{run_id}",
            "breakout",
            dataset.metadata.market,
            dataset.metadata.timeframe,
            request_text,
            f"source={backtest.source.value}; total_return={backtest.metrics.total_return:.4f}; trade_count={backtest.metrics.trade_count}",
            "; ".join(item.code for item in findings),
            "; ".join(row["candidate_id"] for row in comparison.rows),
            "real_research_candidate" if backtest.source is MarketDataAvailability.REAL else "fixture_research_candidate",
            ("krx_real_research", "breakout", backtest.source.value),
            at,
            run_id,
            _sha({"strategy": strategy.fingerprint, "dataset": dataset.fingerprint, "source": backtest.source.value}),
            (backtest.result_id, dataset.dataset_id),
        )
        repo = SQLiteResearchMemoryRepository(self._connection)
        try:
            if repo.find_by_fingerprint(memory.fingerprint) is None:
                repo.add_memory(memory)
                return memory.memory_id
        except sqlite3.IntegrityError:
            return None
        return None


def krx_real_research_payload(connection: sqlite3.Connection, request_text: str, *, symbol: str = "005930") -> dict[str, object]:
    report = RealAutonomousResearchPipeline(connection, build_market_data_provider_from_env(os.environ)).run(request_text, symbol=symbol)
    return report.to_json()


def build_market_data_provider_from_env(env: dict[str, str]) -> KRXHistoricalDataProvider:
    enabled = env.get("GAON_REAL_MARKET_DATA_ENABLED", "").strip().casefold() in {"1", "true", "yes", "on"}
    provider = env.get("GAON_MARKET_DATA_PROVIDER", "fixture").strip().casefold()
    timeout = float(env.get("GAON_MARKET_DATA_TIMEOUT_SECONDS", "20"))
    if not enabled:
        return KRXFixtureMarketDataProvider()
    if provider in {"yahoo", "yahoo-chart", "yahoo_krx"}:
        return YahooKRXHistoricalDataProvider(timeout_seconds=timeout)
    raise RealMarketDataUnavailable(f"real_data_unavailable: unsupported provider {provider}")


def yahoo_krx_bar_debug(symbol: str, day: str, *, opener: HttpOpener | None = None, timeout_seconds: float = 20.0) -> dict[str, object]:
    _validate_date(day)
    yahoo_symbol = _to_yahoo_symbol(symbol)
    target = datetime.fromisoformat(day)
    start_date = (target - timedelta(days=4)).date().isoformat()
    end_date = (target + timedelta(days=4)).date().isoformat()
    period1 = int(datetime.fromisoformat(start_date).replace(tzinfo=UTC).timestamp())
    period2 = int((datetime.fromisoformat(end_date) + timedelta(days=1)).replace(tzinfo=UTC).timestamp())
    query = urlencode({"period1": period1, "period2": period2, "interval": "1d", "events": "history", "includeAdjustedClose": "true"})
    url = f"{YAHOO_CHART_ENDPOINT.format(symbol=yahoo_symbol)}?{query}"
    request = Request(url, headers={"User-Agent": "StrategyLab-v2 Gaon research data check"})
    try:
        response = (opener or _default_urlopen)(request, timeout_seconds)
        payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - diagnostic command reports provider state explicitly.
        raise RealMarketDataUnavailable(f"real_data_unavailable: {exc.__class__.__name__}") from exc
    rows = _debug_yahoo_chart_rows(payload, symbol.upper())
    target_rows = tuple(row for row in rows if row["date_kst"] == day or row["date_utc"] == day)
    return {
        "schema_version": KRX_REAL_PIPELINE_SCHEMA_VERSION,
        "provider": "real:yahoo-chart",
        "symbol": symbol.upper(),
        "yahoo_symbol": yahoo_symbol,
        "target_date": day,
        "url": url,
        "rows": target_rows,
        "neighbor_rows": rows,
    }


def real_krx_data_release_check(connection: sqlite3.Connection, *, symbol: str, start_date: str, end_date: str, provider: KRXHistoricalDataProvider) -> dict[str, object]:
    dataset, quality, _inserted = KRXDatasetBuilder(connection, provider).build(symbol, start_date=start_date, end_date=end_date)
    if dataset.metadata.fixture_backed:
        raise RealMarketDataUnavailable("real_data_unavailable: release check requires source=real")
    blocking = _blocking_quality_findings(quality)
    if blocking:
        details = "; ".join(f"{finding.code}:{finding.message}" for finding in blocking)
        raise RealMarketDataUnavailable(f"real_data_unavailable: blocking_quality_findings={details}")
    spec = UserStrategyParser().parse("20-day breakout close > MA20 > MA60 volume >= volume MA20 stop -5% 10-day low exit", symbol=symbol)
    assumptions = default_execution_assumptions()
    result = RuleBasedBacktestEngine().run(f"real-krx-data-release-check:{uuid4().hex}", spec, dataset, assumptions)
    validation = WalkForwardValidator().validate(spec, dataset, assumptions, run_id=result.run_id)
    return {
        "schema_version": 33,
        "source": result.source.value,
        "fixture_backed": dataset.metadata.fixture_backed,
        "provider": dataset.metadata.source,
        "symbol": symbol.upper(),
        "start_date": dataset.metadata.start_date,
        "end_date": dataset.metadata.end_date,
        "rows": len(dataset.bars),
        "quality": quality.status.value,
        "provider_gaps": len(_findings_by_code(quality, "provider_gap")),
        "provider_gap_dates": _finding_dates(_findings_by_code(quality, "provider_gap")),
        "provider_ohlc_anomalies": len(_findings_by_code(quality, "provider_ohlc_anomaly")),
        "provider_ohlc_anomaly_dates": _finding_dates(_findings_by_code(quality, "provider_ohlc_anomaly")),
        "zero_volume_warnings": len(_findings_by_code(quality, "zero_volume")),
        "zero_volume_dates": _finding_dates(_findings_by_code(quality, "zero_volume")),
        "provider_zero_volume_anomalies": len(_findings_by_code(quality, "provider_zero_volume_anomaly")),
        "provider_zero_volume_anomaly_dates": _finding_dates(_findings_by_code(quality, "provider_zero_volume_anomaly")),
        "blocking_findings": len(blocking),
        "trades": result.metrics.trade_count,
        "metrics": result.metrics.to_json(),
        "validation": validation.passed,
    }


def historical_krx_data_quality_inspect(symbol: str, start_date: str, end_date: str, *, provider: KRXHistoricalDataProvider) -> dict[str, object]:
    raw_dataset = provider.fetch_bars(symbol, start_date=start_date, end_date=end_date)
    policy = _provider_anomaly_policy(raw_dataset.metadata.source)
    registered_zero_dates = policy.provider_zero_volume_anomaly_dates.get(symbol.upper(), frozenset()) if policy is not None else frozenset()
    registered_zero_volume_bars = tuple(bar for bar in raw_dataset.bars if bar.volume == 0 and bar.timestamp in registered_zero_dates)
    unverified_zero_volume_bars = tuple(bar for bar in raw_dataset.bars if bar.volume == 0 and bar.timestamp not in registered_zero_dates)
    dataset = _exclude_registered_provider_zero_volume_bars(raw_dataset)
    quality = _validate_krx_daily_dataset(dataset, min_bars=60)
    return {
        "schema_version": 33,
        "symbol": symbol.upper(),
        "source": dataset.metadata.source,
        "fixture_backed": dataset.metadata.fixture_backed,
        "start_date": dataset.metadata.start_date,
        "end_date": dataset.metadata.end_date,
        "rows": len(dataset.bars),
        "quality": quality.status.value,
        "provider_gap_dates": _finding_dates(_findings_by_code(quality, "provider_gap")),
        "provider_ohlc_anomaly_dates": _finding_dates(_findings_by_code(quality, "provider_ohlc_anomaly")),
        "provider_zero_volume_anomaly_dates": _finding_dates(_findings_by_code(quality, "provider_zero_volume_anomaly")),
        "registered_provider_zero_volume_bars": tuple(
            {
                "date": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "trading_value": bar.trading_value,
            }
            for bar in registered_zero_volume_bars
        ),
        "zero_volume_dates": tuple(bar.timestamp for bar in unverified_zero_volume_bars),
        "zero_volume_bars": tuple(
            {
                "date": bar.timestamp,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "trading_value": bar.trading_value,
            }
            for bar in unverified_zero_volume_bars
        ),
        "unknown_missing_trading_dates": _finding_dates(_findings_by_code(quality, "unknown_missing_trading_day")),
        "blocking_findings": tuple(finding.to_json() for finding in _blocking_quality_findings(quality)),
        "findings": tuple(finding.to_json() for finding in quality.findings),
    }


def provider_gap_release_check(connection: sqlite3.Connection) -> dict[str, object]:
    calendar = KRXTradingCalendar()
    if "2025-09-19" not in calendar.expected_open_dates(start_date="2025-09-19", end_date="2025-09-19"):
        raise RealMarketDataUnavailable("real_data_unavailable: provider gap date was incorrectly marked exchange closed")
    yahoo_dataset = _quality_fixture_dataset(
        "yahoo-gap",
        "2025-09-17",
        "2025-09-23",
        ("2025-09-17", "2025-09-18", "2025-09-22", "2025-09-23"),
        fixture_backed=False,
        source="real:yahoo-chart",
    )
    other_dataset = _quality_fixture_dataset(
        "other-provider-gap",
        "2025-09-17",
        "2025-09-23",
        ("2025-09-17", "2025-09-18", "2025-09-22", "2025-09-23"),
        fixture_backed=False,
        source="real:other-provider",
    )
    unknown_dataset = _quality_fixture_dataset(
        "unknown-gap",
        "2026-01-02",
        "2026-01-06",
        ("2026-01-02", "2026-01-06"),
        fixture_backed=False,
        source="real:yahoo-chart",
    )
    malformed_dataset = _quality_fixture_dataset(
        "provider-gap-malformed",
        "2025-09-17",
        "2025-09-23",
        ("2025-09-17", "2025-09-18", "2025-09-22", "2025-09-23"),
        fixture_backed=False,
        invalid_ohlc=True,
        source="real:yahoo-chart",
    )
    duplicate_dataset = _quality_fixture_dataset(
        "provider-gap-duplicate",
        "2025-09-17",
        "2025-09-17",
        ("2025-09-17", "2025-09-17"),
        fixture_backed=False,
        source="real:yahoo-chart",
    )
    yahoo_quality = _validate_krx_daily_dataset(yahoo_dataset, min_bars=1)
    other_quality = _validate_krx_daily_dataset(other_dataset, min_bars=1)
    unknown_quality = _validate_krx_daily_dataset(unknown_dataset, min_bars=1)
    malformed_quality = _validate_krx_daily_dataset(malformed_dataset, min_bars=1)
    duplicate_quality = _validate_krx_daily_dataset(duplicate_dataset, min_bars=1)
    if not _has_finding(yahoo_quality, "provider_gap"):
        raise RealMarketDataUnavailable("real_data_unavailable: Yahoo provider gap was not classified")
    if _has_finding(yahoo_quality, "unknown_missing_trading_day"):
        raise RealMarketDataUnavailable("real_data_unavailable: known Yahoo provider gap was treated as unknown")
    if not _is_research_eligible_quality(yahoo_quality):
        raise RealMarketDataUnavailable("real_data_unavailable: provider-gap-only data was not research eligible")
    if _has_finding(other_quality, "provider_gap") or not _has_finding(other_quality, "unknown_missing_trading_day"):
        raise RealMarketDataUnavailable("real_data_unavailable: provider anomaly leaked into another provider")
    if not _blocking_quality_findings(unknown_quality):
        raise RealMarketDataUnavailable("real_data_unavailable: unknown missing trading day was not blocking")
    if not _blocking_quality_findings(malformed_quality) or not _blocking_quality_findings(duplicate_quality):
        raise RealMarketDataUnavailable("real_data_unavailable: malformed or duplicate data was not blocking")
    inserted = SQLiteDatasetRegistry(connection).put_dataset(yahoo_dataset, yahoo_quality)
    return {
        "schema_version": 33,
        "provider": yahoo_dataset.metadata.source,
        "fixture_backed": yahoo_dataset.metadata.fixture_backed,
        "quality": yahoo_quality.status.value,
        "provider_gaps": len(_findings_by_code(yahoo_quality, "provider_gap")),
        "provider_gap_dates": _finding_dates(_findings_by_code(yahoo_quality, "provider_gap")),
        "blocking_findings": len(_blocking_quality_findings(yahoo_quality)),
        "other_provider_isolated": True,
        "inserted": inserted,
    }


def historical_krx_data_quality_release_check(connection: sqlite3.Connection) -> dict[str, object]:
    calendar = KRXTradingCalendar()
    for closed_day in ("2023-05-29", "2023-12-29", "2024-12-31"):
        if closed_day in calendar.expected_open_dates(start_date=closed_day, end_date=closed_day):
            raise RealMarketDataUnavailable(f"real_data_unavailable: KRX closure treated as open {closed_day}")
    for open_day in ("2022-01-03", "2022-05-09", "2025-09-19"):
        if open_day not in calendar.expected_open_dates(start_date=open_day, end_date=open_day):
            raise RealMarketDataUnavailable(f"real_data_unavailable: provider anomaly date incorrectly marked exchange closed {open_day}")

    expected = calendar.expected_open_dates(start_date="2022-01-03", end_date="2025-09-19")
    zero_volume_dates = {
        "2022-01-26",
        "2022-02-08",
        "2022-02-09",
        "2022-02-21",
        "2022-02-22",
        "2022-02-23",
        "2022-02-28",
        "2022-03-04",
        "2022-03-10",
        "2022-03-15",
        "2022-03-17",
    }
    missing_yahoo_dates = {"2022-01-03", "2022-05-09", "2024-10-14", "2025-09-19"} | zero_volume_dates
    yahoo_dataset = _quality_fixture_dataset(
        "historical-data-quality-yahoo",
        "2022-01-03",
        "2025-09-19",
        tuple(day for day in expected if day not in missing_yahoo_dates),
        fixture_backed=False,
        source="real:yahoo-chart",
        symbol="005930",
    )
    yahoo_quality = _validate_krx_daily_dataset(yahoo_dataset, min_bars=1)
    provider_gap_dates = _finding_dates(_findings_by_code(yahoo_quality, "provider_gap"))
    if provider_gap_dates != ("2022-01-03", "2022-05-09", "2025-09-19"):
        raise RealMarketDataUnavailable(f"real_data_unavailable: Yahoo historical provider gaps were not classified correctly {provider_gap_dates}")
    provider_ohlc_dates = _finding_dates(_findings_by_code(yahoo_quality, "provider_ohlc_anomaly"))
    if provider_ohlc_dates != ("2024-10-14",):
        raise RealMarketDataUnavailable(f"real_data_unavailable: Yahoo historical OHLC anomaly was not classified correctly {provider_ohlc_dates}")
    provider_zero_dates = _finding_dates(_findings_by_code(yahoo_quality, "provider_zero_volume_anomaly"))
    if provider_zero_dates != tuple(sorted(zero_volume_dates)):
        raise RealMarketDataUnavailable(f"real_data_unavailable: Yahoo historical zero-volume anomalies were not classified correctly {provider_zero_dates}")
    if _blocking_quality_findings(yahoo_quality):
        raise RealMarketDataUnavailable("real_data_unavailable: explained Yahoo historical anomalies were blocking")

    other_symbol_dataset = _quality_fixture_dataset(
        "historical-data-quality-other-symbol",
        "2022-01-03",
        "2022-01-05",
        tuple(day for day in calendar.expected_open_dates(start_date="2022-01-03", end_date="2022-01-05") if day != "2022-01-03"),
        fixture_backed=False,
        source="real:yahoo-chart",
        symbol="000660",
    )
    other_symbol_quality = _validate_krx_daily_dataset(other_symbol_dataset, min_bars=1)
    if not _has_finding(other_symbol_quality, "unknown_missing_trading_day"):
        raise RealMarketDataUnavailable("real_data_unavailable: symbol-specific Yahoo gap leaked into another symbol")

    zero_volume_dataset = _quality_fixture_dataset(
        "historical-data-quality-zero-volume",
        "2026-01-02",
        "2026-01-06",
        KRXTradingCalendar().expected_open_dates(start_date="2026-01-02", end_date="2026-01-06"),
        fixture_backed=False,
        source="real:yahoo-chart",
        zero_volume_dates=frozenset({"2026-01-05"}),
    )
    zero_quality = _validate_krx_daily_dataset(zero_volume_dataset, min_bars=1)
    if not _has_finding(zero_quality, "zero_volume") or not _blocking_quality_findings(zero_quality):
        raise RealMarketDataUnavailable("real_data_unavailable: unregistered zero-volume bar was not kept blocking")

    malformed_dataset = _quality_fixture_dataset(
        "historical-data-quality-malformed",
        "2026-01-02",
        "2026-01-06",
        KRXTradingCalendar().expected_open_dates(start_date="2026-01-02", end_date="2026-01-06"),
        fixture_backed=False,
        source="real:yahoo-chart",
        invalid_ohlc=True,
    )
    malformed_quality = _validate_krx_daily_dataset(malformed_dataset, min_bars=1)
    if not _blocking_quality_findings(malformed_quality):
        raise RealMarketDataUnavailable("real_data_unavailable: malformed OHLC was not blocking")

    return {
        "schema_version": 33,
        "provider": yahoo_dataset.metadata.source,
        "fixture_backed": yahoo_dataset.metadata.fixture_backed,
        "provider_gap_dates": provider_gap_dates,
        "provider_ohlc_anomaly_dates": provider_ohlc_dates,
        "provider_zero_volume_anomaly_dates": provider_zero_dates,
        "zero_volume_policy": "registered_zero_volume_excluded_unregistered_blocks",
        "blocking_findings": len(_blocking_quality_findings(yahoo_quality)),
        "symbol_specific_gap_isolated": True,
        "krx_closed_2023_05_29": True,
        "inserted": False,
    }


def historical_krx_calendar_release_check(connection: sqlite3.Connection) -> dict[str, object]:
    calendar = KRXTradingCalendar()
    historical_closed = (
        "2023-08-15",
        "2023-09-28",
        "2023-09-29",
        "2023-10-02",
        "2023-10-03",
        "2023-10-09",
        "2023-12-25",
        "2023-12-29",
        "2024-01-01",
        "2024-02-09",
        "2024-02-12",
        "2024-03-01",
        "2024-04-10",
        "2024-05-01",
        "2024-05-06",
        "2024-05-15",
        "2024-06-06",
        "2024-08-15",
        "2024-09-16",
        "2024-09-17",
        "2024-09-18",
        "2024-10-01",
        "2024-10-03",
        "2024-10-09",
        "2024-12-25",
        "2024-12-31",
    )
    for day in historical_closed:
        if day in calendar.expected_open_dates(start_date=day, end_date=day):
            raise RealMarketDataUnavailable(f"real_data_unavailable: historical KRX closure treated as open {day}")
    if "2025-09-19" not in calendar.expected_open_dates(start_date="2025-09-19", end_date="2025-09-19"):
        raise RealMarketDataUnavailable("real_data_unavailable: Yahoo provider gap date was incorrectly marked exchange closed")
    expected_3y = calendar.expected_open_dates(start_date="2023-07-25", end_date="2026-07-24")
    yahoo_dates = tuple(day for day in expected_3y if day != "2025-09-19")
    yahoo_dataset = _quality_fixture_dataset(
        "historical-yahoo-gap",
        "2023-07-25",
        "2026-07-24",
        yahoo_dates,
        fixture_backed=False,
        source="real:yahoo-chart",
    )
    yahoo_quality = _validate_krx_daily_dataset(yahoo_dataset, min_bars=1)
    if _finding_dates(_findings_by_code(yahoo_quality, "provider_gap")) != ("2025-09-19",):
        raise RealMarketDataUnavailable("real_data_unavailable: historical Yahoo gap was not isolated to 2025-09-19")
    if _blocking_quality_findings(yahoo_quality):
        raise RealMarketDataUnavailable("real_data_unavailable: historical Yahoo provider-gap-only data was blocking")
    unknown_dataset = _quality_fixture_dataset(
        "historical-unknown-gap",
        "2023-07-25",
        "2026-07-24",
        tuple(day for day in expected_3y if day not in {"2025-09-19", "2026-01-05"}),
        fixture_backed=False,
        source="real:yahoo-chart",
    )
    unknown_quality = _validate_krx_daily_dataset(unknown_dataset, min_bars=1)
    if not _blocking_quality_findings(unknown_quality):
        raise RealMarketDataUnavailable("real_data_unavailable: genuine historical trading-day gap was not blocking")
    expected_5y = calendar.expected_open_dates(start_date="2021-07-25", end_date="2026-07-24")
    for day in ("2021-08-16", "2021-09-20", "2021-09-21", "2021-09-22", "2021-10-04", "2021-10-11", "2021-12-31", "2022-03-09", "2022-06-01", "2022-12-30"):
        if day in expected_5y:
            raise RealMarketDataUnavailable(f"real_data_unavailable: five-year KRX closure treated as open {day}")
    inserted = SQLiteDatasetRegistry(connection).put_dataset(yahoo_dataset, yahoo_quality)
    return {
        "schema_version": 33,
        "historical_closed_excluded": True,
        "provider_gap_dates": _finding_dates(_findings_by_code(yahoo_quality, "provider_gap")),
        "blocking_findings": len(_blocking_quality_findings(yahoo_quality)),
        "expected_3y": len(expected_3y),
        "actual_3y_without_provider_gap": len(yahoo_dates),
        "expected_5y": len(expected_5y),
        "fixture_backed": False,
        "provider": yahoo_dataset.metadata.source,
        "inserted": inserted,
    }


def krx_trading_calendar_release_check(connection: sqlite3.Connection) -> dict[str, object]:
    calendar = KRXTradingCalendar()
    engine = DataQualityEngine()
    weekend = engine.validate(
        _quality_fixture_dataset("calendar-weekend", "2026-07-03", "2026-07-06", ("2026-07-03", "2026-07-06"), fixture_backed=False),
        min_bars=1,
        calendar=calendar,
    )
    holiday = engine.validate(
        _quality_fixture_dataset("calendar-holiday", "2026-01-01", "2026-01-05", ("2026-01-02", "2026-01-05"), fixture_backed=False),
        min_bars=1,
        calendar=calendar,
    )
    missing = engine.validate(
        _quality_fixture_dataset("calendar-missing", "2026-01-02", "2026-01-06", ("2026-01-02", "2026-01-06"), fixture_backed=False),
        min_bars=1,
        calendar=calendar,
    )
    malformed = engine.validate(
        _quality_fixture_dataset("calendar-malformed", "2026-01-02", "2026-01-02", ("2026-01-02",), invalid_ohlc=True, fixture_backed=False),
        min_bars=1,
        calendar=calendar,
    )
    duplicate = engine.validate(
        _quality_fixture_dataset("calendar-duplicate", "2026-01-02", "2026-01-02", ("2026-01-02", "2026-01-02"), fixture_backed=False),
        min_bars=1,
        calendar=calendar,
    )
    if weekend.status is not DataQualityStatus.PASS:
        raise RealMarketDataUnavailable("real_data_unavailable: weekend dates were treated as missing")
    if holiday.status is not DataQualityStatus.PASS:
        raise RealMarketDataUnavailable("real_data_unavailable: KRX holiday dates were treated as missing")
    if not _has_finding(missing, "missing_dates"):
        raise RealMarketDataUnavailable("real_data_unavailable: missing trading day was not detected")
    if not _has_finding(malformed, "invalid_ohlc"):
        raise RealMarketDataUnavailable("real_data_unavailable: malformed OHLCV was not detected")
    if not _has_finding(duplicate, "duplicate_bars"):
        raise RealMarketDataUnavailable("real_data_unavailable: duplicate trading day was not detected")
    release_dataset = _quality_fixture_dataset("calendar-release", "2026-01-01", "2026-01-05", ("2026-01-02", "2026-01-05"), fixture_backed=False)
    release_quality = engine.validate(release_dataset, min_bars=1, calendar=calendar)
    inserted = SQLiteDatasetRegistry(connection).put_dataset(release_dataset, release_quality)
    return {
        "schema_version": 33,
        "weekend_excluded": True,
        "holiday_excluded": True,
        "missing_trading_day_detected": True,
        "malformed_detected": True,
        "duplicate_detected": True,
        "fixture_backed": False,
        "source": "real:test-calendar",
        "inserted": inserted,
    }


def _compare_candidates(original: RealBacktestResult, candidates: tuple[ImprovementCandidate, ...]) -> CandidateComparison:
    rows = [
        {
            "candidate_id": "original",
            "result_id": original.result_id,
            "total_return": original.metrics.total_return,
            "mdd": original.metrics.mdd,
            "profit_factor": original.metrics.profit_factor,
            "trade_count": original.metrics.trade_count,
            "source": original.source.value,
        }
    ]
    for candidate in candidates:
        result = candidate.backtest_result
        rows.append(
            {
                "candidate_id": candidate.candidate_id,
                "result_id": result.result_id if result else None,
                "changed_fields": list(candidate.changed_fields),
                "reason_ko": candidate.reason_ko,
                "total_return": result.metrics.total_return if result else None,
                "mdd": result.metrics.mdd if result else None,
                "profit_factor": result.metrics.profit_factor if result else None,
                "trade_count": result.metrics.trade_count if result else None,
                "source": result.source.value if result else None,
            }
        )
    return CandidateComparison(original.result_id, tuple(rows))


def _build_korean_report(request_text: str, dataset: MarketDataset, quality: DataQualityReport, strategy: CanonicalStrategySpec, assumptions: BacktestExecutionAssumptionSet, backtest: RealBacktestResult, validation: ValidationReport, findings: tuple[CriticFinding, ...], candidates: tuple[ImprovementCandidate, ...], comparison: CandidateComparison) -> str:
    source_label = "fixture" if dataset.metadata.fixture_backed else "real"
    lines = [
        "[분석 기준]",
        f"- 요청: {request_text}",
        "- 자동 주문, Champion 자동 승격, 승인 우회는 수행하지 않았습니다.",
        "",
        "[검증된 데이터]",
        f"- dataset_id={dataset.dataset_id}",
        f"- source={source_label}",
        f"- quality_status={quality.status.value}",
        f"- bars={len(dataset.bars)}",
        "",
        "[백테스트 결과]",
        f"- total_return={backtest.metrics.total_return:.2%}",
        f"- MDD={backtest.metrics.mdd:.2%}",
        f"- Sharpe={backtest.metrics.sharpe if backtest.metrics.sharpe is not None else 'not_available'}",
        f"- trade_count={backtest.metrics.trade_count}",
        f"- execution_assumptions={assumptions.to_json()}",
        "",
        "[발견된 약점]",
    ]
    provider_gap_dates = _finding_dates(_findings_by_code(quality, "provider_gap"))
    if provider_gap_dates:
        joined = ", ".join(provider_gap_dates)
        lines.extend(
            [
                "",
                "[데이터 공급자 경고]",
                f"- 실제 Yahoo KRX 데이터 {len(dataset.bars)}개 일봉을 사용했습니다.",
                f"- 데이터 공급자에서 {joined} 일봉 {len(provider_gap_dates)}건이 누락되어 있습니다.",
                "- 해당 날짜는 KRX 실제 거래일이므로 공급자 데이터 누락으로 분류했습니다.",
                "",
            ]
        )
    lines.extend(f"- {finding.message_ko}" for finding in findings)
    lines.extend(
        [
            "",
            "[개선 가설]",
        ]
    )
    lines.extend(f"- {candidate.candidate_id}: {candidate.reason_ko}" for candidate in candidates)
    lines.extend(["", "[개선 후보 비교]"])
    for row in comparison.rows:
        lines.append(f"- {row['candidate_id']}: total_return={row.get('total_return')} mdd={row.get('mdd')} trade_count={row.get('trade_count')}")
    lines.extend(
        [
            "",
            "[가온의 판단]",
            "- 현재 결과는 연구와 비교를 위한 참고 자료이며, 실거래 판단이나 자동 승격 근거가 아닙니다.",
            "- fixture 결과는 실제 KRX 결과가 아니며 실제 데이터가 연결되면 source=real로 별도 표시됩니다." if dataset.metadata.fixture_backed else "- 실제 public 데이터 기반 결과이지만, 주문 전 별도 승인과 운영 검증이 필요합니다.",
            "",
            "[주의사항]",
            "- LLM 생성 Python, arbitrary shell/SQL, broker 주문, KIS 실거래 연결은 사용하지 않았습니다.",
        ]
    )
    return "\n".join(lines)


def _empty_result(run_id: str, strategy: CanonicalStrategySpec, dataset: MarketDataset, assumptions: BacktestExecutionAssumptionSet, status: str, warnings: tuple[str, ...], at: str) -> RealBacktestResult:
    metrics = RealPerformanceMetrics(0.0, None, 0.0, None, None, None, 0, None, None, None, None, 0.0, float(assumptions.initial_capital.value), None, 0)
    return RealBacktestResult(f"krx-real-backtest-result:{run_id}", run_id, status, MarketDataAvailability.FIXTURE if dataset.metadata.fixture_backed else MarketDataAvailability.REAL, strategy, dataset.dataset_id, dataset.fingerprint, assumptions, metrics, (), (), warnings, at)


def _parse_yahoo_chart_payload(payload: dict[str, object], symbol: str) -> tuple[MarketBar, ...]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise ValueError("missing chart payload")
    error = chart.get("error")
    if error:
        raise ValueError("provider returned chart error")
    results = chart.get("result")
    if not isinstance(results, list) or not results:
        return ()
    result = results[0]
    if not isinstance(result, dict):
        return ()
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        return ()
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
        return ()
    quote = quotes[0]
    opens = quote.get("open", [])
    highs = quote.get("high", [])
    lows = quote.get("low", [])
    closes = quote.get("close", [])
    volumes = quote.get("volume", [])
    bars: list[MarketBar] = []
    for index, timestamp in enumerate(timestamps):
        try:
            open_ = _normalize_yahoo_krx_ohlc(float(opens[index]))
            high = _normalize_yahoo_krx_ohlc(float(highs[index]))
            low = _normalize_yahoo_krx_ohlc(float(lows[index]))
            close = _normalize_yahoo_krx_ohlc(float(closes[index]))
            volume = int(volumes[index] or 0)
        except (TypeError, ValueError, IndexError):
            continue
        if not _is_yahoo_ohlc_consistent(open_, high, low, close):
            continue
        day = datetime.fromtimestamp(int(timestamp), UTC).date().isoformat()
        bars.append(MarketBar(day, symbol, open_, high, low, close, volume, int(close * volume)))
    return tuple(sorted(bars, key=lambda bar: bar.timestamp))


def _debug_yahoo_chart_rows(payload: dict[str, object], symbol: str) -> tuple[dict[str, object], ...]:
    chart = payload.get("chart")
    if not isinstance(chart, dict):
        raise RealMarketDataUnavailable("real_data_unavailable: missing chart payload")
    results = chart.get("result")
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        return ()
    result = results[0]
    timestamps = result.get("timestamp")
    indicators = result.get("indicators")
    if not isinstance(timestamps, list) or not isinstance(indicators, dict):
        return ()
    quotes = indicators.get("quote")
    if not isinstance(quotes, list) or not quotes or not isinstance(quotes[0], dict):
        return ()
    quote = quotes[0]
    adjclose_rows = indicators.get("adjclose")
    adjclose = adjclose_rows[0].get("adjclose", []) if isinstance(adjclose_rows, list) and adjclose_rows and isinstance(adjclose_rows[0], dict) else []
    rows: list[dict[str, object]] = []
    kst_zone = ZoneInfo("Asia/Seoul")
    for index, timestamp in enumerate(timestamps):
        utc_dt = datetime.fromtimestamp(int(timestamp), UTC)
        kst_dt = utc_dt.astimezone(kst_zone)
        raw_open = _array_get(quote.get("open"), index)
        raw_high = _array_get(quote.get("high"), index)
        raw_low = _array_get(quote.get("low"), index)
        raw_close = _array_get(quote.get("close"), index)
        normalized = {
            "open": _maybe_normalize_yahoo_value(raw_open),
            "high": _maybe_normalize_yahoo_value(raw_high),
            "low": _maybe_normalize_yahoo_value(raw_low),
            "close": _maybe_normalize_yahoo_value(raw_close),
        }
        raw_consistent = None
        if all(value is not None for value in normalized.values()):
            raw_consistent = _is_yahoo_ohlc_consistent(float(normalized["open"]), float(normalized["high"]), float(normalized["low"]), float(normalized["close"]))
        rows.append(
            {
                "index": index,
                "symbol": symbol,
                "timestamp": int(timestamp),
                "utc_datetime": utc_dt.isoformat(),
                "kst_datetime": kst_dt.isoformat(),
                "date_utc": utc_dt.date().isoformat(),
                "date_kst": kst_dt.date().isoformat(),
                "raw": {
                    "open": raw_open,
                    "high": raw_high,
                    "low": raw_low,
                    "close": raw_close,
                    "adjclose": _array_get(adjclose, index),
                    "volume": _array_get(quote.get("volume"), index),
                },
                "normalized": normalized,
                "same_index_ohlc_consistent": raw_consistent,
            }
        )
    return tuple(rows)


def _normalize_yahoo_krx_ohlc(value: float) -> float:
    """Normalize tiny Yahoo float drift while preserving real OHLC errors.

    KRX daily equity prices are quoted in integer KRW. Yahoo chart JSON may
    serialize those values as floats very close to an integer, so values such
    as 71999.999999 should not trip OHLC ordering. Wider differences are left
    untouched so genuine provider/parser data defects remain fail-closed.
    """

    rounded = round(value)
    if abs(value - rounded) <= KRX_WON_FLOAT_DRIFT_TOLERANCE:
        return float(rounded)
    return value


def _maybe_normalize_yahoo_value(value: object) -> float | None:
    if value is None:
        return None
    try:
        return _normalize_yahoo_krx_ohlc(float(value))
    except (TypeError, ValueError):
        return None


def _array_get(value: object, index: int) -> object | None:
    if not isinstance(value, list) or index >= len(value):
        return None
    return value[index]


def _is_yahoo_ohlc_consistent(open_: float, high: float, low: float, close: float) -> bool:
    return (
        low - KRX_WON_FLOAT_DRIFT_TOLERANCE <= open_ <= high + KRX_WON_FLOAT_DRIFT_TOLERANCE
        and low - KRX_WON_FLOAT_DRIFT_TOLERANCE <= close <= high + KRX_WON_FLOAT_DRIFT_TOLERANCE
        and low <= high + KRX_WON_FLOAT_DRIFT_TOLERANCE
    )


def _to_yahoo_symbol(symbol: str) -> str:
    upper = symbol.upper().strip()
    if upper.endswith((".KS", ".KQ")):
        return upper
    if upper.startswith("KQ:"):
        return f"{upper[3:]}.KQ"
    return f"{upper}.KS"


def _default_urlopen(request: Request, timeout: float) -> object:
    return urlopen(request, timeout=timeout)


def _quality_fixture_dataset(
    dataset_key: str,
    start_date: str,
    end_date: str,
    dates: tuple[str, ...],
    *,
    fixture_backed: bool,
    source: str | None = None,
    invalid_ohlc: bool = False,
    symbol: str = "005930",
    zero_volume_dates: frozenset[str] = frozenset(),
) -> MarketDataset:
    bars = []
    for index, day in enumerate(dates):
        close = 100.0 + index
        high = close + 1.0
        low = close - 1.0
        if invalid_ohlc:
            high = close - 2.0
        volume = 0 if day in zero_volume_dates else 1_000_000 + index
        bars.append(MarketBar(day, symbol.upper(), close, high, low, close, volume, int(close * volume)))
    dataset_source = source or ("fixture:quality-calendar" if fixture_backed else "real:test-calendar")
    metadata = MarketDataMetadata(dataset_source, "KOSPI", "daily", start_date, end_date, True, "2026-07-25T00:00:00Z", fixture_backed)
    return MarketDataset(f"dataset:{dataset_key}:{start_date}:{end_date}", (MarketSymbol(symbol.upper(), symbol.upper(), "KOSPI"),), tuple(bars), metadata)


def _validate_krx_daily_dataset(dataset: MarketDataset, *, min_bars: int) -> DataQualityReport:
    calendar = KRXTradingCalendar() if dataset.metadata.timeframe == "daily" else None
    policy = _provider_anomaly_policy(dataset.metadata.source)
    symbol = dataset.symbols[0].symbol if dataset.symbols else ""
    classifier = (lambda day: policy.classify_missing_date(day, symbol=symbol)) if policy is not None else _unknown_missing_trading_day
    zero_volume_classifier = (lambda bar: policy.classify_zero_volume(bar)) if policy is not None else None
    return DataQualityEngine().validate(dataset, min_bars=min_bars, calendar=calendar, missing_date_classifier=classifier if calendar is not None else None, zero_volume_classifier=zero_volume_classifier)


def _exclude_registered_provider_zero_volume_bars(dataset: MarketDataset) -> MarketDataset:
    policy = _provider_anomaly_policy(dataset.metadata.source)
    if policy is None:
        return dataset
    filtered = []
    removed = False
    for bar in dataset.bars:
        symbol_dates = policy.provider_zero_volume_anomaly_dates.get(bar.symbol.upper(), frozenset())
        if bar.timestamp in symbol_dates and bar.volume == 0 and bar.trading_value == 0:
            removed = True
            continue
        filtered.append(bar)
    if not removed:
        return dataset
    return replace(dataset, bars=tuple(filtered))


def _provider_anomaly_policy(provider_source: str) -> ProviderAnomalyPolicy | None:
    return YAHOO_KRX_ANOMALY_POLICY if provider_source == YAHOO_KRX_ANOMALY_POLICY.provider else None


def _unknown_missing_trading_day(day: str) -> DataQualityFinding:
    _validate_date(day)
    return DataQualityFinding("unknown_missing_trading_day", "warning", f"missing KRX trading date {day} is not explained by calendar or provider anomaly registry")


def _has_finding(report: DataQualityReport, code: str) -> bool:
    return any(finding.code == code for finding in report.findings)


def _findings_by_code(report: DataQualityReport, code: str) -> tuple[DataQualityFinding, ...]:
    return tuple(finding for finding in report.findings if finding.code == code)


def _blocking_quality_findings(report: DataQualityReport) -> tuple[DataQualityFinding, ...]:
    return tuple(finding for finding in report.findings if finding.severity == "error" or finding.code not in ALLOWED_RELEASE_WARNING_CODES)


def _is_research_eligible_quality(report: DataQualityReport) -> bool:
    return not _blocking_quality_findings(report)


def _finding_dates(findings: tuple[DataQualityFinding, ...]) -> tuple[str, ...]:
    dates = []
    for finding in findings:
        match = re.search(r"\d{4}-\d{2}-\d{2}", finding.message)
        if match:
            dates.append(match.group(0))
    return tuple(dates)


def _date_range(start: str, end: str) -> list[str]:
    current = datetime.fromisoformat(start)
    final = datetime.fromisoformat(end)
    dates = []
    while current <= final:
        dates.append(current.date().isoformat())
        current += timedelta(days=1)
    return dates


def _validate_date(value: str) -> None:
    if DATE_ONLY.fullmatch(value) is None:
        raise ValueError("date must use YYYY-MM-DD")


def _max_drawdown(equities: list[float]) -> float:
    peak = equities[0] if equities else 0.0
    worst = 0.0
    for equity in equities:
        peak = max(peak, equity)
        if peak:
            worst = min(worst, equity / peak - 1.0)
    return abs(worst)


def _sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    avg = sum(returns) / len(returns)
    variance = sum((item - avg) ** 2 for item in returns) / (len(returns) - 1)
    stdev = variance ** 0.5
    return None if stdev == 0 else (avg / stdev) * (252 ** 0.5)


def _longest_losing_streak(trades: tuple[RealBacktestTrade, ...]) -> int:
    longest = 0
    current = 0
    for trade in trades:
        if trade.pnl < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _sha(payload: dict[str, object]) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
