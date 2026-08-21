# Hotfix: Research Mission Promotion Target Consistency

## Context

Production Telegram showed `promotion-ready candidates: 0/1` after
sample exhaustion, candidate decision, strategy-space expansion, and
candidate rotation. The active mission was still the canonical KR
market-wide autonomous research mission, whose objective is three
distinct promotion-ready strategy fingerprints before human approval.

## Root Cause

The status renderer prints `ResearchMission.progress_label`; it does not
derive the denominator from the active candidate pool. The regression was
state-level: incidental count wording such as "후보 1개" could be parsed as
the promotion-ready target and persisted over the existing target. A
mission already written with `target_promotion_ready_candidates=1` would
then keep rendering `0/1` after restart.

## Design

- Promotion target and candidate pool size are separate.
- Canonical KR market-wide strategy research missions restore target `3`
  when a stale or missing target is loaded.
- Existing target counts cannot be reduced by later turns; explicit higher
  targets remain possible.
- Target extraction now requires target/goal context such as promotion,
  readiness, "until", or goal wording. Incidental count phrases no longer
  mutate the mission target.
- Promotion-ready progress is still counted only by distinct
  `strategy_fingerprint` entries recorded by the existing promotion gate.

## Acceptance

- Active candidate: `0/3`
- Candidate rotation: `0/3`
- First distinct promotion-ready fingerprint: `1/3`
- Restart: `1/3`
- Second distinct fingerprint: `2/3`
- Duplicate fingerprint: still `2/3`
- Third distinct fingerprint: `3/3` and `AWAITING_HUMAN_APPROVAL`

## Release Check

```bash
python -m gaon.runtime.cli gaon-production-promotion-target-consistency-release-check
```

The check proves target restoration, incidental count isolation, distinct
fingerprint counting, restart persistence, and unchanged safety.

## Safety

Schema remains v36. No live trading, broker/KIS order, Champion
auto-promotion, approval bypass, unapproved strategy mutation, or
fabricated metrics are introduced.
