# Hotfix 163.3 - Autonomous Research Progression Integrity

Status: COMPLETE

## Context

Telegram production testing showed that repeated `계속 연구해줘` requests could
start a fresh autonomous cycle instead of continuing from the previous
autonomous research state. A separate progress-comparison prompt could also
describe unsupported assumption or metric changes.

## Problem

The conversation brain invoked `autonomous_research_cycle` with only request
text, symbol, and mode. It did not pass the prior autonomous state into the safe
tool call. Candidate identities also included cycle-specific IDs, so the same
candidate could appear new when a fresh run ID was generated.

## Fix

Hotfix 163.3 adds an explicit `continuation_state` contract for autonomous
research safe-tool calls. The state includes parent/root cycle IDs,
continuation count, tested candidate keys, immutable strategy/assumption
fingerprints, and terminal state. Candidate dedupe keys are normalized by
candidate kind, hypothesis, changed rules, and status rather than run-specific
cycle IDs.

Progress comparison requests now render from the stored structured autonomous
context. They do not rerun tools and do not invent cost-assumption or
performance deltas when authoritative paired metrics are unavailable.

## Invariants

- Continuation is not treated as a fresh baseline restart.
- Previously TESTED candidates are not recreated or retested under the same
  assumptions.
- Repeated continuation with no justified path stops deterministically with
  `NO_NEW_RESEARCH_PATH`.
- Assumptions are reported as unchanged unless explicitly user-provided changes
  exist in structured context.
- Presentation follow-ups after progression comparison preserve the autonomous
  context without rerunning tools.
- Telegram chat isolation remains enforced.
- No live trading, KIS/Broker order, Champion auto-promotion, approval bypass,
  strategy mutation, or fabricated metrics are introduced.

## Release Check

```bash
python -m gaon.runtime.cli gaon-autonomous-research-progression-release-check --db :memory:
```

Expected result:

```text
gaon-autonomous-research-progression-release-check: PASS ... continuation_state=pass parent_linkage=pass candidate_dedupe=pass progress_comparison=pass assumptions_immutable=true grounded=true safety=pass
```
