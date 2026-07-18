# Paper Revalidation And Kill/Rollback Gates

Sprint 46 evaluates Paper Forward Test evidence and produces deterministic safety decisions.

`LIVE_ELIGIBLE` means technically eligible for future live consideration only. It does not enable live trading, connect KIS, place broker orders, or approve execution.

## Policy

Policy version: `paper_revalidation_policy_v1`

Default gates:

- completed paper session required for `LIVE_ELIGIBLE`
- minimum simulated trades: 20
- maximum paper drawdown: 20%
- hard kill paper drawdown: 35%
- zero critical execution errors
- active Champion fingerprint must match the paper session and summary
- missing optional metrics are not fabricated

## Decisions

- `LIVE_ELIGIBLE`: completed, sufficient paper evidence, no critical risk signal
- `HOLD`: incomplete session, insufficient trade count, unavailable mandatory comparability
- `KILL`: corrupt state, critical execution error, fingerprint mismatch, impossible metric, extreme drawdown
- `ROLLBACK_RECOMMENDED`: material paper deterioration that requires explicit human/admin rollback through Sprint 44
- `REVIEW`: missing optional metrics or ambiguous evidence

## Persistence

Schema v17 adds:

- `paper_revalidation_requests`
- `paper_revalidation_reports`

## Safety

The engine records a durable safety decision only. It does not rollback Champions, change the registry, enable live trading, send orders, or access MyMoneyGuard.
