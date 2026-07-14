"""Strategy models and signal contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any


class SignalType(str, Enum):
    """Canonical strategy signal types."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass(frozen=True)
class StrategyMetadata:
    """Human and registry metadata for a strategy."""

    name: str
    version: str
    description: str = ""
    author: str = "StrategyLab"


@dataclass(frozen=True)
class StrategyConfig:
    """Serializable strategy configuration."""

    strategy_name: str
    strategy_version: str
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "parameters": dict(self.parameters),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrategyConfig":
        return cls(
            strategy_name=str(data["strategy_name"]),
            strategy_version=str(data["strategy_version"]),
            parameters=dict(data.get("parameters", {})),
        )


@dataclass(frozen=True)
class Signal:
    """Strategy signal output record."""

    symbol: str
    timestamp: datetime
    signal_type: SignalType
    strength: float
    reason: str
    strategy_name: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError("signal strength must be between 0.0 and 1.0")

