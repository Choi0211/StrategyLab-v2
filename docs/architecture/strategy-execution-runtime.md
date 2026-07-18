# Strategy Execution Runtime

Sprint 47 adds a unified Strategy Execution Runtime with explicit mode gates.

Supported modes:

- `DISABLED`
- `PAPER`
- `LIVE`

Default mode is `DISABLED`. No implicit paper or live execution is started.

## Policy

Policy version: `strategy_execution_policy_v1`

Core gates:

- active Champion is required
- Champion version and fingerprint must match the request
- stale Champion plans are blocked at run time
- duplicate active runs are blocked
- `KILL`, `HOLD`, and `ROLLBACK_RECOMMENDED` revalidation statuses block live execution
- `LIVE_ELIGIBLE` is required for live planning but is not enough to place orders
- live trading remains blocked because the live broker adapter is unavailable until a future sprint

## Runtime Behavior

`PAPER` execution reuses the existing `PaperTradingAdapter`, `TradingExecutionService`, `TradingRiskPolicy`, and SQLite trading repository.

`LIVE` execution always produces `BLOCKED` in Sprint 47. This is intentional, even if live trading is explicitly configured later, because no live broker adapter exists in this public repository.

## Persistence

Schema v18 adds:

- `strategy_execution_plans`
- `strategy_execution_runs`

## Safety

The runtime does not connect to KIS, broker credentials, real orders, MyMoneyGuard, or paid providers. It does not automatically promote Champions, rollback Champions, approve execution, or replay live side effects.
