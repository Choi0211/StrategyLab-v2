"""Risk decision models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskScore:
    """Normalized risk score."""

    score: float
    reason: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")


@dataclass(frozen=True)
class EmergencyStopDecision:
    """Emergency stop result."""

    triggered: bool
    reason: str


@dataclass(frozen=True)
class CircuitBreakerDecision:
    """Circuit breaker result."""

    triggered: bool
    reason: str

