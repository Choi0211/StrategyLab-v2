# Hotfix 256.1 - Validation Semantics & Leakage Integrity

Status: IMPLEMENTED

## Context

Sprint 249-256 connected Autonomous Quant Partner robustness sections to the
real rule-based backtest engine. A review found that some validation labels
still treated successful execution as a passing validation result, and OOS /
walk-forward windows could include warmup-period trades in performance metrics.

## Problem

Production validation must distinguish "the engine ran" from "the candidate
passed evidence-backed validation." Indicator warmup bars are allowed, but
trades, PnL, and performance metrics used for OOS or fold validation must come
only from the evaluation window.

## Design

- OOS and walk-forward validation now run the engine on warmup plus evaluation
  bars, then filter trades and rebuild metrics from evaluation-window trades
  only.
- Each evaluated section reports `execution_status` separately from
  `validation_status`; `status` tracks the validation result.
- Candidate validation is baseline-relative and sample-aware. A low-sample
  positive return cannot pass, and underperformance versus baseline fails.
- Candidate strategy fingerprints are frozen before OOS and reused across all
  walk-forward folds.
- Regime validation uses deterministic price return and realized-volatility
  classification instead of fixed chronological labels or macro narratives.
- Cost stress compares baseline and candidate metrics under bounded scenarios
  with explicit assumption provenance.
- Peer selection records policy, candidate universe size, selected peers, and
  selection reasons. Curated fallback is declared when a dynamic universe is not
  available.

## Invariants

- No live trading, KIS/Broker order, automatic Champion promotion, approval
  bypass, or strategy mutation.
- No fixture-backed promotion evidence in production paths.
- No fabricated validation metrics.
- Schema v36 remains unchanged.
- Missing lineage or fingerprint mismatch is fail-closed.

## Release Checks

New release checks:

- `gaon-production-oos-evaluation-boundary-release-check`
- `gaon-production-walk-forward-evaluation-boundary-release-check`
- `gaon-production-oos-performance-comparison-release-check`
- `gaon-production-walk-forward-performance-comparison-release-check`
- `gaon-production-real-regime-classification-release-check`
- `gaon-production-cost-stress-performance-release-check`
- `gaon-production-peer-selection-policy-release-check`
- `gaon-production-validation-execution-vs-result-status-release-check`
- `gaon-production-candidate-freeze-integrity-release-check`
- `gaon-production-no-evaluation-window-contamination-release-check`
- `gaon-production-hotfix2561-release-check`

Each emits `check_mode=deterministic_release_validation`.

## Rollback

Rollback is code-only. Revert the hotfix commit to restore the previous
validation semantics. No database migration or cleanup is required.
