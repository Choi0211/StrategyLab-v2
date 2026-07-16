# ADR-0005: Knowledge Lifecycle and Approval Gate

Status: Proposed  
Date: 2026-07-16  
Sprint: 12  

## Context

Gaon may collect evidence and learn from research, but it must not validate knowledge or revise policy without approval.

Knowledge must be distinguishable from raw collected notes.

## Decision

Use the lifecycle:

```text
Collected
  -> Reviewed
  -> Need Validation
  -> Validated
  -> Deprecated
```

`Validated` requires explicit user approval.

## Rules

- Collected: raw evidence-backed claim
- Reviewed: inspected for completeness
- Need Validation: requires experiment, backtest, citation review, or user review
- Validated: approved by user after validation
- Deprecated: superseded, contradicted, or expired

Forbidden:

- auto-promoting to `Validated`
- validating conflicting claims
- deleting user preferences automatically
- applying policy revisions without approval

## Revalidation

Validated knowledge must carry a `RevalidationSchedule`.

Revalidation may be triggered by:

- stale evidence
- conflicting new evidence
- failed experiment
- changed user preference
- changed market regime

## Consequences

Learning Memory can grow autonomously while preserving evidence, approval, and rollback discipline.
