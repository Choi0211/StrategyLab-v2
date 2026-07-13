"""Portfolio accounting models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class CashLedger:
    """Cash state for portfolio simulation."""

    cash: float

    def debit(self, amount: float) -> "CashLedger":
        if amount < 0:
            raise ValueError("amount must be non-negative")
        if amount > self.cash:
            raise ValueError("insufficient cash")
        return CashLedger(cash=round(self.cash - amount, 6))

    def credit(self, amount: float) -> "CashLedger":
        if amount < 0:
            raise ValueError("amount must be non-negative")
        return CashLedger(cash=round(self.cash + amount, 6))


@dataclass(frozen=True)
class Position:
    """Symbol position."""

    symbol: str
    quantity: int = 0
    average_price: float = 0.0

    def buy(self, quantity: int, price: float) -> "Position":
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        total_cost = self.average_price * self.quantity + price * quantity
        new_quantity = self.quantity + quantity
        return Position(self.symbol, new_quantity, round(total_cost / new_quantity, 6))

    def sell(self, quantity: int) -> "Position":
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if quantity > self.quantity:
            raise ValueError("cannot sell more than current quantity")
        return Position(self.symbol, self.quantity - quantity, self.average_price)

    def market_value(self, price: float) -> float:
        return round(self.quantity * price, 6)


@dataclass(frozen=True)
class AllocationTarget:
    """Target portfolio allocation for one symbol."""

    symbol: str
    weight: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.weight <= 1.0:
            raise ValueError("weight must be between 0.0 and 1.0")


@dataclass(frozen=True)
class RebalanceInstruction:
    """Value-level rebalance instruction."""

    symbol: str
    target_value: float
    current_value: float
    delta_value: float


@dataclass(frozen=True)
class PerformanceSnapshot:
    """Portfolio performance state at a point in time."""

    timestamp: datetime
    cash: float
    holdings_value: float
    total_equity: float


@dataclass(frozen=True)
class PortfolioState:
    """Portfolio cash and positions."""

    cash: CashLedger
    positions: dict[str, Position] = field(default_factory=dict)

    def holdings_value(self, marks: dict[str, float]) -> float:
        return round(sum(position.market_value(marks.get(symbol, 0.0)) for symbol, position in self.positions.items()), 6)

    def total_equity(self, marks: dict[str, float]) -> float:
        return round(self.cash.cash + self.holdings_value(marks), 6)

    def snapshot(self, timestamp: datetime, marks: dict[str, float]) -> PerformanceSnapshot:
        holdings = self.holdings_value(marks)
        return PerformanceSnapshot(timestamp, self.cash.cash, holdings, round(self.cash.cash + holdings, 6))

    def rebalance_instructions(
        self,
        targets: tuple[AllocationTarget, ...],
        marks: dict[str, float],
    ) -> tuple[RebalanceInstruction, ...]:
        total_weight = round(sum(target.weight for target in targets), 6)
        if total_weight != 1.0:
            raise ValueError("allocation target weights must sum to 1.0")
        total_equity = self.total_equity(marks)
        instructions = []
        for target in targets:
            current_value = self.positions.get(target.symbol, Position(target.symbol)).market_value(marks.get(target.symbol, 0.0))
            target_value = round(total_equity * target.weight, 6)
            instructions.append(
                RebalanceInstruction(
                    symbol=target.symbol,
                    target_value=target_value,
                    current_value=current_value,
                    delta_value=round(target_value - current_value, 6),
                )
            )
        return tuple(instructions)

