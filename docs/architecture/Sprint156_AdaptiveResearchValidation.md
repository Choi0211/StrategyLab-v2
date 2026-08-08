# Sprint 156 - Adaptive Research Validation

Status: COMPLETE

## Goal

Detect whether a structured research result has enough evidence for a research
decision and, when it does not, produce a bounded validation plan instead of
pretending the evidence is sufficient.

## Scope

- `ResearchAdequacyAssessment`
- `EvidenceAdequacy`
- `ValidationNeed`
- `ValidationPlan`
- `ValidationStopReason`
- deterministic `AdaptiveResearchValidator`
- `gaon-adaptive-validation-release-check`

## Contracts

Adequacy states are `SUFFICIENT`, `INSUFFICIENT`, `DEGRADED`, and `INVALID`.
The validator considers trade count, observation period, market-regime coverage,
MDD, win/loss sample, data quality, missing/zero-volume bars, and symbol
coverage.

The validator is advisory. It may recommend period expansion, regime testing,
multi-symbol validation, parameter robustness checks, or out-of-sample tests,
but it cannot mutate strategy configuration, promote a Champion, approve
knowledge, or place orders.

## Safety

Blocking data quality is fail-closed as `INVALID`. Insufficient sample creates
validation needs only. No live trading, KIS/Broker order, Champion promotion,
approval bypass, or production strategy mutation is implemented.

## Verification

```bash
python -m gaon.runtime.cli gaon-adaptive-validation-release-check --db :memory:
```
