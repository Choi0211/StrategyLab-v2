# Sprint 249-256 Real Autonomous Research Execution

Status: COMPLETE

## Context

Sprint 241-248 and Hotfix 248.1 made Autonomous Quant Partner fail closed when
production-grade robustness sections were missing actual execution lineage. The
next step is to wire those sections to existing real-data/backtest execution
instead of treating them as report-only placeholders.

## Goal

Run production autonomous research validation from authoritative structured
inputs: real multi-symbol peer validation, out-of-sample validation,
walk-forward validation, regime validation, bounded parameter variants,
transaction-cost stress scenarios, Monte Carlo over actual trade returns,
provider-state/provenance reporting, and a bounded action loop with explicit
budget stop reasons.

## Non-goals

- No live trading.
- No KIS or broker orders.
- No automatic Champion promotion.
- No approval bypass.
- No strategy configuration mutation before explicit approval.
- No fabricated metrics or fixture-backed production promotion evidence.
- No schema migration unless persistence contracts require it.

## Architecture

`autonomous_quant_partner_payload()` reconstructs the authoritative
`MarketDataset`, `CanonicalStrategySpec`, and execution assumptions from the
baseline real-research payload when no `production_robustness_execution` block
is already present. It then runs the existing `RuleBasedBacktestEngine` for the
primary strategy and validation slices.

Telegram production passes its SQLite connection into the partner payload. When
peer datasets are not embedded in the baseline, peer execution may fetch peer
symbols through `build_market_data_provider_from_env()` and `KRXDatasetBuilder`
only when `GAON_REAL_MARKET_DATA_ENABLED` is enabled. If real peer data or
quality eligibility is unavailable, the section reports an explicit
non-execution blocker instead of fabricating cross-symbol evidence.

Release checks use deterministic real-labeled execution inputs with
`fixture_backed=false` so the validation code path is exercised without
external network access. Those release inputs are not production Telegram
results.

## Contracts And Invariants

- Fixture-backed baselines are blocked for production robustness execution.
- Missing or malformed baseline lineage produces explicit `not_run` blockers.
- Multi-symbol validation does not rewrite the primary trade count.
- OOS, walk-forward, regime, parameter, cost stress, and Monte Carlo reports
  require actual execution lineage.
- Monte Carlo uses actual trade return series only; it creates no new market
  evidence.
- Provider-not-configured states remain honest.
- YouTube remains exploratory-only.
- Promotion readiness remains blocked unless independent evidence and real
  validation are sufficient.

## Acceptance Criteria

- All Sprint 249-256 release checks pass.
- Production Telegram Autonomous Learning passes the current DB connection to
  the partner execution path.
- Peer validation attempts use the existing real KRX provider path when the
  environment is configured and baseline peer datasets are absent.
- Missing peer data, missing trade returns, or insufficient validation remain
  blocking or `not_run` states.
- No orders, strategy mutations, approval bypass, or auto-promotion occur.

## Test Matrix

- Unit tests cover release-check aggregation, no-fabrication gates, production
  peer provider wiring, and approval blocking.
- Integration tests cover CLI command registration through the Telegram
  conversation agent release-check list.
- Release checks cover each execution category and the aggregate Sprint 249-256
  gate.

## Operational Verification

```bash
.venv/bin/python -m gaon.runtime.cli deployment-import-path-check \
  --expected-source /opt/strategylab-v2/src/gaon
.venv/bin/python -m gaon.runtime.cli gaon-production-sprint249-256-release-check
```

For live provider inspection, enable real market data explicitly:

```bash
GAON_REAL_MARKET_DATA_ENABLED=true \
GAON_MARKET_DATA_PROVIDER=yahoo-chart \
.venv/bin/python -m gaon.runtime.cli gaon-production-real-multi-symbol-execution-release-check
```

## Rollback

Rollback is code-only. Revert the Sprint 249-256 commit and redeploy editable
source. No schema migration is introduced.

## Completion Checklist

- [x] Real execution path added.
- [x] Telegram connection propagation added.
- [x] Release checks added.
- [x] Targeted local tests pass.
- [x] Full unit test suite pass recorded.
- [x] Full integration test suite pass recorded.
- [x] Release verification pass recorded.
- [x] Production verification pending after deployment is documented.
