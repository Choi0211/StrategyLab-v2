"""Market data adapter boundaries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from strategylab.market.models import MarketDataset


class MarketDataAdapter(ABC):
    """Interface for loading market datasets."""

    @abstractmethod
    def load(
        self,
        symbols: tuple[str, ...],
        start: date | None = None,
        end: date | None = None,
    ) -> MarketDataset:
        """Load a dataset for symbols and date range."""


class InMemoryMarketDataAdapter(MarketDataAdapter):
    """Test adapter backed by an in-memory dataset."""

    def __init__(self, dataset: MarketDataset) -> None:
        self.dataset = dataset

    def load(
        self,
        symbols: tuple[str, ...],
        start: date | None = None,
        end: date | None = None,
    ) -> MarketDataset:
        filtered_bars = []
        symbol_set = set(symbols)
        for symbol in symbols:
            symbol_dataset = self.dataset.filter(symbol=symbol, start=start, end=end)
            filtered_bars.extend(symbol_dataset.bars)
        return MarketDataset(
            bars=tuple(bar for bar in filtered_bars if bar.symbol in symbol_set),
            provenance=self.dataset.provenance,
        )

