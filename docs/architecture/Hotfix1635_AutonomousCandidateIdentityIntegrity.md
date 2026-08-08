# Hotfix 163.5 - Autonomous Research Candidate Identity Integrity

Status: COMPLETE

## Context

Hotfix 163.4 preserved root autonomous research history across
`NO_NEW_RESEARCH_PATH` continuations. Production Telegram acceptance testing then
found that the history could still show duplicate logical candidates:
`robust-breakout, robust-breakout, regime-filter, regime-filter`.

## Root Cause

Autonomous research used two different candidate representations:

- `tested_candidate_keys`: a strict duplicate-prevention key containing
  `candidate_kind`, `changed_rules`, `hypothesis`, and `status`.
- `historical_candidates`: a presentation/history identity that still included
  `changed_rules`.

When proposal/retest records and restored `tested_candidate_keys` had different
`changed_rules` values, the same logical candidate was counted twice in history.

## Design

Candidate duplicate detection remains strict and keeps the full key. Candidate
history now uses a separate canonical identity:

```text
candidate_kind=<logical-candidate-kind>
```

This keeps `robust-breakout` and `regime-filter` stable whether they arrive from
proposal records, retest records, previous history, or restored
`tested_candidate_keys`.

## Invariants

- `NO_NEW_RESEARCH_PATH` still means no new current-cycle candidate.
- Historical candidates and TESTED historical candidates remain visible.
- Continuation count and terminal state remain preserved.
- Assumptions remain immutable.
- Comparison follow-ups do not rerun autonomous research tools.
- No fabricated metric delta or unsupported cost/slippage/tax assumption is
  rendered.
- Schema remains v36. No migration is required.

## Release Check

```bash
python -m gaon.runtime.cli gaon-autonomous-candidate-identity-release-check --db :memory:
```

The check replays the production-style Telegram sequence:

1. analysis
2. autonomous validation
3. continue
4. continue again
5. compare progress with the initial research

It verifies that `historical_candidates=2`,
`historical_TESTED_candidates=2`, `current_cycle_candidates=0`,
`continuation_count=2`, and `terminal_state=no_new_research_path`.

## Safety

This hotfix is read-only. It does not add live trading, KIS or broker orders,
Champion auto-promotion, approval bypass, strategy config mutation, or
fabricated metrics.
