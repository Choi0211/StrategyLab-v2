# Sprint 177 - Evidence Conflict Re-evaluation

Status: COMPLETE

## Context

Sprint 176 creates unvalidated Knowledge Candidates from normalized evidence.
Sprint 177 reuses the existing structured conflict and gap modules to
re-evaluate a topic when new claim candidates arrive.

## Problem

Gaon needs to notice when new evidence changes the research state, but it must
not infer stance from prose or automatically resolve conflicts.

## Goal

- Re-evaluate explicit positioned claim evidence for a topic.
- Detect status changes such as insufficient independence becoming unresolved
  conflict.
- Generate bounded research questions from conflict/gap state.
- Keep all outputs unvalidated and advisory.

## Non-goals

- No free-text stance inference.
- No automatic conflict resolution.
- No Knowledge Validated state.
- No production approval.
- No policy application or strategy mutation.
- No trading.

## Scope

`EvidenceConflictReevaluator` accepts Knowledge Candidates plus explicit
candidate-id to `ClaimStance` mappings. It produces positioned claims, a
`KnowledgeConflictRecord`, and research questions through existing Sprint 169
and Sprint 170 components.

## Contracts and Invariants

- Every candidate must have an explicit stance.
- Validated or production-approved inputs are blocked at this gate.
- Existing conflict detector de-duplicates by claim ID.
- Conflicts are never resolved by score.
- Research questions are prompts for later research, not answers.

## Acceptance Criteria

- Single-source directional evidence remains insufficient independence.
- New independent opposing evidence becomes unresolved conflict.
- Missing stance blocks reevaluation.
- Validated/approved input blocks reevaluation.
- Release check passes without schema migration.

## Test Matrix

- `tests/unit/test_evidence_reevaluation.py`
- `python -m gaon.runtime.cli gaon-evidence-conflict-reevaluation-release-check`
- Full unit and integration suites.
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-evidence-conflict-reevaluation-release-check
```

## Rollback

Remove the Sprint 177 module, tests, and CLI release-check registration. No DB
schema or persistent state is changed.

## Documentation

README, changelog, release notes, and test results record the new reevaluation
gate.

## Completion Checklist

- [x] Re-evaluator implemented with existing conflict/gap modules.
- [x] Explicit stance requirement enforced.
- [x] No automatic resolution.
- [x] Release check added.
- [x] Unit tests added.
- [x] Schema v36 preserved.
