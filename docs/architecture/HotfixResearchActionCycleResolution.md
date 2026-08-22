# Hotfix: Research Action Cycle Resolution

Status: Implemented

## Context

Production autonomous research progression reached a KR-ST-006-like state
where several validation dimensions were unresolved:

- OOS: `insufficient_oos_sample`
- walk-forward: `fail`
- transaction cost/slippage: `cost_fragile`
- regime: `insufficient_regime_coverage`
- cross-symbol: `multi_symbol_partial`
- parameter sensitivity: `stable`
- Monte Carlo: `not_run_insufficient_primary_sample`

The action sequence then alternated:

```text
RUN_OOS(false) -> RUN_REGIME(false) -> RUN_OOS(false)
```

The prior replay guard blocked only immediate same-action replay. A
different unresolved blocker in between reset that guard.

## Root Cause

`StrategyCandidateRecord` persisted only the most recent
`last_validation_reference`. `next_blocker_driven_research_action()` could
therefore see that `RUN_OOS` was not the immediate previous reference and
select it again, even though the candidate's material evidence state had
not changed since the last no-progress `RUN_OOS`.

## Design

Each strategy candidate now persists a bounded `validation_attempt_history`
for robustness actions. Every attempt records:

- action
- validation stage
- symbol/sample
- material evidence state key
- whether the attempt produced measurable progress
- evidence reference

The material evidence key includes candidate fingerprint, breadth sample,
robustness symbols, validation stage statuses, sample-exhaustion state, and
terminal evidence. It deliberately excludes timestamps, presentation text,
last action labels, and counters.

When choosing the next blocker-driven action, Gaon now skips any action
that already ended without progress under the current material evidence
state. Once new material evidence appears, such as a new symbol/sample or a
changed validation result, the key changes and the action may be selected
again when still warranted.

## Progression

- A no-progress `RUN_OOS` followed by a no-progress `RUN_REGIME` no longer
  returns to `RUN_OOS` under the same evidence state.
- A no-progress `RUN_OOS -> RUN_REGIME -> RUN_WALK_FORWARD` cycle likewise
  cannot jump back to the first action without new evidence.
- If all currently actionable blockers are exhausted with no progress, the
  planner moves to new evidence acquisition or candidate rotation depending
  on canonical candidate state and stagnation count.
- Restart preserves the cycle boundary through candidate JSON.

## Safety

This is bookkeeping over existing validation evidence. It does not execute
orders, mutate strategies, promote Champions, bypass approvals, or create
fabricated metrics.

## Release Check

```bash
python -m gaon.runtime.cli gaon-production-research-action-cycle-resolution-release-check
```

The check proves A-B-A and A-B-C-A cycle blocking, material-evidence reset,
restart persistence, production KR-ST-006-shaped no ping-pong behavior, and
unchanged safety.
