# Paper Trading Forward Test

Sprint 45 connects the approved active Champion to a paper-only forward-test workflow.

The workflow reuses the existing `PaperTradingAdapter`, `TradingExecutionService`, `TradingRiskPolicy`, and `SQLiteTradingRepository`. It does not create a live broker route and does not connect to KIS or MyMoneyGuard.

## Flow

```text
Champion Registry
-> Paper Session Create
-> Start
-> Simulated Paper Orders
-> Observations
-> Performance Summary
-> Future Revalidation Gate
```

Paper results never promote to live trading automatically. Sprint 46 or later must define any revalidation, rollback, or kill gate behavior.

## Policy

Policy version: `paper_forward_test_policy_v1`

The policy records future-readiness metadata:

- minimum session duration placeholder
- minimum simulated trade count
- optional maximum paper drawdown field
- Champion fingerprint must remain unchanged during the session

Unavailable metrics such as realized PnL, unrealized PnL, drawdown, and exposure are not fabricated.

## Persistence

Schema v16 adds:

- `paper_trading_sessions`
- `paper_trading_observations`
- `paper_trading_summaries`

The same runtime DB also keeps Champion registry state and paper trading request/result records.

## Safety

Only the currently active Champion version can create or run a paper session. Stale former Champions, unapproved candidates, unknown strategies, and fingerprint mismatches are rejected.

No live KIS, broker credentials, real orders, automatic trading, automatic approval, paper-to-live promotion, or MyMoneyGuard dependency is introduced.
