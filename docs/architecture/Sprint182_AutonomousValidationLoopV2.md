# Sprint 182 - Autonomous Validation Loop v2

Status: COMPLETE

## Context

Sprint 181 creates immutable strategy experiment contracts from proposed
evidence-backed hypotheses. Sprint 182 attaches authoritative validation
evidence to those experiments and decides whether the result can progress to
review.

## Problem

Autonomous research needs a gate between proposed experiments and downstream
ranking. That gate must not execute backtests itself, fabricate metrics, or
turn fixture evidence into production approval.

## Goal

Add a read-only validation loop that accepts only structured authoritative
evidence for the same experiment, detects insufficient samples, blocks
quality failures, and preserves the no-mutation safety boundary.

## Non-goals

- No backtest execution.
- No Champion promotion.
- No production approval.
- No strategy configuration mutation.
- No schema migration.

## Scope

- `AuthoritativeValidationEvidence`
- `ValidationLoopV2Result`
- `AutonomousValidationLoopV2`
- `gaon-validation-loop-v2-release-check`

## Contracts and Invariants

- Evidence must match the experiment ID.
- Blocking quality findings fail closed.
- Metric values must be internally consistent with structured fields.
- Low sample size is reported as needs-more-evidence, not fabricated
  confidence.
- Fixture-backed evidence remains explicitly marked as fixture-backed.
- No execution, order, approval, or strategy mutation happens in this layer.

## Acceptance Criteria

- Ready experiments with authoritative metrics are accepted for review.
- Low trade counts return `needs_more_evidence`.
- Experiment mismatch and data-quality failures are blocked.
- Fabricated trade-count mismatches are blocked.
- Release check passes without database writes.

## Test Matrix

- `tests.unit.test_validation_loop_v2`
- `gaon-validation-loop-v2-release-check`
- Full unit and integration suites
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-validation-loop-v2-release-check
```

## Rollback

Remove the Sprint 182 validation loop module, tests, CLI command, and
documentation entries. No schema rollback is required.
