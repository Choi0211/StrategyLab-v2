"""Public adapter contracts for future private integrations."""

from gaon.adapters.trading import (
    AccountSummary,
    CommandStatus,
    FakeTradingAdapter,
    MarketStatus,
    OrderCommand,
    Position,
    RiskGate,
    RiskGateResult,
    RuntimeStrategyStatus,
    TradingAdapter,
)

__all__ = [
    "AccountSummary",
    "CommandStatus",
    "FakeTradingAdapter",
    "MarketStatus",
    "OrderCommand",
    "Position",
    "RiskGate",
    "RiskGateResult",
    "RuntimeStrategyStatus",
    "TradingAdapter",
]
