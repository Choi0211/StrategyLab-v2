# Sprint 180 - Evidence-backed Strategy Hypothesis

Status: COMPLETE

## Context

Sprint 179 stores unvalidated external research memory. Sprint 180 converts
that memory into proposed, falsifiable strategy hypotheses.

## Problem

External research can suggest possible strategy changes, but Gaon must not
present those suggestions as tested performance or production-ready policy.

## Goal

- Create `EvidenceBackedStrategyHypothesis` records from memory evidence.
- Preserve memory, claim, and research-question lineage.
- Require falsification criteria.
- Block fabricated performance metrics in hypothesis text.

## Non-goals

- No backtest execution.
- No tested-candidate status.
- No Knowledge Validated state.
- No production approval.
- No strategy mutation, Champion promotion, or trading.

## Scope

`EvidenceBackedHypothesisGenerator` accepts unvalidated memory records plus
explicit changed rules, rationale, mechanism, and falsification criteria. The
result remains `proposed` until later validation.

## Contracts and Invariants

- Evidence memory is mandatory.
- Claim/source lineage is mandatory.
- Prevalidated or production-approved memory is blocked at this gate.
- Performance metric tokens are blocked because no validation has happened yet.
- Hypotheses are never marked tested, approved, or applied.

## Acceptance Criteria

- Evidence-backed memory yields a proposed hypothesis.
- No-memory input blocks.
- Fabricated metric text blocks.
- Prevalidated memory blocks.
- Release check passes without schema migration.

## Test Matrix

- `tests/unit/test_evidence_hypothesis.py`
- `python -m gaon.runtime.cli gaon-evidence-backed-hypothesis-release-check`
- Full unit and integration suites.
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-evidence-backed-hypothesis-release-check
```

## Rollback

Remove the Sprint 180 hypothesis module, tests, and CLI release-check
registration. No persistent schema changes are introduced.

## Documentation

README, changelog, release notes, and test results record the hypothesis gate.

## Completion Checklist

- [x] Evidence-backed hypothesis model implemented.
- [x] Fabricated metrics blocked.
- [x] Unvalidated lifecycle enforced.
- [x] Release check added.
- [x] Schema v36 preserved.
