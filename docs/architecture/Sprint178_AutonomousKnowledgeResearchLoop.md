# Sprint 178 - Autonomous Knowledge Research Loop

Status: COMPLETE

## Context

Sprints 175 through 177 created safe normalization, claim bridging, and
conflict/gap reevaluation. Sprint 178 composes those pieces into a bounded
knowledge research loop over explicit inert evidence inputs.

## Problem

Gaon needs a repeatable loop that can process multiple evidence sources and
produce next research questions without opening new network paths or validating
knowledge prematurely.

## Goal

- Process explicit source evidence inputs through normalization and claim
  extraction.
- Re-evaluate conflict/gap state after new claim candidates are available.
- Respect source count, byte, and iteration budgets.
- Return structured blockers instead of continuing on unsafe evidence.

## Non-goals

- No autonomous network acquisition.
- No claim summarization or stance inference.
- No Knowledge Validated state.
- No strategy change or Champion promotion.
- No trading.

## Scope

`AutonomousKnowledgeResearchLoop` accepts `SourceEvidenceInput` records with
source provenance, raw inert content, MIME type, and explicit stance. It then
uses the Sprint 175 normalizer, Sprint 176 bridge, and Sprint 177 reevaluator.

## Contracts and Invariants

- Network is not used by the loop.
- Byte/source/iteration limits are enforced.
- Unsupported content blocks claim extraction.
- Conflict status is structured and unresolved conflicts emit questions only.
- Outputs remain unvalidated, unapproved, and non-executable.

## Acceptance Criteria

- Two independent opposing evidence inputs yield unresolved conflict and one
  research question.
- Empty evidence blocks.
- Byte budget overflow blocks.
- Unsupported PDF content blocks.
- Release check passes without schema migration.

## Test Matrix

- `tests/unit/test_autonomous_knowledge_loop.py`
- `python -m gaon.runtime.cli gaon-autonomous-knowledge-research-loop-release-check`
- Full unit and integration suites.
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-autonomous-knowledge-research-loop-release-check
```

## Rollback

Remove the Sprint 178 loop module, tests, and CLI release-check registration.
No persistent state or schema migration is introduced.

## Documentation

README, changelog, release notes, and test results record the loop contract.

## Completion Checklist

- [x] Bounded loop implemented.
- [x] Existing normalization/claim/conflict components reused.
- [x] Budget blockers tested.
- [x] Release check added.
- [x] Schema v36 preserved.
