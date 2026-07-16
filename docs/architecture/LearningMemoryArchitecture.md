# Learning Memory Architecture

Status: Blueprint  
Sprint: 12  

## Purpose

Learning Memory is Gaon's evidence-backed memory system.

It stores research experience so Gaon can remember what was tried, why it worked or failed, what the user prefers, what evidence supports a claim, and which memories should influence the next research plan.

Gaon may learn from memory, but it must not change itself without validation, approval, versioning, and rollback.

## Principles

- Evidence first
- Confidence is explicit, not implied
- Confidence is only a review-priority and retrieval-ranking signal
- Knowledge is promoted through lifecycle states
- User approval is required for `Validated`
- User preferences are protected from automatic deletion and overwrite
- All changes are audited
- Policy revisions are rollbackable
- JSON payloads are versioned and migratable
- Infrastructure is replaceable

## Domain Model Draft

### LearningRecord

Canonical memory envelope.

Fields:

- `record_id`
- `record_type`
- `scope`
- `project`
- `strategy`
- `market`
- `created_at`
- `updated_at`
- `version`
- `evidence`
- `confidence`
- `revalidation`
- `audit_ref`

Rules:

- evidence is required
- version starts at `1`
- scope must be explicit
- update creates a new version

### EvidenceRecord

Evidence attached to a learning item.

Fields:

- `evidence_id`
- `evidence_type`
- `source`
- `reference`
- `summary`
- `created_at`

Allowed evidence types:

- source
- url
- document
- research
- paper
- official documentation
- backtest
- experiment
- conversation

### KnowledgeClaim

A claim that may become knowledge.

Fields:

- `claim_id`
- `statement`
- `topic`
- `status`
- `evidence`
- `confidence`
- `conflicts`
- `approval`

Lifecycle:

```text
Collected
  -> Reviewed
  -> Need Validation
  -> Validated
  -> Deprecated
```

Rules:

- evidence is required
- `Validated` requires user approval
- conflicting claims cannot be auto-validated

### ResearchOutcome

Outcome of a research session or experiment.

Fields:

- `outcome_id`
- `research_goal_id`
- `experiment_id`
- `result_summary`
- `metrics`
- `evidence`
- `confidence`
- `conclusion`

### FailurePattern

Separated failure memory.

Fields:

- `failure_id`
- `cause`
- `symptom`
- `context`
- `avoidance_rule`
- `evidence`
- `confidence`

### SuccessPattern

Separated success memory.

Fields:

- `success_id`
- `pattern`
- `context`
- `repeatability_notes`
- `evidence`
- `confidence`

### UserPreference

Protected user preference memory.

Fields:

- `preference_id`
- `preference`
- `scope`
- `evidence`
- `confidence`
- `version`
- `approval`

Rules:

- no automatic deletion
- no automatic overwrite
- changes require a new version and audit event

### ConversationSummary

Evidence-backed conversation memory.

Fields:

- `summary_id`
- `conversation_ref`
- `summary`
- `decisions`
- `todos`
- `evidence`
- `confidence`

### ConfidenceScore

Confidence calculation output.

Fields:

- `value`
- `basis`
- `evidence_count`
- `validation_state`
- `recency`
- `conflict_penalty`

Contract:

```text
confidence = evidence_strength + validation_weight + recency_weight - conflict_penalty
```

Sprint 12 defines the contract only. Exact weighting may be implemented after tests and review.

Limits:

- Confidence cannot approve `Validated` knowledge.
- Confidence cannot apply policy revisions.
- Confidence cannot change or overwrite user preferences.
- Confidence only helps prioritize review and sort retrieval results.

### KnowledgeApproval

Approval record for validating knowledge.

Fields:

- `approval_id`
- `claim_id`
- `approved_by`
- `approved_at`
- `evidence`

Rules:

- required for `Validated`
- separate from policy approval

### PolicyApproval

Approval record for applying policy revisions.

Fields:

- `approval_id`
- `revision_id`
- `approved_by`
- `approved_at`
- `evidence`

Rules:

- required before policy revision application
- separate from knowledge approval

### LearningProposal

Proposed learning update.

Fields:

- `proposal_id`
- `proposal_type`
- `target_ref`
- `change_summary`
- `evidence`
- `confidence`
- `approval_required`

Rules:

