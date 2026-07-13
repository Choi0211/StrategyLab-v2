"""Example strategies for testing the StrategyLab v2 framework."""

from __future__ import annotations

from strategylab.market import MarketDataset
from strategylab.strategies.interface import Strategy
from strategylab.strategies.models import Signal, SignalType, StrategyConfig, StrategyMetadata
from strategylab.strategies.parameters import ParameterDefinition, ParameterSchema, ParameterType


class CloseAboveThresholdStrategy(Strategy):
    """Deterministic example strategy used for Sprint 3 tests."""

    metadata = StrategyMetadata(
        name="close_above_threshold",
        version="0.1.0",
        description="Emits buy when close is greater than or equal to threshold.",
    )
    parameter_schema = ParameterSchema(
        definitions=(
            ParameterDefinition(
                name="threshold",
                parameter_type=ParameterType.FLOAT,
                default=100.0,
                min_value=0.0,
                description="Close price threshold for buy signals.",
            ),
            ParameterDefinition(
                name="strength",
                parameter_type=ParameterType.FLOAT,
                default=1.0,
                min_value=0.0,
                max_value=1.0,
                description="Signal strength to emit.",
            ),
        )
    )

    def generate_signals(self, dataset: MarketDataset, config: StrategyConfig) -> tuple[Signal, ...]:
        parameters = self.parameter_schema.validate(config.parameters)
        threshold = float(parameters["threshold"])
        strength = float(parameters["strength"])
        signals = []
        for bar in dataset.bars:
            signal_type = SignalType.BUY if bar.close >= threshold else SignalType.HOLD
            signals.append(
                Signal(
                    symbol=bar.symbol,
                    timestamp=bar.timestamp,
                    signal_type=signal_type,
                    strength=strength if signal_type is SignalType.BUY else 0.0,
                    reason=f"close {bar.close} compared with threshold {threshold}",
                    strategy_name=self.metadata.name,
                )
            )
        return tuple(signals)

