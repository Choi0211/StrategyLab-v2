# Trading Adapter Contract

Status: Sprint 40 safe trading adapter foundation

The public repository defines broker-free adapter contracts only. It does not connect to a live broker, private account, KIS API, or MyMoneyGuard runtime.

Live trading is not implemented.

## Sprint 40 Structured Boundary

Sprint 40 adds structured non-live trading models:

- `TradingIntent`
- `TradingAction`
- `OrderSide`
- `OrderType`
- `TradingRequest`
- `TradingDecision`
- `TradingExecutionContext`
- `TradingResult`
- `TradingStatus`
- `AccountSnapshot`
- `PositionSnapshot`
- `TradingRiskPolicy`

Only fake and paper adapters are implemented. Live broker adapters remain disabled and unimplemented.

## Read-Only Methods

- `account_summary`
- `positions`
- `market_status`
- `runtime_status`

## Command Lifecycle

Order commands move through:

`PROPOSED -> VALIDATED -> APPROVED -> EXECUTED`

They may also become `CANCELLED` or `REJECTED`.

Execution is disabled by default. Even the fake adapter raises `PermissionError` unless `execution_enabled=True` and the command carries an approval reference.

## Risk Gates

The public contract defines risk-gate checks for:

- max holdings
- max order value
- daily loss limit
- duplicate order prevention
- market-hours check
- emergency stop

## Boundaries

Not included:

- live broker connection
- broker credentials
- account IDs
- KIS REST or WebSocket
- real account access
- real order execution
- private MyMoneyGuard imports
- automatic order approval
- Telegram-triggered order execution