- proposals do not mutate policy automatically
- approval is required for policy-impacting changes

### PolicyRevision

Rollbackable policy change.

Fields:

- `revision_id`
- `policy_ref`
- `proposed_change`
- `previous_version`
- `next_version`
- `evidence`
- `approval`
- `rollback_ref`

Rules:

- must include rollback reference
- must not apply without user approval

### RevalidationSchedule

Planned revalidation metadata.

Fields:

- `schedule_id`
- `target_ref`
- `reason`
- `due_at`
- `frequency`
- `status`

## Duplicate Detection

Duplicate candidates are detected by:

- same normalized statement
- same normalized record content
- same scope
- same project/strategy/market tuple
- overlapping evidence reference

Sprint 12-B implements candidate detection only. Duplicates are not automatically merged and do not mutate existing records.

## Conflict Detection

Claims conflict when they share scope and topic or explicit target references but assert incompatible statements or states.

Conflict result:

- both claims remain below `Validated`
- conflict candidates are returned for review
- no automatic resolution or approval occurs

## Query Requirements

Learning Memory must support:

- chronological research lookup
- project filter
- strategy filter
- market filter
- evidence source filter
- status filter
- related memory lookup for next research planning

Sprint 12-B repository behavior:

- `LearningRepository` defines add, get, list, chronological, filter, duplicate, conflict, and audit methods.
- `InMemoryLearningRepository` stores deterministic JSON round-tripped objects for test isolation.
- `filter(project, strategy, market)` uses AND semantics.
- `list_chronological()` sorts explicitly by `created_at` then `record_id`.
- stored records and audit events are returned as defensive copies.
- duplicate IDs are rejected.
- records without evidence are rejected before storage.
- repository JSON export/import uses versioned deterministic payloads.
- legacy repository v0 payloads migrate through explicit migration functions.

## Related Memory Retrieval Evaluation

Related memory retrieval is ranked by:

- scope match
- project/strategy/market match
- evidence quality
- validation state
- recency
- conflict state
- revalidation status

Confidence may contribute to ranking, but it must not grant approval or mutate memory.

Sprint 12 runtime implements deterministic related-memory retrieval. Each result includes:

- `record`
- `total_score`
- `score_breakdown`
- `warnings`
- `conflict_state`
- `revalidation_state`

Score components:

- scope match
- project match
- strategy match
- market match
- topic/content match
- validation state
- evidence quality
- recency
- conflict penalty
- revalidation overdue penalty
- confidence signal

## Audit Log

Every change records:

- event_id
- actor
- action
- target_ref
- before_version
- after_version
- evidence
- timestamp
- rollback_ref

Sprint 12-B audit behavior:

- `append_audit(event)` is append-only.
- duplicate `event_id` values are rejected.
- `replace_audit` and `delete_audit` are forbidden.
- `list_audit(target_ref)` returns deterministic target-scoped events.
- `list_audit(target_ref, action)` uses AND semantics.

## JSON Versioning

Every serialized payload must include:

- `schema_version`
- `kind`
- `data`

Migration rules:

- migrations are explicit functions
- unsupported future versions fail closed
- migration emits an audit event
- migrated objects keep previous version reference

Sprint 12-B adds golden JSON fixtures for the current LearningRecord schema and a migration compatibility fixture for v1 payloads.

Sprint 12 runtime fixture files live under `tests/fixtures/learning_memory/` and include valid v1, legacy v0, unsupported v2, duplicate ID, invalid timestamp, missing evidence, malformed, and retrieval-ranking fixtures.

## Research Brain Integration

Sprint 12 runtime adds explicit conversion helpers:

- ResearchGoal -> LearningRecord
- ResearchPlan -> LearningRecord
- completed ResearchSession -> ResearchOutcome
- ResearchJournalEntry -> LearningRecord

The workflow returns proposed records, duplicate candidates, and conflict candidates. It does not automatically save, validate, merge, deprecate, or apply policy.

## Time Contract

Sprint 12-B requires all Learning Memory timestamps to be ISO 8601 UTC values. Date-only strings and non-UTC offsets are rejected.

## Boundary

Sprint 12 does not implement:

- real DB
- vector DB
- external AI API
- Telegram
- Dashboard
- MyMoneyGuard access
- trading
- automatic policy mutation
