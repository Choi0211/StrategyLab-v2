# Hotfix 163.4 - Autonomous Research History Integrity

Status: COMPLETE

## Context

Hotfix 163.3 added autonomous continuation state and candidate deduplication.
Production-style Telegram progression exposed a follow-up issue: after a
`NO_NEW_RESEARCH_PATH` continuation, the progress comparison could render only
the empty current cycle and lose the root autonomous research history.

## Problem

`NO_NEW_RESEARCH_PATH` means the current continuation found no new research path.
It must not erase previously generated or TESTED candidates. The comparison
answer must distinguish root history from the current cycle.

## Design

Progression state now preserves separate fields:

- `historical_candidates`
- `historical_tested_candidates`
- `current_cycle_candidates`
- `current_cycle_tested_candidates`
- `duplicate_candidates`
- `continuation_count`
- `terminal_state`

Candidate dedupe remains stricter than display history. Dedupe uses tested
candidate keys, while history uses normalized candidate identity so proposal and
retest records for the same robust-breakout or regime-filter candidate are not
double-counted.

## Invariants

- `NO_NEW_RESEARCH_PATH` only clears current-cycle proposals/retests.
- Root candidate history remains available for later presentation and comparison.
- Progress comparison does not rerun autonomous tools.
- No unsupported metric deltas, cost assumptions, slippage, tax, execution, or
  position sizing changes are fabricated.
- Safety boundaries remain read-only.

## Verification

Release check:

```powershell
python -m gaon.runtime.cli gaon-autonomous-research-history-release-check --db :memory:
```

Expected result:

- `historical_candidates=2`
- `historical_TESTED_candidates=2`
- `current_cycle_candidates=0`
- `continuation_count=2`
- `terminal_state=no_new_research_path`
- `no_tool_rerun=true`

## Schema

No schema migration. Schema remains v36.
