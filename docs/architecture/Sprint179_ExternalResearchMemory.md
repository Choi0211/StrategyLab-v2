# Sprint 179 - External Research Memory

Status: COMPLETE

## Context

Sprint 178 produces structured autonomous knowledge-loop results. Sprint 179
stores those results as evidence-backed memory while keeping them unvalidated
and separate from production policy.

## Problem

Gaon needs durable memory of external research outcomes, but storing research
memory must not imply validated knowledge, production approval, or strategy
change.

## Goal

- Store autonomous knowledge-loop outcomes in append-only JSONL under
  `GaonStorage`.
- Preserve topic, loop, claim, question, and source references.
- Report duplicate fingerprints instead of overwriting records.
- Keep memory lifecycle as unvalidated evidence.

## Non-goals

- No Knowledge Validated transition.
- No merge or overwrite of duplicate memory.
- No production policy application.
- No strategy mutation, Champion promotion, or trading.
- No DB migration.

## Scope

`ExternalResearchMemoryStore` writes to
`memory/research_history/external_research_memory.jsonl` within `GaonStorage`.
It searches by topic and detects duplicate fingerprints.

## Contracts and Invariants

- Memory writes require evidence-backed loop candidates.
- Prevalidated, production-approved, mutated, or executed inputs are blocked.
- Duplicate fingerprints return `duplicate` without appending a second record.
- Stored records remain unvalidated, unapproved, and non-policy.

## Acceptance Criteria

- First write stores one memory record.
- Second identical write reports duplicate.
- Topic search retrieves stored evidence.
- Prevalidated input is blocked.
- Release check passes without schema migration.

## Test Matrix

- `tests/unit/test_external_research_memory.py`
- `python -m gaon.runtime.cli gaon-external-research-memory-release-check`
- Full unit and integration suites.
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-external-research-memory-release-check
```

## Rollback

Remove the Sprint 179 memory module, tests, and CLI release-check registration.
No schema or production runtime state is changed by the release check.

## Documentation

README, changelog, release notes, and test results record the memory contract.

## Completion Checklist

- [x] Append-only memory store implemented.
- [x] Duplicate detection added.
- [x] Safety blockers enforced.
- [x] Release check added.
- [x] Schema v36 preserved.
