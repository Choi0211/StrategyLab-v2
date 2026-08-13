# Hotfix 248.1 - Real Robustness Execution

Status: COMPLETE

## Context

Sprint 241-248 added a production-grade validation envelope for Autonomous
Quant Partner. Review found that several robustness sections returned
deterministic-looking success metrics even when no peer-symbol, OOS,
walk-forward, regime, parameter, cost-stress, or Monte Carlo execution evidence
was present.

## Problem

The production path could present validation confidence that was not backed by
an authoritative backtest or robustness execution artifact. This violated the
Verified Evidence First contract even though trading, promotion, and mutation
safety boundaries remained disabled.

## Fix

Production-grade validation now treats robustness execution as evidence input:

- Executed sections pass through only when they carry actual execution lineage.
- Missing sections return explicit `not_run`, `not_supported`, or
  missing-evidence states.
- Unified promotion readiness requires every robustness gate to be executed
  before `requires_human_approval` is possible.
- Monte Carlo is computed only from actual trade-return series, or from an
  explicit executed Monte Carlo artifact.
- Signal pairwise counts are no longer derived from broad `min()` estimates;
  absent exact pairwise diagnostics are reported as `not_available`.

Release checks may still inject deterministic actual-execution evidence for
repeatable CI, but production payload construction does not synthesize peer,
OOS, fold, regime, parameter, cost, or Monte Carlo metrics from trade count
alone.

## Contracts

- No fabricated validation metrics.
- No metadata-only or fixture evidence in production promotion readiness.
- No live trading, KIS/Broker order, Champion auto-promotion, approval bypass,
  or strategy mutation.
- Schema remains v36.

## Release Checks

New release checks:

- `gaon-production-no-fabricated-validation-metrics-release-check`
- `gaon-production-real-multi-symbol-validation-release-check`
- `gaon-production-real-oos-validation-release-check`
- `gaon-production-real-walk-forward-release-check`
- `gaon-production-real-regime-validation-release-check`
- `gaon-production-real-parameter-sensitivity-release-check`
- `gaon-production-real-transaction-cost-stress-release-check`
- `gaon-production-real-monte-carlo-release-check`
- `gaon-production-real-robustness-execution-release-check`

## Rollback

Revert the hotfix commit. This restores the prior Sprint 241-248 validation
renderer behavior, but also restores the fabricated robustness-metric risk.
