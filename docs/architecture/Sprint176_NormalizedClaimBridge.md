# Sprint 176 - Normalized Claim Bridge

Status: COMPLETE

## Context

Sprint 175 produces bounded normalized text from previously acquired source
content. Sprint 176 connects that normalized evidence to the existing Sprint 168
verbatim claim and Knowledge Candidate foundation.

## Problem

Normalized content must not automatically become validated knowledge. The
system needs a narrow bridge that extracts only source-present claims and keeps
all provenance, quality, and safety boundaries intact.

## Goal

- Convert eligible normalized text into verbatim `ExtractedClaim` records.
- Build unvalidated `KnowledgeCandidate` records only when source quality allows
  evidence use.
- Preserve acquisition ID, source locator, raw checksum, and normalized checksum.
- Block unsupported, rejected, mismatched, or empty normalized content.

## Non-goals

- No claim summarization or paraphrasing.
- No conflict resolution.
- No Knowledge Validated state.
- No production approval.
- No strategy configuration mutation.
- No Champion promotion.
- No trading.

## Scope

`NormalizedContentClaimBridge` accepts a `NormalizedContentRecord`,
`SourceProvenance`, and optional `SourceQualityAssessment`. It validates source
locator and checksum linkage, applies the existing evidence gate, then reuses
`VerbatimClaimExtractor` and `KnowledgeCandidateBuilder`.

## Contracts and Invariants

- `status=normalized` and `eligible_for_claim_extraction=true` are required.
- Source locator and raw checksum must match the provenance record.
- Rejected evidence remains blocked.
- Claims must be verbatim substrings of normalized text.
- Generated candidates are unvalidated, untested, and not production-approved.
- External content remains evidence, never instruction.

## Acceptance Criteria

- Eligible normalized text yields verbatim claims and unvalidated candidates.
- Unsupported normalized content yields zero claims and zero candidates.
- Source/checksum mismatch is blocked.
- Rejected quality is blocked.
- Release check passes without DB migration.

## Test Matrix

- `tests/unit/test_content_claim_bridge.py`
- `python -m gaon.runtime.cli gaon-normalized-claim-bridge-release-check`
- Full unit and integration suites.
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-normalized-claim-bridge-release-check
```

## Rollback

Remove the Sprint 176 module, CLI release-check registration, and tests. No
schema migration or persistent data changes are introduced.

## Documentation

README, changelog, release notes, and test results record the new bridge and
release check.

## Completion Checklist

- [x] Bridge implemented with existing claim/candidate builders.
- [x] Source and checksum linkage enforced.
- [x] Rejected/unsupported evidence blocked.
- [x] Release check added.
- [x] Unit tests added.
- [x] Schema v36 preserved.
