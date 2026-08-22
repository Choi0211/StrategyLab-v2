# Hotfix: Terminal Validation Retry Boundary

Status: Implemented

## Context

Production autonomous research progression for a KR-ST-007-like candidate
showed this sequence:

```text
RUN_OOS -> OOS=fail_underperformed_baseline
RUN_REGIME -> no progress
next_action=RUN_OOS
```

The previous cross-action cycle fix tracked no-progress attempts, but an
OOS run that changed the stage status from partial to a decisive failure
was stored as `progressed=true`. Since the attempt history only recorded
the pre-attempt evidence state, the current post-attempt state looked as if
RUN_OOS had never been consumed.

## Design

Validation attempt history now records both:

- `state_key`: the material evidence state before the validation attempt
- `result_state_key`: the material evidence state after the validation
  attempt is merged into the candidate

The blocker selector treats an action as already consumed when the current
material evidence state matches either key. This blocks immediate reruns of
a decisive validation result such as `fail_underperformed_baseline`, and it
also preserves the previous no-progress behavior.

## Retry Semantics

The boundary is not a permanent blacklist. If material evidence changes,
such as a new distinct symbol, more cumulative trades, candidate fingerprint
change, or validation-stage evidence update, the material state key changes
and the validation action can become eligible again.

## Candidate Comparison

The multi-symbol candidate comparison renderer now exposes the structured
reason behind `original_preferred`, `candidate_preferred`, or
`no_clear_winner`. A candidate with better median return but a smaller
aggregate trade sample is reported as mixed evidence instead of being
silently described as less stable or hidden behind presentation text.

## Safety

This hotfix changes planner bookkeeping and evidence-bound presentation
only. It does not add live trading, broker/KIS orders, Champion
auto-promotion, approval bypass, strategy mutation, or fabricated metrics.

## Release Check

```bash
python -m gaon.runtime.cli gaon-production-terminal-validation-retry-boundary-release-check
```

The check proves terminal OOS replay blocking, restart persistence, and
legitimate retry after new material evidence.
