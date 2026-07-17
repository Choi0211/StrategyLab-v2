"""Broker-free trading adapter contracts.

This module defines public contracts only. It does not import or connect to any
private broker, account, token, or live trading implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol


class CommandStatus(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    APPROVED = "approved"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass(frozen=True)
class AccountSummary:
    account_ref: str
    cash: float
    equity: float
    currency: str
    as_of: str


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: float
    average_price: float
    market_value: float


@dataclass(frozen=True)
class MarketStatus:
    market: str
    is_open: bool
    checked_at: str
    reason: str = ""


@dataclass(frozen=True)
class RuntimeStrategyStatus:
    strategy: str
    running: bool
    mode: str
    updated_at: str


@dataclass(frozen=True)
class OrderCommand:
    command_id: str
    symbol: str
    side: str
    quantity: float
    limit_price: float | None
    status: CommandStatus
    proposed_by: str
    created_at: str
    approval_ref: str | None = None
    rejection_reason: str | None = None


@dataclass(frozen=True)
class RiskGate:
    max_holdings: int
    max_order_value: float
    daily_loss_limit: float
    duplicate_order_prevention: bool = True
    market_hours_required: bool = True
    emergency_stop: bool = False


@dataclass(frozen=True)
class RiskGateResult:
    passed: bool
    reasons: tuple[str, ...]


class TradingAdapter(Protocol):
    execution_enabled: bool

    def account_summary(self) -> AccountSummary: ...
    def positions(self) -> tuple[Position, ...]: ...
    def market_status(self, market: str) -> MarketStatus: ...
    def runtime_status(self, strategy: str) -> RuntimeStrategyStatus: ...
    def propose_order(self, command: OrderCommand) -> OrderCommand: ...
    def validate_order(self, command: OrderCommand, gate: RiskGate) -> RiskGateResult: ...
    def approve_order(self, command: OrderCommand, *, approval_ref: str) -> OrderCommand: ...
    def execute_order(self, command: OrderCommand) -> OrderCommand: ...
    def cancel_order(self, command: OrderCommand, *, reason: str) -> OrderCommand: ...


class FakeTradingAdapter:
    def __init__(self, *, execution_enabled: bool = False, market_open: bool = True) -> None:
        self.execution_enabled = execution_enabled
        self._market_open = market_open
        self._commands: dict[str, OrderCommand] = {}

    def account_summary(self) -> AccountSummary:
        return AccountSummary("paper-account", 1_000_000.0, 1_000_000.0, "KRW", "2026-07-17T00:00:00Z")

    def positions(self) -> tuple[Position, ...]:
        return ()

    def market_status(self, market: str) -> MarketStatus:
        return MarketStatus(market, self._market_open, "2026-07-17T00:00:00Z", "" if self._market_open else "market closed")

    def runtime_status(self, strategy: str) -> RuntimeStrategyStatus:
        return RuntimeStrategyStatus(strategy, True, "paper", "2026-07-17T00:00:00Z")

    def propose_order(self, command: OrderCommand) -> OrderCommand:
        if command.status is not CommandStatus.PROPOSED:
            raise ValueError("order command must start as proposed")
        self._commands[command.command_id] = command
        return command

    def validate_order(self, command: OrderCommand, gate: RiskGate) -> RiskGateResult:
        reasons: list[str] = []
        if gate.emergency_stop:
            reasons.append("emergency stop enabled")
        if command.quantity <= 0:
            reasons.append("quantity must be positive")
        order_value = command.quantity * (command.limit_price or 0)
        if order_value > gate.max_order_value:
            reasons.append("max order value exceeded")
        if gate.market_hours_required and not self._market_open:
            reasons.append("market is closed")
        if gate.duplicate_order_prevention and command.command_id in self._commands and self._commands[command.command_id] is not command:
            reasons.append("duplicate order command")
        return RiskGateResult(not reasons, tuple(reasons))

    def approve_order(self, command: OrderCommand, *, approval_ref: str) -> OrderCommand:
        if command.status is not CommandStatus.PROPOSED:
            raise ValueError("only proposed commands can be approved")
        approved = replace(command, status=CommandStatus.APPROVED, approval_ref=approval_ref)
        self._commands[approved.command_id] = approved
        return approved

    def execute_order(self, command: OrderCommand) -> OrderCommand:
        if not self.execution_enabled:
            raise PermissionError("trading execution is disabled")
        if command.status is not CommandStatus.APPROVED or not command.approval_ref:
            raise PermissionError("approved command with approval_ref is required")
        executed = replace(command, status=CommandStatus.EXECUTED)
        self._commands[executed.command_id] = executed
        return executed

    def cancel_order(self, command: OrderCommand, *, reason: str) -> OrderCommand:
        cancelled = replace(command, status=CommandStatus.CANCELLED, rejection_reason=reason)
        self._commands[cancelled.command_id] = cancelled
        return cancelled
