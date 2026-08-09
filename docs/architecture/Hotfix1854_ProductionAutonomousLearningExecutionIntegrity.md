# Hotfix 185.4 Production Autonomous Learning Execution Integrity

Status: COMPLETE

## Context

Telegram Autonomous Learning V2 was wired through
`autonomous_learning_e2e_release_check()`. That release check intentionally uses
fixture discovery, fixture transport, fixture experiment/backtest helpers, and
`allow_fixture=True` so deterministic release checks can reach a human approval
boundary without network or real market dependencies.

That fixture-only execution path is not valid for production Telegram.

## Fix

- Production Telegram now calls `telegram_autonomous_learning_payload()`, which
  starts from the existing `krx_real_research_payload()` baseline and its TESTED
  candidate backtests.
- The release-check E2E path remains isolated in
  `autonomous_learning_e2e_release_check()`.
- Production candidate validation uses only the candidate `backtest_result`
  already produced by the KRX real-research engine.
- Candidate strategy fingerprint must match the candidate backtest strategy
  fingerprint.
- Fixture baseline/candidate evidence blocks production promotion and does not
  request human approval.
- External research execution uses the existing bounded discovery orchestration;
  if only metadata or no safely acquired content is available, production marks
  the candidate as needing real validation instead of pretending evidence was
  read.

## Invariants

- Production Telegram does not call release-check fixture helpers.
- `allow_fixture=True` remains release-check only.
- Fixture-backed evidence cannot create an eligible production promotion
  candidate.
- Changed rules require an actually executed candidate backtest. Unimplemented
  rules do not fabricate results.
- No KIS/Broker order, live trading, Champion auto-promotion, approval bypass, or
  strategy mutation.
- Schema remains v36 for runtime storage; the payload schema is v2.

## Release Check

```bash
python -m gaon.runtime.cli gaon-production-autonomous-learning-execution-release-check
```

The check proves:

- `production_uses_release_fixture=false`
- `fixture_promotion_blocked=true`
- `candidate_backtest_authoritative=true`
- `candidate_strategy_fingerprint_matched=true`
- `real_data_required=true`
- `strategy_mutated=false`
- `order_executed=false`
- `safety=pass`
