# Sprint 181 - Strategy Experiment Builder

Status: COMPLETE

## Context

Sprint 180 produces proposed evidence-backed hypotheses. Sprint 181 turns those
hypotheses into immutable, validation-ready experiment contracts.

## Problem

Gaon needs a structured way to say exactly what should be tested before any
backtest or promotion logic runs.

## Goal

- Build `StrategyResearchExperiment` records from proposed hypotheses.
- Preserve baseline strategy fingerprint and assumptions fingerprint.
- Preserve universe, period, changed-rule, and cost-model inputs.
- Keep experiment creation separate from execution.

## Non-goals

- No backtest execution.
- No validation result.
- No production approval.
- No strategy mutation, Champion promotion, or trading.

## Scope

`StrategyExperimentBuilder` validates a proposed, untested hypothesis and emits
a deterministic experiment ID. Invalid period, missing universe, missing
baseline, missing assumptions, or already-tested hypotheses are blocked.

## Contracts and Invariants

- Hypothesis must be `proposed` and untested.
- Baseline and assumptions fingerprints are immutable inputs.
- Universe symbols are canonicalized by stable sorting.
- `backtest_executed=false` and `tested=false` at creation.

## Acceptance Criteria

- Proposed hypothesis yields `ready_for_validation`.
- Symbol order does not change experiment ID.
- Tested hypothesis is blocked.
- Invalid period and missing universe are blocked.
- Release check passes without schema migration.

## Test Matrix

- `tests/unit/test_strategy_experiment.py`
- `python -m gaon.runtime.cli gaon-strategy-experiment-builder-release-check`
- Full unit and integration suites.
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-strategy-experiment-builder-release-check
```

## Rollback

Remove the Sprint 181 experiment module, tests, and CLI release-check
registration. No schema or persistent state changes are introduced.

## Documentation

README, changelog, release notes, and test results record the experiment
builder.

## Completion Checklist

- [x] Experiment model and builder implemented.
- [x] Immutable fingerprints preserved.
- [x] No execution on creation.
- [x] Release check added.
- [x] Schema v36 preserved.
