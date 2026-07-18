"""Broker-free trading adapter contracts.

This module defines public contracts only. It does not import or connect to any
private broker, account, token, or live trading implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
import re
import sqlite3
from typing import Any
from typing import Protocol

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{0,19}$")


class CommandStatus(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    APPROVED = "approved"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class TradingIntent(str, Enum):
    ANALYZE = "analyze"
    SIMULATE_BUY = "simulate_buy"
    SIMULATE_SELL = "simulate_sell"
    CANCEL_SIMULATED_ORDER = "cancel_simulated_order"
    LIVE_BUY = "live_buy"
    LIVE_SELL = "live_sell"


class TradingAction(str, Enum):
    ANALYZE = "analyze"
    SIMULATE_ORDER = "simulate_order"
    CANCEL_SIMULATED_ORDER = "cancel_simulated_order"
    BLOCK_LIVE_EXECUTION = "block_live_execution"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class TradingStatus(str, Enum):
    CREATED = "created"
    VALIDATED = "validated"
    REJECTED = "rejected"
    BLOCKED = "blocked"
    SIMULATED = "simulated"
    CANCELLED = "cancelled"
    FAILED = "failed"


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
class AccountSnapshot:
    account_ref: str
    cash: float
    equity: float
    currency: str
    as_of: str

    def __post_init__(self) -> None:
        _validate_utc(self.as_of)
        if self.cash < 0 or self.equity < 0:
            raise ValueError("account snapshot values must be non-negative")


@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    quantity: float
    average_price: float
    market_value: float
    as_of: str

    def __post_init__(self) -> None:
        _validate_symbol(self.symbol)
        _validate_utc(self.as_of)


@dataclass(frozen=True)
class TradingRequest:
    request_id: str
    intent: TradingIntent
    symbol: str
    side: OrderSide | None
    quantity: float
    order_type: OrderType
    limit_price: float | None
    actor_ref: str
    created_at: str
    simulation: bool = True
    approval_ref: str | None = None
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        if not self.request_id or not self.actor_ref:
            raise ValueError("trading request requires id and actor")
        _validate_utc(self.created_at)
        if self.symbol:
            _validate_symbol(self.symbol)
        if self.quantity < 0:
            raise ValueError("trading request quantity cannot be negative")
        if self.limit_price is not None and self.limit_price <= 0:
            raise ValueError("limit price must be positive")


@dataclass(frozen=True)
class TradingDecision:
    request_id: str
    status: TradingStatus
    action: TradingAction
    reasons: tuple[str, ...]
    approval_required: bool


@dataclass(frozen=True)
class TradingExecutionContext:
    actor_ref: str
    dry_run: bool
    free_only: bool
    created_at: str


@dataclass(frozen=True)
class TradingResult:
    result_id: str
    request_id: str
    status: TradingStatus
    message: str
    account: AccountSnapshot | None
    positions: tuple[PositionSnapshot, ...]
    decision: TradingDecision
    notional: float
    created_at: str

    def __post_init__(self) -> None:
        _validate_utc(self.created_at)

    def to_json(self) -> str:
        return json.dumps(
            {
                "result_id": self.result_id,
                "request_id": self.request_id,
                "status": self.status.value,
                "message": self.message,
                "account": self.account.__dict__ if self.account else None,
                "positions": [position.__dict__ for position in self.positions],
                "decision": {
                    "request_id": self.decision.request_id,
                    "status": self.decision.status.value,
                    "action": self.decision.action.value,
                    "reasons": list(self.decision.reasons),
                    "approval_required": self.decision.approval_required,
                },
                "notional": self.notional,
                "created_at": self.created_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


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
    def get_account_snapshot(self) -> AccountSnapshot: ...
    def get_positions(self) -> tuple[PositionSnapshot, ...]: ...
    def validate_request(self, request: TradingRequest, policy: "TradingRiskPolicy") -> TradingDecision: ...
    def simulate_order(self, request: TradingRequest) -> TradingResult: ...
    def cancel_simulated_order(self, request: TradingRequest) -> TradingResult: ...
    def health_check(self) -> tuple[bool, str]: ...
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

    def get_account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot("paper-account", 1_000_000.0, 1_000_000.0, "KRW", "2026-07-17T00:00:00Z")

    def get_positions(self) -> tuple[PositionSnapshot, ...]:
        return ()

    def validate_request(self, request: TradingRequest, policy: "TradingRiskPolicy") -> TradingDecision:
        return policy.validate(request, self.get_account_snapshot(), self.get_positions(), seen_idempotency_keys=tuple(self._commands))

    def simulate_order(self, request: TradingRequest) -> TradingResult:
        decision = TradingDecision(request.request_id, TradingStatus.SIMULATED, TradingAction.SIMULATE_ORDER, (), False)
        return TradingResult(
            f"trading-result:{request.request_id}",
            request.request_id,
            TradingStatus.SIMULATED,
            "paper simulation completed; no live order was placed",
            self.get_account_snapshot(),
            self.get_positions(),
            decision,
            _notional(request),
            request.created_at,
        )

    def cancel_simulated_order(self, request: TradingRequest) -> TradingResult:
        decision = TradingDecision(request.request_id, TradingStatus.CANCELLED, TradingAction.CANCEL_SIMULATED_ORDER, (), False)
        return TradingResult(
            f"trading-result:{request.request_id}",
            request.request_id,
            TradingStatus.CANCELLED,
            "simulated order cancelled; no live order was placed",
            self.get_account_snapshot(),
            self.get_positions(),
            decision,
            0.0,
            request.created_at,
        )

    def health_check(self) -> tuple[bool, str]:
        return True, "fake trading adapter ready; live trading disabled"

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


@dataclass(frozen=True)
class TradingRiskPolicy:
    max_notional: float = 1_000_000.0
    max_position_quantity: float = 100.0
    allowed_order_types: tuple[OrderType, ...] = (OrderType.MARKET, OrderType.LIMIT)
    live_execution_enabled: bool = False
    adapter_enabled: bool = True

    def validate(
        self,
        request: TradingRequest,
        account: AccountSnapshot,
        positions: tuple[PositionSnapshot, ...],
        *,
        seen_idempotency_keys: tuple[str, ...] = (),
    ) -> TradingDecision:
        reasons: list[str] = []
        if not self.adapter_enabled:
            reasons.append("trading adapter is disabled")
        if request.intent in {TradingIntent.LIVE_BUY, TradingIntent.LIVE_SELL} or not request.simulation:
            reasons.append("live trading is not implemented")
        if request.order_type not in self.allowed_order_types:
            reasons.append("unsupported order type")
        if request.intent in {TradingIntent.SIMULATE_BUY, TradingIntent.SIMULATE_SELL} and request.quantity <= 0:
            reasons.append("quantity must be positive")
        if request.symbol:
            try:
                _validate_symbol(request.symbol)
            except ValueError:
                reasons.append("invalid symbol")
        elif request.intent is not TradingIntent.ANALYZE:
            reasons.append("symbol is required")
        notional = _notional(request)
        if notional > self.max_notional:
            reasons.append("max notional exceeded")
        current_quantity = sum(position.quantity for position in positions if position.symbol == request.symbol)
        projected = current_quantity + request.quantity if request.side == OrderSide.BUY else max(0.0, current_quantity - request.quantity)
        if projected > self.max_position_quantity:
            reasons.append("max position limit exceeded")
        if request.idempotency_key and request.idempotency_key in seen_idempotency_keys:
            reasons.append("duplicate trading request")
        if not account.currency:
            reasons.append("account currency is required")
        status = TradingStatus.REJECTED if reasons else TradingStatus.VALIDATED
        action = TradingAction.BLOCK_LIVE_EXECUTION if "live trading is not implemented" in reasons else _action_for_intent(request.intent)
        return TradingDecision(request.request_id, status, action, tuple(reasons), approval_required=bool(reasons and action == TradingAction.BLOCK_LIVE_EXECUTION))


class PaperTradingAdapter(FakeTradingAdapter):
    def __init__(self, *, adapter_enabled: bool = True, fail_simulation: bool = False) -> None:
        super().__init__(execution_enabled=False, market_open=True)
        self._adapter_enabled = adapter_enabled
        self._fail_simulation = fail_simulation
        self._account = AccountSnapshot("paper-account", 1_000_000.0, 1_000_000.0, "KRW", "2026-07-17T00:00:00Z")
        self._positions: dict[str, PositionSnapshot] = {}
        self._idempotency_keys: set[str] = set()

    def get_account_snapshot(self) -> AccountSnapshot:
        return self._account

    def get_positions(self) -> tuple[PositionSnapshot, ...]:
        return tuple(self._positions[symbol] for symbol in sorted(self._positions))

    def validate_request(self, request: TradingRequest, policy: TradingRiskPolicy) -> TradingDecision:
        effective_policy = replace(policy, adapter_enabled=policy.adapter_enabled and self._adapter_enabled)
        return effective_policy.validate(request, self.get_account_snapshot(), self.get_positions(), seen_idempotency_keys=tuple(self._idempotency_keys))

    def simulate_order(self, request: TradingRequest) -> TradingResult:
        if self._fail_simulation:
            raise RuntimeError("paper trading simulation failed")
        if not self._adapter_enabled:
            decision = TradingDecision(request.request_id, TradingStatus.REJECTED, TradingAction.SIMULATE_ORDER, ("trading adapter is disabled",), False)
            return _trading_result(request, TradingStatus.REJECTED, "paper adapter disabled", self.get_account_snapshot(), self.get_positions(), decision)
        if request.idempotency_key:
            self._idempotency_keys.add(request.idempotency_key)
        if request.intent in {TradingIntent.SIMULATE_BUY, TradingIntent.SIMULATE_SELL} and request.symbol:
            existing = self._positions.get(request.symbol)
            current = existing.quantity if existing else 0.0
            next_quantity = current + request.quantity if request.side == OrderSide.BUY else max(0.0, current - request.quantity)
            self._positions[request.symbol] = PositionSnapshot(request.symbol, next_quantity, request.limit_price or 0.0, next_quantity * (request.limit_price or 0.0), request.created_at)
        decision = TradingDecision(request.request_id, TradingStatus.SIMULATED, TradingAction.SIMULATE_ORDER, (), False)
        return _trading_result(request, TradingStatus.SIMULATED, "paper simulation completed; no live order was placed", self.get_account_snapshot(), self.get_positions(), decision)

    def cancel_simulated_order(self, request: TradingRequest) -> TradingResult:
        decision = TradingDecision(request.request_id, TradingStatus.CANCELLED, TradingAction.CANCEL_SIMULATED_ORDER, (), False)
        return _trading_result(request, TradingStatus.CANCELLED, "simulated order cancelled; no live order was placed", self.get_account_snapshot(), self.get_positions(), decision)

    def health_check(self) -> tuple[bool, str]:
        return self._adapter_enabled, "paper trading adapter ready; live trading disabled" if self._adapter_enabled else "paper trading adapter disabled"


class SQLiteTradingRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_request(self, request: TradingRequest) -> bool:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO trading_requests(request_id, intent, symbol, side, quantity, order_type, limit_price, actor_ref, created_at, simulation, approval_ref, idempotency_key)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _request_row(request),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def add_result(self, result: TradingResult) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT OR REPLACE INTO trading_results(result_id, request_id, status, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (result.result_id, result.request_id, result.status.value, result.to_json(), result.created_at),
            )

    def list_results(self) -> tuple[TradingResult, ...]:
        rows = self._connection.execute("SELECT payload_json FROM trading_results ORDER BY created_at, result_id").fetchall()
        return tuple(_result_from_json(str(row[0])) for row in rows)


class TradingExecutionService:
    def __init__(
        self,
        adapter: TradingAdapter,
        policy: TradingRiskPolicy,
        *,
        repository: SQLiteTradingRepository | None = None,
        event_store: Any | None = None,
        metrics: Any | None = None,
    ) -> None:
        self._adapter = adapter
        self._policy = policy
        self._repository = repository
        self._event_store = event_store
        self._metrics = metrics

    def execute(self, request: TradingRequest) -> TradingResult:
        if self._repository is not None and not self._repository.add_request(request):
            decision = TradingDecision(request.request_id, TradingStatus.REJECTED, _action_for_intent(request.intent), ("duplicate trading request",), False)
            result = _trading_result(request, TradingStatus.REJECTED, "duplicate trading request rejected", self._adapter.get_account_snapshot(), self._adapter.get_positions(), decision)
            self._record("TradingRequestRejected", request, result)
            _increment(self._metrics, "gaon_trading_rejections_total")
            self._repository.add_result(result)
            return result
        self._record("TradingRequestCreated", request, None)
        _increment(self._metrics, "gaon_trading_requests_total")
        try:
            decision = self._adapter.validate_request(request, self._policy)
            if decision.status == TradingStatus.REJECTED:
                result = _trading_result(request, TradingStatus.BLOCKED if decision.action == TradingAction.BLOCK_LIVE_EXECUTION else TradingStatus.REJECTED, "; ".join(decision.reasons), self._adapter.get_account_snapshot(), self._adapter.get_positions(), decision)
                self._record("TradingExecutionBlocked" if result.status == TradingStatus.BLOCKED else "TradingRequestRejected", request, result)
                _increment(self._metrics, "gaon_trading_execution_blocked_total" if result.status == TradingStatus.BLOCKED else "gaon_trading_rejections_total")
                if self._repository is not None:
                    self._repository.add_result(result)
                return result
            self._record("TradingRequestValidated", request, None)
            if request.intent is TradingIntent.ANALYZE:
                result = _trading_result(request, TradingStatus.VALIDATED, "paper account inspected; no live account access performed", self._adapter.get_account_snapshot(), self._adapter.get_positions(), decision)
            elif request.intent is TradingIntent.CANCEL_SIMULATED_ORDER:
                result = self._adapter.cancel_simulated_order(request)
            else:
                self._record("PaperTradeStarted", request, None)
                result = self._adapter.simulate_order(request)
                _increment(self._metrics, "gaon_paper_trades_total")
            self._record("PaperTradeCompleted" if result.status in {TradingStatus.SIMULATED, TradingStatus.CANCELLED} else "TradingRequestValidated", request, result)
            if self._repository is not None:
                self._repository.add_result(result)
            return result
        except Exception as exc:  # noqa: BLE001 - adapter failure must not crash runtime.
            decision = TradingDecision(request.request_id, TradingStatus.FAILED, _action_for_intent(request.intent), (exc.__class__.__name__,), False)
            result = _trading_result(request, TradingStatus.FAILED, "paper trading failed safely", None, (), decision)
            self._record("PaperTradeFailed", request, result)
            _increment(self._metrics, "gaon_paper_trade_failures_total")
            if self._repository is not None:
                self._repository.add_result(result)
            return result

    def _record(self, event_type: str, request: TradingRequest, result: TradingResult | None) -> None:
        if self._event_store is not None:
            self._event_store.append(trading_event(event_type, request, result))


def trading_event(event_type: str, request: TradingRequest, result: TradingResult | None):
    from gaon.runtime.event_store import DurableEvent

    return DurableEvent(
        event_id=f"event:trading:{event_type}:{request.request_id}:{result.result_id if result else request.created_at}",
        event_type=event_type,
        occurred_at=request.created_at,
        actor_ref=request.actor_ref,
        correlation_id=request.request_id,
        causation_id=None,
        scope="trading",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={"request_id": request.request_id, "intent": request.intent.value, "status": result.status.value if result else TradingStatus.CREATED.value},
        evidence_refs=(),
        audit_refs=(),
        appended_at=request.created_at,
    )


def record_trading_metrics(metrics: Any, results: tuple[TradingResult, ...]) -> None:
    metrics.gauge("gaon_trading_results_total", float(len(results)), component="trading")


def build_trading_request(
    request_id: str,
    intent: TradingIntent,
    *,
    symbol: str = "",
    quantity: float = 0.0,
    price: float | None = None,
    actor_ref: str = "actor:redacted",
    created_at: str,
    idempotency_key: str | None = None,
) -> TradingRequest:
    side = OrderSide.BUY if intent in {TradingIntent.SIMULATE_BUY, TradingIntent.LIVE_BUY} else OrderSide.SELL if intent in {TradingIntent.SIMULATE_SELL, TradingIntent.LIVE_SELL} else None
    return TradingRequest(request_id, intent, symbol, side, quantity, OrderType.LIMIT if price else OrderType.MARKET, price, actor_ref, created_at, simulation=intent not in {TradingIntent.LIVE_BUY, TradingIntent.LIVE_SELL}, idempotency_key=idempotency_key)


def _request_row(request: TradingRequest) -> tuple[object, ...]:
    return (
        request.request_id,
        request.intent.value,
        request.symbol,
        request.side.value if request.side else None,
        request.quantity,
        request.order_type.value,
        request.limit_price,
        request.actor_ref,
        request.created_at,
        1 if request.simulation else 0,
        request.approval_ref,
        request.idempotency_key,
    )


def _trading_result(request: TradingRequest, status: TradingStatus, message: str, account: AccountSnapshot | None, positions: tuple[PositionSnapshot, ...], decision: TradingDecision) -> TradingResult:
    return TradingResult(f"trading-result:{request.request_id}", request.request_id, status, message, account, positions, decision, _notional(request), request.created_at)


def _result_from_json(value: str) -> TradingResult:
    payload = json.loads(value)
    account_payload = payload.get("account")
    decision_payload = payload["decision"]  # type: ignore[index]
    account = AccountSnapshot(**account_payload) if isinstance(account_payload, dict) else None
    positions = tuple(PositionSnapshot(**item) for item in payload["positions"])  # type: ignore[index]
    decision = TradingDecision(
        str(decision_payload["request_id"]),  # type: ignore[index]
        TradingStatus(str(decision_payload["status"])),  # type: ignore[index]
        TradingAction(str(decision_payload["action"])),  # type: ignore[index]
        tuple(str(item) for item in decision_payload["reasons"]),  # type: ignore[index]
        bool(decision_payload["approval_required"]),  # type: ignore[index]
    )
    return TradingResult(str(payload["result_id"]), str(payload["request_id"]), TradingStatus(str(payload["status"])), str(payload["message"]), account, positions, decision, float(payload["notional"]), str(payload["created_at"]))


def _action_for_intent(intent: TradingIntent) -> TradingAction:
    if intent is TradingIntent.ANALYZE:
        return TradingAction.ANALYZE
    if intent is TradingIntent.CANCEL_SIMULATED_ORDER:
        return TradingAction.CANCEL_SIMULATED_ORDER
    if intent in {TradingIntent.LIVE_BUY, TradingIntent.LIVE_SELL}:
        return TradingAction.BLOCK_LIVE_EXECUTION
    return TradingAction.SIMULATE_ORDER


def _notional(request: TradingRequest) -> float:
    return request.quantity * (request.limit_price or 0.0)


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _validate_symbol(symbol: str) -> None:
    if SYMBOL_PATTERN.fullmatch(symbol) is None:
        raise ValueError("invalid symbol")


def _increment(metrics: Any | None, name: str) -> None:
    if metrics is not None:
        metrics.increment(name, component="trading")
