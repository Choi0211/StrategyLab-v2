"""Market data contracts for StrategyLab v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class DataSourceMetadata:
    """Metadata describing where a dataset came from."""

    source_name: str
    collected_at: datetime
    frequency: str
    timezone: str


@dataclass(frozen=True)
class DataProvenance:
    """Audit record for market data used in research."""

    source: DataSourceMetadata
    symbol_universe: tuple[str, ...]
    start_date: date
    end_date: date
    preprocessing_steps: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class MarketBar:
    """Single OHLCV market bar."""

    symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")


@dataclass(frozen=True)
class MarketDataset:
    """Collection of market bars with provenance."""

    bars: tuple[MarketBar, ...]
    provenance: DataProvenance

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted({bar.symbol for bar in self.bars}))

    @property
    def start_date(self) -> date | None:
        if not self.bars:
            return None
        return min(bar.timestamp.date() for bar in self.bars)

    @property
    def end_date(self) -> date | None:
        if not self.bars:
            return None
        return max(bar.timestamp.date() for bar in self.bars)

    def filter(self, symbol: str | None = None, start: date | None = None, end: date | None = None) -> "MarketDataset":
        """Return a filtered dataset preserving original provenance."""

        filtered = []
        for bar in self.bars:
            bar_date = bar.timestamp.date()
            if symbol is not None and bar.symbol != symbol:
                continue
            if start is not None and bar_date < start:
                continue
            if end is not None and bar_date > end:
                continue
            filtered.append(bar)
        return MarketDataset(bars=tuple(filtered), provenance=self.provenance)
