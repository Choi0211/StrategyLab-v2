# Sprint 183 - Strategy Robustness Ranking

Status: COMPLETE

## Context

Sprint 182 accepts authoritative validation evidence for immutable
experiments. Sprint 183 ranks those accepted validation results so downstream
policy can inspect candidate strength without receiving implicit approval.

## Problem

Candidate comparison must be based on structured metrics, not generated
narrative. It also must not confuse a ranked candidate with a production
promotion.

## Goal

Add an evidence-only robustness ranker that requires trade count, return,
drawdown, profit factor, and win rate metrics before producing a reviewable
ranking.

## Non-goals

- No Champion promotion.
- No approval request creation.
- No strategy configuration mutation.
- No schema migration.
- No invented metric completion.

## Scope

- `StrategyRobustnessRanker`
- `RobustnessRankingResult`
- `RobustnessRankedStrategy`
- `gaon-robustness-ranking-release-check`

## Contracts and Invariants

- Only `ACCEPTED_FOR_REVIEW` validation loop results are rankable.
- Required metrics must be present in structured evidence.
- Fixture-backed rankings remain marked and are not production approval.
- Ranking never mutates strategies, promotes Champion, or trades.

## Acceptance Criteria

- Stronger structured evidence ranks first.
- Missing metrics block ranking.
- Non-accepted validation blocks ranking.
- Release check verifies ranking and safety flags.

## Test Matrix

- `tests.unit.test_robustness_ranking`
- `gaon-robustness-ranking-release-check`
- Full unit and integration suites
- `scripts/verify_release.py`
- `deployment-import-path-check`
- `git diff --check`

## Operational Verification

```bash
python -m gaon.runtime.cli gaon-robustness-ranking-release-check
```

## Rollback

Remove the Sprint 183 ranking module, tests, CLI command, and documentation
entries. No schema rollback is required.
