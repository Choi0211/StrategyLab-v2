# RFC-0003: Sprint 12 Learning Memory

Status: Accepted for implementation  
Sprint: 12  

## Problem

Gaon needs a Learning Memory system that stores evidence-backed research experience and uses it to improve future research planning.

The system must prevent unverified self-modification, unsupported claims, preference corruption, and hidden policy changes.

## Proposal

Design and then implement Learning Memory around:

- evidence-backed records
- knowledge lifecycle
- duplicate detection
- conflict detection
- confidence scoring
- protected user preferences
- audit log
- rollbackable policy revisions
- JSON versioning and migrations
- related-memory lookup for next research planning

## Domain Model Draft

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
- `KnowledgeApproval`
- `PolicyApproval`
- `AuditEvent`

## Acceptance Criteria

- records without evidence are rejected
- duplicate candidates are detected
- conflicting equivalent claims are detected
- confidence calculation is explicit and testable
- confidence is a review-priority and retrieval-ranking signal only
- confidence cannot approve knowledge, apply policy, or change user preferences
- `Validated` requires user approval
- `KnowledgeApproval` and `PolicyApproval` are separate contracts
- failure and success memories are separate
- user preferences cannot be auto-deleted or overwritten
- chronological lookup works
- project, strategy, and market filters work
- related memories can be retrieved for planning
- related-memory evaluation covers scope match, project/strategy/market match, evidence quality, validation state, recency, conflict state, and revalidation status
- JSON schema version is present
- unsupported future schema versions fail closed
- audit log records all changes
- policy revisions support rollback references

## Non-Goals

- real DB
- vector DB
- external AI API
- Telegram
- Dashboard
- MyMoneyGuard
- live trading
- automatic policy mutation

## Open Questions

- final confidence weighting
- canonical duplicate normalization strategy
- exact revalidation default interval by memory type
- whether conversation summaries require user approval before becoming knowledge
