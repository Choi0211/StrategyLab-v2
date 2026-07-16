"""Confidence contracts for learned items."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceScore:
    """Bounded confidence score for evidence-backed learning."""

    value: float
    reason: str

    def __post_init__(self) -> None:
        if self.value < 0.0 or self.value > 1.0:
            raise ValueError("confidence value must be between 0.0 and 1.0")
        if not self.reason:
            raise ValueError("confidence reason is required")
