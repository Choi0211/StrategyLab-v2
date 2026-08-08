# Sprint 158 - Strategy Candidate Generation

Status: COMPLETE

## Goal

Generate strategy improvement candidates only when structured evidence and a
validation plan justify doing so.

## Scope

- `StrategyCandidate`
- `StrategyCandidateStatus`
- deterministic `StrategyCandidateGenerator`
- `gaon-strategy-candidate-generation-release-check`

## Contracts

Candidates keep parent strategy, hypothesis, changed rules, rationale,
supporting evidence, expected effect, possible downside, and rollback reference.
Changed candidates start as `PROPOSED`; they are not production strategy
changes.

## Safety

Random parameter search is not the default behavior. Production mutation,
Champion promotion, order placement, and approval bypass remain disabled.

## Verification

```bash
python -m gaon.runtime.cli gaon-strategy-candidate-generation-release-check --db :memory:
```
