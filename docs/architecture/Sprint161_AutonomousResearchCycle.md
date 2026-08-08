# Sprint 161 - Autonomous Research Cycle

Status: COMPLETE

## Goal

Compose adaptive validation, planning, candidate generation, critic/retest, and
Learning Memory integration into one bounded autonomous research cycle.

## Scope

- `AutonomousResearchCycleRequest`
- `AutonomousResearchCycleReport`
- `CycleTerminalState`
- deterministic `AutonomousResearchCycleRunner`
- `gaon-autonomous-research-cycle-release-check`

## Contracts

The cycle is bounded by explicit `max_steps`. Invalid data quality fails closed
with `DATA_FAILURE`. Insufficient evidence remains `INSUFFICIENT_EVIDENCE`.
Sufficient evidence requires user approval before any configuration change.

The runner may persist unvalidated Learning Memory evidence, but it does not
apply policy, mutate strategy configuration, place orders, or promote a
Champion.

## Safety

No live trading, KIS/Broker order, automatic approval, Champion promotion, or
strategy configuration mutation is implemented.

## Verification

```bash
python -m gaon.runtime.cli gaon-autonomous-research-cycle-release-check --db :memory:
```
