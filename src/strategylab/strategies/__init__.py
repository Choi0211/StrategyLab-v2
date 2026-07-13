"""Strategy plugin module boundary."""

from strategylab.strategies.examples import CloseAboveThresholdStrategy
from strategylab.strategies.interface import Strategy
from strategylab.strategies.models import (
    Signal,
    SignalType,
    StrategyConfig,
    StrategyMetadata,
)
from strategylab.strategies.parameters import (
    ParameterDefinition,
    ParameterSchema,
    ParameterType,
)
from strategylab.strategies.registry import StrategyRegistry

__all__ = [
    "CloseAboveThresholdStrategy",
    "ParameterDefinition",
    "ParameterSchema",
    "ParameterType",
    "Signal",
    "SignalType",
    "Strategy",
    "StrategyConfig",
    "StrategyMetadata",
    "StrategyRegistry",
]

