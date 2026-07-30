"""Dynamic KRX universe selection for Sprint 151.

The selector is deterministic and read-only. It ranks only symbols supplied by
an explicit market-data provider universe snapshot, then verifies one daily bar
per candidate for the requested selection date. It does not infer the whole KRX
market from unrelated data and it does not mutate strategy state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re
from typing import Protocol
from uuid import uuid4

from gaon.research.krx_real_pipeline import KRXFixtureMarketDataProvider, KRXTradingCalendar, RealMarketDataUnavailable, utc_now
from gaon.research.real_research import DataQualityEngine, DataQualityStatus, MarketDataset, MarketSymbol


KRX_UNIVERSE_SCHEMA_VERSION = 1
SUPPORTED_MARKETS = frozenset({"KOSPI", "KOSDAQ", "ALL"})
SUPPORTED_RANKING_METRICS = frozenset({"trading_value"})
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CANONICAL_KRX_SYMBOL = re.compile(r"^\d{6}$")


class KRXUniverseSource(str, Enum):
    FIXTURE = "fixture"
    REAL = "real"


@dataclass(frozen=True)
class KRXUniversePolicy:
    policy_version: str = "krx-universe-selection-v1"
    supported_ranking_metrics: tuple[str, ...] = ("trading_value",)
    tie_break: str = "canonical_symbol_ascending"
    exclude_zero_volume: bool = True
    exclude_zero_trading_value: bool = True
    require_explicit_provider_universe: bool = True

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": KRX_UNIVERSE_SCHEMA_VERSION,
            "policy_version": self.policy_version,
            "supported_ranking_metrics": list(self.supported_ranking_metrics),
            "tie_break": self.tie_break,
            "exclude_zero_volume": self.exclude_zero_volume,
            "exclude_zero_trading_value": self.exclude_zero_trading_value,
            "require_explicit_provider_universe": self.require_explicit_provider_universe,
        }


@dataclass(frozen=True)
class KRXUniverseRequest:
    market: str
    selection_date: str
    ranking_metric: str
    requested_size: int
    exclusions: tuple[str, ...] = ()
    minimum_trading_value: int | None = None
    minimum_volume: int | None = None

    def __post_init__(self) -> None:
        market = self.market.upper().strip()
        metric = self.ranking_metric.strip().lower()
        if market not in SUPPORTED_MARKETS:
            raise ValueError("market must be KOSPI, KOSDAQ, or ALL")
        if DATE_ONLY.fullmatch(self.selection_date) is None:
            raise ValueError("selection_date must use YYYY-MM-DD")
        if metric not in SUPPORTED_RANKING_METRICS:
            raise ValueError("ranking_metric must be trading_value")
        if self.requested_size <= 0:
            raise ValueError("requested_size must be positive")
        if self.minimum_trading_value is not None and self.minimum_trading_value < 0:
            raise ValueError("minimum_trading_value must not be negative")
        if self.minimum_volume is not None and self.minimum_volume < 0:
            raise ValueError("minimum_volume must not be negative")
        exclusions = tuple(_canonicalize_symbol(symbol) for symbol in self.exclusions)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "ranking_metric", metric)
        object.__setattr__(self, "exclusions", tuple(dict.fromkeys(exclusions)))

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": KRX_UNIVERSE_SCHEMA_VERSION,
            "market": self.market,
            "selection_date": self.selection_date,
            "ranking_metric": self.ranking_metric,
            "requested_size": self.requested_size,
            "exclusions": list(self.exclusions),
            "minimum_trading_value": self.minimum_trading_value,
            "minimum_volume": self.minimum_volume,
        }


@dataclass(frozen=True)
class KRXUniverseEntry:
    rank: int | None
    symbol: str
    name: str | None
    market: str
    trading_value: int
    volume: int
    close: float
    data_date: str
    included: bool
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _canonicalize_symbol(self.symbol))
        object.__setattr__(self, "market", self.market.upper().strip())
        if self.volume < 0 or self.trading_value < 0:
            raise ValueError("volume and trading_value must not be negative")
        if self.data_date and DATE_ONLY.fullmatch(self.data_date) is None:
            raise ValueError("data_date must use YYYY-MM-DD")

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": KRX_UNIVERSE_SCHEMA_VERSION,
            "rank": self.rank,
            "symbol": self.symbol,
            "name": self.name,
            "market": self.market,
            "trading_value": self.trading_value,
            "volume": self.volume,
            "close": self.close,
            "data_date": self.data_date,
            "included": self.included,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass(frozen=True)
class KRXUniverseExclusion:
    symbol: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", _canonicalize_symbol(self.symbol))
        if not self.reason:
            raise ValueError("exclusion reason is required")

    def to_json(self) -> dict[str, object]:
        return {"schema_version": KRX_UNIVERSE_SCHEMA_VERSION, "symbol": self.symbol, "reason": self.reason}


@dataclass(frozen=True)
class KRXUniverseResult:
    universe_id: str
    request: KRXUniverseRequest
    source: str
    fixture_backed: bool
    symbols: tuple[str, ...]
    ranked_entries: tuple[KRXUniverseEntry, ...]
    exclusions: tuple[KRXUniverseExclusion, ...]
    selected_size: int
    generated_at: str
    data_quality_summary: dict[str, object]
    warnings: tuple[str, ...]
    policy: KRXUniversePolicy

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": KRX_UNIVERSE_SCHEMA_VERSION,
            "universe_id": self.universe_id,
            "request": self.request.to_json(),
            "source": self.source,
            "fixture_backed": self.fixture_backed,
            "symbols": list(self.symbols),
            "ranked_entries": [entry.to_json() for entry in self.ranked_entries],
            "exclusions": [item.to_json() for item in self.exclusions],
            "requested_size": self.request.requested_size,
            "selected_size": self.selected_size,
            "generated_at": self.generated_at,
            "data_quality_summary": dict(self.data_quality_summary),
            "warnings": list(self.warnings),
            "policy": self.policy.to_json(),
            "automatic_order": False,
            "automatic_champion_promotion": False,
            "automatic_config_apply": False,
        }


class KRXUniverseMarketDataProvider(Protocol):
    source: str

    def fetch_universe(self, market: str) -> tuple[MarketSymbol, ...]: ...

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset: ...


class KRXUniverseSelector:
    def __init__(self, provider: KRXUniverseMarketDataProvider | None = None, policy: KRXUniversePolicy | None = None) -> None:
        self._provider = provider or KRXUniverseFixtureProvider()
        self._policy = policy or KRXUniversePolicy()

    def select(self, request: KRXUniverseRequest, *, generated_at: str | None = None) -> KRXUniverseResult:
        at = generated_at or utc_now()
        if request.selection_date not in KRXTradingCalendar().expected_open_dates(start_date=request.selection_date, end_date=request.selection_date):
            raise RealMarketDataUnavailable("real_data_unavailable: selection date is not a KRX trading day")
        try:
            candidates = self._provider.fetch_universe(request.market)
        except Exception as exc:  # noqa: BLE001 - provider failures are explicit fail-closed states.
            raise RealMarketDataUnavailable(f"real_data_unavailable: provider universe unavailable: {exc.__class__.__name__}") from exc
        if not candidates:
            raise RealMarketDataUnavailable("real_data_unavailable: provider returned empty universe")

        rows: list[KRXUniverseEntry] = []
        exclusions: list[KRXUniverseExclusion] = []
        seen: set[str] = set()
        source = getattr(self._provider, "source", "unknown")
        fixture_backed = False
        for candidate in candidates:
            try:
                symbol = _canonicalize_symbol(candidate.symbol)
            except ValueError:
                continue
            market = candidate.market.upper().strip()
            if symbol in seen:
                exclusions.append(KRXUniverseExclusion(symbol, "duplicate_symbol"))
                continue
            seen.add(symbol)
            if request.market != "ALL" and market != request.market:
                exclusions.append(KRXUniverseExclusion(symbol, "market_mismatch"))
                continue
            if symbol in request.exclusions:
                exclusions.append(KRXUniverseExclusion(symbol, "user_excluded"))
                continue
            try:
                dataset = self._provider.fetch_bars(symbol, start_date=request.selection_date, end_date=request.selection_date)
                quality = DataQualityEngine().validate(dataset, min_bars=1)
            except Exception as exc:  # noqa: BLE001 - a bad candidate is excluded, not converted to fake data.
                exclusions.append(KRXUniverseExclusion(symbol, f"data_unavailable:{exc.__class__.__name__}"))
                continue
            fixture_backed = fixture_backed or dataset.metadata.fixture_backed
            if quality.status is DataQualityStatus.FAIL:
                exclusions.append(KRXUniverseExclusion(symbol, "data_quality_fail"))
                continue
            bar = next((item for item in dataset.bars if item.timestamp == request.selection_date), None)
            if bar is None:
                exclusions.append(KRXUniverseExclusion(symbol, "missing_selection_date_bar"))
                continue
            reason = _entry_exclusion_reason(bar.volume, bar.trading_value, request)
            if reason:
                exclusions.append(KRXUniverseExclusion(symbol, reason))
                rows.append(KRXUniverseEntry(None, symbol, candidate.name, market, int(bar.trading_value), int(bar.volume), float(bar.close), bar.timestamp, False, reason))
                continue
            rows.append(KRXUniverseEntry(None, symbol, candidate.name, market, int(bar.trading_value), int(bar.volume), float(bar.close), bar.timestamp, True, None))

        included = sorted((row for row in rows if row.included), key=lambda row: (-row.trading_value, row.symbol))
        if not included:
            raise RealMarketDataUnavailable("real_data_unavailable: no eligible symbols after universe filters")
        selected = tuple(included[: request.requested_size])
        ranked = tuple(KRXUniverseEntry(index + 1, row.symbol, row.name, row.market, row.trading_value, row.volume, row.close, row.data_date, True) for index, row in enumerate(selected))
        selected_symbols = tuple(row.symbol for row in ranked)
        warnings = ()
        if len(selected_symbols) < request.requested_size:
            warnings = (f"selected_size {len(selected_symbols)} is smaller than requested_size {request.requested_size}",)
        universe_id = f"krx-universe:{_sha({'request': request.to_json(), 'symbols': selected_symbols, 'source': source, 'policy': self._policy.to_json()})[:16]}"
        return KRXUniverseResult(
            universe_id,
            request,
            source,
            fixture_backed,
            selected_symbols,
            ranked,
            tuple(exclusions),
            len(selected_symbols),
            at,
            {
                "candidate_count": len(candidates),
                "eligible_count": len(included),
                "excluded_count": len(exclusions),
                "ranking_metric": request.ranking_metric,
            },
            warnings,
            self._policy,
        )


class KRXUniverseFixtureProvider(KRXFixtureMarketDataProvider):
    source = "fixture:krx-universe"

    def fetch_universe(self, market: str) -> tuple[MarketSymbol, ...]:
        symbols = (
            MarketSymbol("005930", "Samsung Electronics", "KOSPI"),
            MarketSymbol("000660", "SK Hynix", "KOSPI"),
            MarketSymbol("005380", "Hyundai Motor", "KOSPI"),
            MarketSymbol("035420", "NAVER", "KOSPI"),
            MarketSymbol("051910", "LG Chem", "KOSPI"),
            MarketSymbol("091990", "Celltrion Healthcare", "KOSDAQ"),
            MarketSymbol("005930.KS", "Samsung Electronics duplicate", "KOSPI"),
        )
        market_upper = market.upper().strip()
        if market_upper == "ALL":
            return symbols
        return tuple(symbol for symbol in symbols if symbol.market.upper() == market_upper)

    def fetch_bars(self, symbol: str, *, start_date: str, end_date: str, timeframe: str = "daily") -> MarketDataset:
        dataset = super().fetch_bars(symbol, start_date=start_date, end_date=end_date, timeframe=timeframe)
        multipliers = {
            "005930": 12,
            "000660": 10,
            "005380": 8,
            "035420": 7,
            "051910": 6,
            "091990": 5,
        }
        canonical = _canonicalize_symbol(symbol)
        multiplier = multipliers.get(canonical, 1)
        bars = tuple(
            type(bar)(
                bar.timestamp,
                canonical,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.volume * multiplier,
                bar.trading_value * multiplier,
            )
            for bar in dataset.bars
        )
        symbols = (MarketSymbol(canonical, canonical, dataset.metadata.market),)
        return type(dataset)(dataset.dataset_id.replace(symbol.upper(), canonical), symbols, bars, dataset.metadata, dataset.corporate_actions)


def krx_universe_release_check() -> dict[str, object]:
    selector = KRXUniverseSelector(KRXUniverseFixtureProvider())
    result = selector.select(KRXUniverseRequest("ALL", "2026-07-30", "trading_value", 5, exclusions=("091990",)), generated_at="2026-07-30T00:00:00Z")
    if result.symbols != ("005930", "000660", "005380", "035420", "051910"):
        raise RealMarketDataUnavailable("real_data_unavailable: universe ranking was not deterministic")
    if result.fixture_backed is not True or result.source != "fixture:krx-universe":
        raise RealMarketDataUnavailable("real_data_unavailable: release check provenance mismatch")
    if any(entry.trading_value <= 0 or entry.volume <= 0 for entry in result.ranked_entries):
        raise RealMarketDataUnavailable("real_data_unavailable: invalid universe ranking row")
    if result.to_json()["automatic_order"] or result.to_json()["automatic_champion_promotion"]:
        raise RealMarketDataUnavailable("real_data_unavailable: universe safety boundary violated")
    return result.to_json()


def render_krx_universe_result(result: KRXUniverseResult) -> str:
    lines = [
        "krx-universe-select:",
        f"universe_id={result.universe_id}",
        f"market={result.request.market}",
        f"selection_date={result.request.selection_date}",
        f"metric={result.request.ranking_metric}",
        f"requested_size={result.request.requested_size}",
        f"selected_size={result.selected_size}",
        f"source={result.source}",
        f"fixture_backed={str(result.fixture_backed).lower()}",
        "symbols=" + ",".join(result.symbols),
        "ranked_entries:",
    ]
    for entry in result.ranked_entries:
        lines.append(f"{entry.rank}. {entry.symbol} {entry.name or ''} trading_value={entry.trading_value} volume={entry.volume} close={entry.close} data_date={entry.data_date}".rstrip())
    if result.warnings:
        lines.append("warnings=" + "; ".join(result.warnings))
    if result.exclusions:
        lines.append("exclusions=" + "; ".join(f"{item.symbol}:{item.reason}" for item in result.exclusions))
    return "\n".join(lines)


def _entry_exclusion_reason(volume: int, trading_value: int, request: KRXUniverseRequest) -> str | None:
    if volume == 0:
        return "zero_volume"
    if trading_value <= 0:
        return "zero_trading_value"
    if request.minimum_volume is not None and volume < request.minimum_volume:
        return "below_minimum_volume"
    if request.minimum_trading_value is not None and trading_value < request.minimum_trading_value:
        return "below_minimum_trading_value"
    return None


def _canonicalize_symbol(symbol: str) -> str:
    value = str(symbol).strip().upper()
    if value.startswith("KQ:"):
        value = value[3:]
    for suffix in (".KS", ".KQ"):
        if value.endswith(suffix):
            value = value[: -len(suffix)]
    if CANONICAL_KRX_SYMBOL.fullmatch(value) is None:
        raise ValueError("symbol must canonicalize to six-digit KRX code")
    return value


def _sha(payload: dict[str, object]) -> str:
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


def _json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
