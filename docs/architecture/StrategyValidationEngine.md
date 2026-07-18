# Strategy Validation Engine

Status: Sprint 42

The Strategy Validation Engine evaluates normalized Sprint 41 `BacktestResult` objects and produces deterministic `ValidationReport` records.

Validation PASS does not automatically promote or deploy a strategy.

## Flow

```text
BacktestRequest
-> BacktestAdapter
-> normalized BacktestResult
-> StrategyValidationEngine
-> ValidationReport
-> PASS / FAIL / REVIEW
-> future Champion/Challenger Engine
```

The engine does not create a parallel backtest model. It reads `BacktestResult`, `BacktestMetrics`, trade summary, strategy reference, dataset reference, fingerprint, and reproducibility metadata.

## Contracts

- `ValidationRequest`
- `ValidationPolicy`
- `ValidationRule`
- `ValidationRuleResult`
- `ValidationReport`
- `ValidationStatus`
- `ValidationSeverity`
- `ValidationEvidence`

`ValidationStatus` values:

- `PASS`: all hard rules pass and no review rule is unresolved.
- `FAIL`: at least one hard-fail rule failed.
- `REVIEW`: no hard-fail rule failed, but policy requires human review for missing or weak evidence.

## Default Policy

`validation_policy_v1` is conservative and deterministic:

- trade count must be at least 30
- maximum drawdown must be at most 30%
- profit factor must be at least 1.1 when available
- sample period must be at least 180 days
- reproducibility fingerprint is required

These are configurable defaults, not user-specific investment preferences.

## MDD Convention

The internal drawdown convention is a positive fraction from `0.0` to `1.0`.

Accepted inputs:

- `-0.20` means 20% drawdown
- `0.20` means 20% drawdown
- `20.0` means 20% drawdown

Impossible or ambiguous values outside the supported range fail closed.

## Optional Metrics

Missing optional metrics are not fabricated. Policy decides whether missing values are skipped, reviewed, or failed. In `validation_policy_v1`, missing `profit_factor` causes `REVIEW`.

## Multi-Run Readiness

The engine accepts multiple `BacktestResult` records for the same validation request. Sprint 42 supports deterministic aggregation checks:

- passing window ratio
- catastrophic drawdown window detection
- one-window dominance warning

It does not implement parameter optimization, walk-forward search, Champion ranking, or Challenger ranking.

## Overfitting Warnings

Sprint 42 includes heuristic warnings only:

- very high return with low trade count
- very high win rate with tiny sample
- one window dominates aggregate return

These warnings are not statistical proof of overfitting.

## Persistence, Events, Metrics

Runtime schema v13 adds:

- `validation_requests`
- `validation_reports`

Lifecycle events:

- `ValidationRequested`
- `ValidationStarted`
- `ValidationCompleted`
- `ValidationFailed`
- `ValidationReviewRequired`

Metrics:

- `gaon_validation_requests_total`
- `gaon_validation_pass_total`
- `gaon_validation_fail_total`
- `gaon_validation_review_total`
- `gaon_validation_errors_total`

## Safety Boundary

Validation does not perform Champion promotion, active strategy switching, paper trading promotion, live KIS access, broker orders, automatic trading, automatic approval, MyMoneyGuard integration, network access, or paid-provider fallback.
