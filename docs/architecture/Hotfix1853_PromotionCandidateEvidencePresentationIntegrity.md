# Hotfix 185.3 Promotion Candidate Evidence Presentation Integrity

Status: COMPLETE

## Context

Hotfix 185.1 and 185.2 route explicit Telegram autonomous-learning requests into
the Autonomous Learning V2 orchestration. Production acceptance then exposed a
presentation gap: after V2 produced a promotion candidate, a follow-up asking
for the candidate details could be routed back into the V2 tool or rendered as a
generic status summary instead of reusing the preserved promotion-candidate
evidence.

## Problem

Promotion-candidate detail questions are presentation-only requests. They must
not rerun autonomous learning, external research, backtests, ranking, or approval
logic. They also must not fall back to default backtest fields such as unknown
periods, `trade_count=0`, or fabricated missing metrics.

## Design

- Autonomous Learning V2 release output now carries a structured
  `promotion_candidate_context` with candidate identity, fingerprint, changed
  rules, hypothesis, source lineage, validation evidence, ranking components,
  risks, and human-gate state.
- Telegram follow-up routing detects promotion-candidate presentation requests
  while an active same-chat V2 context exists and renders from the stored context
  without invoking tools.
- The grounded renderer has a dedicated promotion-candidate evidence view. It
  prints only authoritative structured fields and renders missing metrics as
  unavailable rather than as zero.
- Source lineage preserves metadata-only evidence explicitly so metadata is not
  mistaken for validated source content.
- Cross-chat presentation requests remain isolated and receive deterministic
  missing-context guidance.

## Contracts

- No live trading.
- No KIS or broker orders.
- No Champion auto-promotion.
- No approval bypass.
- No strategy configuration mutation.
- No fabricated metrics, default zero metrics, or unknown-period fallback.
- Schema remains v36.

## Release Check

```bash
python -m gaon.runtime.cli gaon-promotion-candidate-presentation-release-check --db :memory:
```

The check verifies candidate identity, fingerprint, hypothesis, changed rules,
source lineage, authoritative validation metrics, ranking context, chat
isolation, no tool rerun, and unchanged approval/safety state.
