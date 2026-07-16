# Sprint 12 Test Plan: Learning Memory

Status: Blueprint  

## Unit Tests

Required unit tests:

- `LearningRecord` rejects missing evidence
- `KnowledgeClaim` rejects missing evidence
- `KnowledgeClaim` lifecycle valid transitions
- `KnowledgeClaim` rejects `Validated` without user approval
- duplicate detection identifies equivalent records
- conflict detection identifies incompatible equivalent claims
- confidence calculation returns bounded score
- `FailurePattern` and `SuccessPattern` remain distinct
- `UserPreference` cannot be auto-deleted
- `UserPreference` cannot be overwritten without proposal and audit event
- chronological lookup returns ordered records
- project filter works
- strategy filter works
- market filter works
- related-memory lookup returns scoped memories
- JSON version is included
- unsupported future JSON version fails closed
- migration emits an audit event
- policy revision requires rollback reference
- policy revision cannot apply without user approval
- duplicate ID rejection
- immutable repository copy protection
- deterministic chronological ordering by timestamp and ID
- project/strategy/market AND filter behavior
- duplicate candidate detection without merge
- conflict candidate detection without resolution
- KnowledgeApproval scope mismatch rejection
- PolicyApproval scope and rollback mismatch rejection
- ISO 8601 UTC timestamp rejection for invalid values
- append-only audit behavior
- audit target query
- golden JSON fixture loading
- migration fixture compatibility
- related retrieval deterministic ranking
- retrieval score breakdown
- conflict/revalidation penalty
- repository JSON export/import round-trip
- v0 to v1 repository migration
- Research Brain conversion workflow
- Research Memory workflow does not auto-save
- no DB, vector, external AI API, private, or live trading imports

## Integration Tests

Required integration tests:

- Research Brain goal and plan create Learning Memory candidates
- Research outcome becomes a claim candidate, not validated knowledge
- failure pattern and success pattern are stored separately
- user preference affects related-memory search without being overwritten
- policy revision proposal records audit and rollback metadata

## Regression Tests

Regression tests:

- Sprint 11 Research Brain tests continue to pass
- Learning Memory foundation tests continue to pass
- release verification continues to pass

## Golden Fixtures

Golden fixtures:

- duplicate claim fixture
- conflicting claim fixture
- validated claim with approval fixture
- deprecated claim fixture
- user preference version fixture
- policy rollback fixture
- JSON migration fixture

## Sprint 12-B Gate

- `tests/unit/test_learning_repository.py` must pass.
- Existing Sprint 12-A contract tests must continue to pass under UTC timestamp validation.
- Release verification must remain green.

## Acceptance Gate

Sprint 12 cannot close unless:

- unit tests pass
- integration tests pass
- golden fixture tests pass
- migration tests pass
- release verification passes
- documentation is updated
- no secrets or private MyMoneyGuard files are introduced
