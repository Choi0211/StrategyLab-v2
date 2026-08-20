# Autonomous Research Completion

Status: Implemented locally on `feature/autonomous-research-completion`

## Context

Patch 8.7 and Patch 8.8 fixed canonical ResearchMission and
StrategyCandidate read-model continuity. Production acceptance then showed
the remaining gap: a continuation turn could run a bounded research cycle
without reducing blockers or adding independent evidence. In particular,
robustness validation could revisit an already-used symbol and report the
same cumulative state again.

## Design

This patch keeps the existing engine boundaries:

- `ResearchMission` remains the durable mission state.
- `StrategyCandidateRecord` remains the candidate identity and evidence
  ledger.
- `LLMConversationBrain` still executes one bounded tool action per
  Telegram request.
- Existing multi-symbol research and Autonomous Learning V2 pipelines are
  reused.

No second autonomous research engine is introduced.

## Blocker-Driven Progression

`gaon.knowledge.strategy_candidate` now exposes deterministic read-model
helpers:

- `candidate_progress_signature()`
- `candidate_remaining_blockers()`
- `next_blocker_driven_research_action()`

Progress is evidence-bound. A Research Director action label changing is
not sufficient by itself. Progress requires new independent evidence, a
changed validation stage, more sample coverage, or a terminal candidate
decision.

## Evidence Diversification

Mission breadth cycles now pass already-used candidate symbols as bounded
avoidance input:

- excluded symbols
- breadth evidence symbols
- robustness evidence symbols

When all known breadth evidence has already been used for robustness,
Gaon clears the focus symbol instead of falling back to
`evidence_symbols[0]`. The next continuation therefore expands the sample
instead of re-counting duplicate evidence.

## Stagnation And Rotation

Duplicate robustness evidence is still audited as an attempt, but it no
longer resets candidate progress. Existing stagnation and rotation rules
therefore work from meaningful progress rather than action-label churn.

## Promotion Readiness

The existing distinct-fingerprint promotion gate is preserved. Three
distinct promotion-ready strategy fingerprints move the mission to
`AWAITING_HUMAN_APPROVAL`; no Champion promotion, strategy mutation, or
order execution occurs automatically.

## Provider Honesty

The completion release check records source capability honestly. YouTube,
community, and social are reported as `not_configured` unless a real
provider is wired. Metadata-only evidence is not treated as content-backed
research evidence.

## Release Check

```bash
python -m gaon.runtime.cli gaon-production-autonomous-research-completion-release-check
```

The release check is deterministic and network-free. It verifies
blocker-driven progression, duplicate evidence blocking, candidate
rotation, distinct promotion-ready counting, restart persistence, Patch
8.7 handoff preservation, Patch 8.8 read-model preservation, and safety
invariants.

## Schema

Schema v36 is unchanged. The patch uses existing JSON mission/candidate
state and adds no migration.
