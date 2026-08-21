# Hotfix: Research Mission Strategy-Space Expansion

Status: Implemented

## Context

Production Research Missions can legitimately exhaust the original bounded
strategy-family inventory while still having `promotion-ready candidates:
0/3`. Previously that state was rendered as
`strategy_family_space_exhausted`, which stopped the mission even when the
candidate history contained real blocker evidence that could guide the next
safe hypothesis.

## Design

The fix keeps the existing `ResearchMission` and `StrategyCandidateRecord`
architecture. When all base strategy families have been tried and no active
candidate remains, the conversation path emits an explicit
`EXPAND_STRATEGY_SPACE` action instead of treating family exhaustion as a
terminal failure.

Expansion candidates are selected from a bounded declarative grammar that
uses only primitives already supported by the real backtest path:

- breakout lookback
- MA20/MA60 trend confirmation
- volume MA20 confirmation
- channel-low exit lookback
- percentage protective stop

No LLM-generated code, unsupported indicator, broker order, or strategy
mutation is introduced.

## Evidence To Hypothesis

The expansion ranker reads persisted candidate evidence only:

- insufficient trade sample
- cross-symbol weakness
- non-pass validation stage status
- cost fragility
- OOS/walk-forward/regime blockers
- candidate stagnation or rejection reason

These signals influence which bounded template is tried first. They do not
create fabricated market metrics or mark a candidate promotion-ready.

## Identity

Every expanded candidate is converted to the normal candidate spec and
checked by the existing strategy-family fingerprint. A semantic duplicate is
blocked when either its family or fingerprint already exists in the mission.

## Lifecycle

New expansion candidates enter the same production pipeline:

`hypothesis -> StrategyCandidateRecord -> candidate_spec -> multi_symbol_research -> robustness blockers -> ranking/promotion gate`

Candidate creation itself is not validation progress. Only real
multi-symbol/backtest evidence can update trade counts, evidence symbols, or
promotion status.

## Safety

The schema remains v36. The hotfix does not add live trading, KIS/Broker
orders, Champion auto-promotion, approval bypass, or unapproved strategy
configuration changes.

## Release Check

`gaon-production-strategy-space-expansion-release-check` proves:

- base families are exhausted
- `EXPAND_STRATEGY_SPACE` is selected
- blocker evidence is used
- a distinct candidate fingerprint is generated
- the candidate is persisted
- the existing multi-symbol pipeline can reconstruct the same candidate spec
- previous candidate history survives restart
- no validation or promotion progress is fabricated
