# Sprint 185 - Human-gated Autonomous Research Promotion

Status: COMPLETE

## Context

Sprints 175-184 build the safe path from external source normalization through
evidence-backed hypotheses, immutable experiments, validation, ranking, and an
approval-required promotion candidate. Sprint 185 adds the final human gate.

## Problem

Autonomous research must never activate production strategy changes by itself.
Even when a candidate is ranked and approved by a human, StrategyLab must keep
the result manual-application only unless a future sprint explicitly adds a
separate audited mutation workflow.

## Goal

Validate explicit human approval tokens for promotion candidates and return an
auditable manual-application result while preserving all execution and trading
safety boundaries.

## Non-goals

- No strategy configuration mutation.
- No Champion promotion.
- No broker or KIS order.
- No Telegram config mutation.
- No schema migration.

## Scope

- `HumanGatedPromotionService`
- `HumanApprovalReceipt`
- `HumanGatedPromotionResult`
- `gaon-human-gated-promotion-release-check`
- `gaon-autonomous-learning-production-gate-release-check`

## Contracts and Invariants

- Missing approval remains `awaiting_human_approval`.
- Invalid approval token blocks fail closed.
- Valid approval returns `approved_for_manual_application`.
- Approval token is never stored or printed; only its digest is retained.
- Manual application remains required.
- No automatic Champion promotion, strategy mutation, or order execution.

## Acceptance Criteria

- Missing approval does not mutate state.
- Invalid token is blocked.
- Valid token creates an auditable manual-only approval result.
- Aggregate production gate release check passes.

## Test Matrix

- `tests.unit.test_human_gated_promotion`
- `gaon-human-gated-promotion-release-check`
- `gaon-autonomous-learning-production-gate-release-check`
- Full unit and integration suites
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-human-gated-promotion-release-check
python -m gaon.runtime.cli gaon-autonomous-learning-production-gate-release-check
```

## Rollback

Remove the Sprint 185 human gate module, tests, CLI commands, and
documentation entries. No schema rollback is required.
