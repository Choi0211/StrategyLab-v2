"""Position sizing helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FixedQuantitySizer:
    """Always returns a fixed quantity when affordable."""

    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")

    def size(self, cash: float, price: float) -> int:
        if price <= 0:
            raise ValueError("price must be positive")
        return self.quantity if cash >= self.quantity * price else 0

