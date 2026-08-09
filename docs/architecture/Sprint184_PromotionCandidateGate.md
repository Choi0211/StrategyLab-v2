# Sprint 184 - Promotion Candidate Gate

Status: COMPLETE

## Context

Sprint 183 ranks accepted validation evidence. Sprint 184 converts the top
ranked item into a reviewable promotion candidate that explicitly requires
human approval.

## Problem

Ranking a strategy candidate must never be interpreted as production
activation. The system needs a gate that preserves rollback information and
blocks fixture-backed production candidates.

## Goal

Add a promotion candidate gate that creates approval-required candidate
records from real ranked evidence while preserving all safety boundaries.

## Non-goals

- No approval token consumption.
- No Champion promotion.
- No strategy configuration mutation.
- No broker or KIS order.
- No schema migration.

## Scope

- `PromotionCandidateGate`
- `PromotionCandidateRecord`
- `gaon-promotion-candidate-gate-release-check`

## Contracts and Invariants

- Ranked output is review-only.
- Fixture-backed candidates are blocked for production by default.
- Every candidate requires human approval.
- Rollback target is preserved.
- No promotion, mutation, or order execution happens in the gate.

## Acceptance Criteria

- Real ranked evidence becomes `requires_human_approval`.
- Fixture-backed evidence is blocked for production use.
- Unranked or ineligible candidates are blocked.
- Release check verifies approval requirement and safety flags.

## Test Matrix

- `tests.unit.test_promotion_gate`
- `gaon-promotion-candidate-gate-release-check`
- Full unit and integration suites
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-promotion-candidate-gate-release-check
```

## Rollback

Remove the Sprint 184 gate module, tests, CLI command, and documentation
entries. No schema rollback is required.
