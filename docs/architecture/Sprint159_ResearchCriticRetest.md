# Sprint 159 - Critic / Improvement / Retest

Status: COMPLETE

## Goal

Add a structured critic loop that evaluates research weaknesses, creates
improvement proposals, retests candidates, and preserves rejected evidence.

## Scope

- `ResearchCriticFinding`
- `ImprovementProposal`
- `CandidateRetestResult`
- `CriticRetestReport`
- deterministic `ResearchCriticEngine`
- deterministic `CriticImprovementRetestLoop`
- `gaon-research-critic-release-check`

## Contracts

The critic evaluates sample size, drawdown, and data-quality blockers. Findings
do not directly mutate a strategy. Improvement proposals become candidates and
must be retested before they can be considered tested evidence.

Rejected candidates are retained in the report instead of being discarded.

## Safety

No live trading, KIS/Broker order, Champion promotion, approval bypass, or
production strategy mutation is implemented.

## Verification

```bash
python -m gaon.runtime.cli gaon-research-critic-release-check --db :memory:
```
