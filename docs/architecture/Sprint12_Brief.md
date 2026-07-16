# Sprint 12 Brief: Learning Memory Blueprint

Status: Sprint 12-B Implementation  
Branch: feature/sprint12-memory-repository  
Base: latest main  
Parent Contract: `docs/architecture/GaonDevelopmentContract.md`  

## Objective

Sprint 12 designs the Learning Memory system that allows Gaon to remember past research, failures, successes, user preferences, evidence, and conversations, then use those memories to prepare better future research plans.

Sprint 12-A implemented domain contracts. Sprint 12-B adds deterministic in-memory repository and detection contracts only. It does not implement real storage, vector search, AI providers, Telegram, Dashboard, MyMoneyGuard access, or trading behavior.

## Scope

Design and Sprint 12-B implementation:

- Learning Memory domain model draft
- evidence-backed storage contract
- duplicate and conflict detection rules
- confidence calculation contract
- Knowledge lifecycle
- audit log and rollback policy
- versioned JSON and migration policy
- query/filter requirements
- test strategy
- in-memory repository for contract tests
- append-only audit workflow
- ISO 8601 UTC timestamp validation
- golden JSON fixture and migration compatibility fixture

## Required Domain Model Draft

- `LearningRecord`
- `EvidenceRecord`
- `KnowledgeClaim`
- `ResearchOutcome`
- `FailurePattern`
- `SuccessPattern`
- `UserPreference`
- `ConversationSummary`
- `ConfidenceScore`
- `LearningProposal`
- `PolicyRevision`
- `RevalidationSchedule`

## Required Behaviors

- reject learning records without evidence
- detect duplicate records
- detect conflicts between equivalent claims
- calculate confidence through an explicit contract
- require user approval before `Validated`
- separate failure reasons from success patterns
- prevent automatic deletion or overwrite of user preferences
- support chronological research lookup
- support project, strategy, and market filters
- search related memories for the next research plan
- support JSON versioning and migrations
- audit every change
- support rollbackable policy revisions

## Non-Goals

- real database implementation
- vector database connection
- external AI API connection
- Telegram implementation
- Dashboard implementation
- MyMoneyGuard access
- live trading
- automatic policy changes

## Implementation Order

1. Confirm this Blueprint.
2. Accept ADR-0004 and ADR-0005.
3. Add domain models only.
4. Add in-memory deterministic repository contracts for tests.
5. Add duplicate and conflict detection.
6. Add confidence calculation contract.
7. Add lifecycle transition rules.
8. Add audit log and rollback contracts.
9. Add JSON versioning and migration tests.
10. Update documentation and release notes.

## Sprint 12-B Implemented API

- `LearningRepository`
- `InMemoryLearningRepository`
- `DuplicateDetector`
- `ConflictDetector`
- `DuplicateCandidate`
- `ConflictCandidate`
- `validate_iso8601_utc`
- `GOLDEN_LEARNING_RECORD_JSON`
- `MIGRATION_V1_LEARNING_RECORD_JSON`

## Remaining Sprint 12-C Scope

- related-memory retrieval ranking
- evidence quality scoring policy
- revalidation due-query workflow
- repository-backed LearningProposal generation
- integration with Research Brain outcome candidates
- documentation updates for retrieval behavior

## Acceptance Criteria

- All required domain model contracts are represented.
- Evidence is mandatory for learning records, claims, outcomes, patterns, preferences, summaries, proposals, and policy revisions.
- Knowledge lifecycle follows `Collected -> Reviewed -> Need Validation -> Validated -> Deprecated`.
- `Validated` requires explicit user approval.
- User preferences cannot be deleted or overwritten automatically.
- Audit log records create, update, lifecycle transition, approval, deprecation, and rollback events.
- JSON payloads include schema version and migration policy.
- Test plan covers unit, integration, regression, golden fixture, and migration tests.

## Risks

| Risk | Mitigation |
| --- | --- |
| Memory becomes untrusted notes | Require evidence, confidence, scope, version, audit log, and revalidation. |
| Gaon changes itself without review | Policy revisions remain proposals until user approval. |
| User preference corruption | Disallow automatic delete and overwrite. |
| Duplicate noisy memories | Add duplicate detection before storage. |
| Contradictory knowledge | Add conflict detection and `Need Validation` state. |
| Premature infrastructure coupling | Keep DB/vector/AI integrations out of Sprint 12. |
