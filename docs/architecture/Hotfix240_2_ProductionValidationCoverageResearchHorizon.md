# Hotfix 240.2 - Production Validation Coverage & Research Horizon

Status: COMPLETE

## Context

Production Telegram proved that Hotfix 240.1 routes Autonomous Quant Partner
responses correctly, but the authoritative baseline showed `bars=unknown` and
`trade_count=1`. The blocker is validation coverage, not routing.

## Root Cause

The production KRX real-research pipeline used an implicit short default window
(`2026-01-01` to `2026-07-10`) when the Telegram request did not provide dates.
The partner then consumed only a shallow `trade_count` sample diagnostic, so bar
counts, warmup, signal counts, and horizon provenance were not preserved through:

market data -> backtest -> validation evidence -> Autonomous Quant Partner ->
Telegram rendering.

## Design

- Added a bounded production validation horizon policy: `1y -> 3y -> 5y`.
- The policy extends only the validation window. It does not relax strategy
  rules, change filters, change stops, or mutate configuration.
- Added a structured validation coverage contract with requested/actual period,
  raw/usable/warmup/dropped bars, entry/exit/completed/open trade counts,
  minimum required trades, horizon days/bars, sufficiency status/reasons,
  signal diagnostics, cost assumptions, and comparison window fingerprint.
- Added candidate validation coverage parity so baseline/candidates share the
  same source, date window, and assumption fingerprint unless explicitly marked.
- Tournament ranking now records whether sample sufficiency gates ranking.

## Sample Sufficiency

The minimum production sample remains 30 completed trades. Results below that
remain `insufficient_trades` and promotion is not justified by headline metrics.

Supported detailed statuses:

- `sufficient`
- `insufficient_trades`
- `insufficient_bars`
- `insufficient_signals`
- `data_quality_failure` where quality blocks execution

## Telegram Rendering

The Autonomous Quant Partner section now renders:

- validation period
- raw and usable bars
- warmup bars
- entry/exit/completed trade counts
- minimum required trades
- sample sufficiency status and reasons
- horizon extension attempts
- multi-symbol, out-of-sample, walk-forward status
- signal diagnostics
- tournament ranking gate

`bars=unknown` is no longer acceptable when authoritative coverage exists.

## Release Checks

Added:

- `gaon-production-validation-coverage-release-check`
- `gaon-production-research-horizon-release-check`
- `gaon-production-sample-sufficiency-release-check`
- `gaon-production-backtest-signal-diagnostic-release-check`
- `gaon-production-validation-window-integrity-release-check`
- `gaon-production-autonomous-validation-coverage-release-check`

## Safety

Schema remains v36. No live trading, KIS/Broker order, automatic Champion
promotion, approval bypass, strategy mutation, fixture promotion evidence, or
fabricated metrics were added.
