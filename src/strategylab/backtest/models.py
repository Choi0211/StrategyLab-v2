"""Backtest models and canonical result schema."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class TradeSide(str, Enum):
    """Canonical trade sides."""

    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class BacktestConfig:
    """Backtest assumptions used by the deterministic runner."""

    initial_capital: float
    transaction_cost_rate: float = 0.0
    slippage_rate: float = 0.0
    quantity_per_signal: int = 1

    def __post_init__(self) -> None:
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.transaction_cost_rate < 0:
            raise ValueError("transaction_cost_rate must be non-negative")
        if self.slippage_rate < 0:
            raise ValueError("slippage_rate must be non-negative")
        if self.quantity_per_signal <= 0:
            raise ValueError("quantity_per_signal must be positive")

    def to_dict(self) -> dict[str, float | int]:
        return {
            "initial_capital": self.initial_capital,
            "transaction_cost_rate": self.transaction_cost_rate,
            "slippage_rate": self.slippage_rate,
            "quantity_per_signal": self.quantity_per_signal,
        }


@dataclass(frozen=True)
class TradeRecord:
    """Executed trade record emitted by the backtest runner."""

    timestamp: datetime
    symbol: str
    side: TradeSide
    price: float
    quantity: int
    fees: float
    slippage: float
    reason: str


@dataclass(frozen=True)
class EquityCurvePoint:
    """Portfolio equity snapshot."""

    timestamp: datetime
    cash: float
    holdings_value: float
    total_equity: float
    drawdown: float


@dataclass(frozen=True)
class BacktestResult:
    """Canonical backtest result."""

    result_id: str
    config: BacktestConfig
    trades: tuple[TradeRecord, ...]
    equity_curve: tuple[EquityCurvePoint, ...]

