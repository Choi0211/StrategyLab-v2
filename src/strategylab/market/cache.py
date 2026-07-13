"""Market data cache boundary."""

from __future__ import annotations

from abc import ABC, abstractmethod

from strategylab.market.models import MarketDataset


class MarketDataCache(ABC):
    """Interface for cache implementations used by market adapters."""

    @abstractmethod
    def get(self, key: str) -> MarketDataset | None:
        """Return cached dataset or None."""

    @abstractmethod
    def set(self, key: str, dataset: MarketDataset) -> None:
        """Store dataset in cache."""

