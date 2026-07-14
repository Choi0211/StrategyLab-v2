"""Strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from strategylab.market import MarketDataset
from strategylab.strategies.models import Signal, StrategyConfig, StrategyMetadata
from strategylab.strategies.parameters import ParameterSchema


class Strategy(ABC):
    """Base interface for StrategyLab v2 strategies."""

    metadata: StrategyMetadata
    parameter_schema: ParameterSchema

    def build_config(self, parameters: dict[str, object] | None = None) -> StrategyConfig:
        validated = self.parameter_schema.validate(parameters or {})
        return StrategyConfig(
            strategy_name=self.metadata.name,
            strategy_version=self.metadata.version,
            parameters=validated,
        )

    @abstractmethod
    def generate_signals(self, dataset: MarketDataset, config: StrategyConfig) -> tuple[Signal, ...]:
        """Generate deterministic signals for a dataset and config."""

