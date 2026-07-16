# Sprint 11 Brief: Research Brain and Learning Memory Foundation

Status: Active  
Branch: develop-v2  
Parent Contract: `docs/architecture/GaonDevelopmentContract.md`  
Parent Specification: `docs/architecture/GaonPlatformMasterSpecification.md`

## Objective

Sprint 11 starts the Research Brain and Learning Memory foundation for Gaon.

The sprint goal is to create the first testable learning contracts that allow Gaon to remember research goals, plans, experiments, results, failures, successes, user preferences, knowledge, citations, and conversation summaries with evidence.

## Scope

Included:

- Gaon Learning Engine package boundary
- Research Brain package boundary
- Research Goal contract
- Research Plan contract
- Research Session contract
- Research Interview contract
- Research Journal contract
- Learning Memory record contract
- Evidence record contract
- Knowledge lifecycle contract
- Experience pattern contract
- Policy update candidate contract
- Confidence score contract
- Unit tests for Learning Memory guardrails
- Unit tests for Research Brain guardrails
- Sprint 11 architecture, ADR, RFC, and learning documentation

Excluded:

- live trading
- broker APIs
- KIS API
- private MyMoneyGuard access
- Telegram runtime
- dashboard runtime
- automatic source code modification
- automatic prompt modification
- automatic champion operation
- automatic policy changes

## Acceptance Criteria

- Learning Memory records require evidence.
- Research Brain artifacts require evidence.
- Research Plan is tied to one Research Goal.
- Research Journal entries are immutable and reject duplicate IDs.
- Knowledge cannot become `Validated` without user approval.
- Policy update candidates require evidence and rollback metadata.
- Forbidden autonomous actions are represented explicitly.
- `Research Memory` terminology is replaced by `Learning Memory` in Sprint 11 planning.
- Unit tests and integration tests pass.
- Release verification passes.

## Development Order

```text
Blueprint
  -> ADR
  -> Implementation
  -> Unit Test
  -> Integration Test
  -> Documentation
  -> Review
  -> PR
```

## Completion Rule

Sprint 11 is not complete until tests, documentation, and release verification pass.
