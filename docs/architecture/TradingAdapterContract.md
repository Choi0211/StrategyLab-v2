# Trading Adapter Contract

Status: Sprint 23 v2 release candidate contract

The public repository defines broker-free adapter contracts only. It does not connect to a live broker, private account, KIS API, or MyMoneyGuard runtime.

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
- private MyMoneyGuard imports
- automatic order approval
- Telegram-triggered order execution
