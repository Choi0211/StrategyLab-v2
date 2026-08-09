# Sprint 175-185 Follow-up: Autonomous Learning Execution Integrity

Status: IMPLEMENTED

## Context

Sprint 175-185 introduced the safe external evidence, hypothesis,
experiment, validation, ranking, and human-gated promotion contracts. The
follow-up closes two integration gaps discovered during review:

- Sprint 178 now has a bounded path that executes the existing discovery,
  metadata ingestion, content acquisition, normalization, claim bridge, and
  evidence reevaluation components instead of requiring pre-supplied evidence.
- Sprint 181-182 now has a trusted adapter from actual structured
  `RealBacktestResult` / `RealAutonomousResearchReport` objects into
  validation evidence, so arbitrary metric dictionaries cannot enter the
  autonomous validation path as authoritative evidence.

## Execution Path

The deterministic release path is:

1. `ResearchQuestion`
2. `SourceDiscoveryPlanner`
3. `BoundedSourceDiscoveryExecutor`
4. `DiscoveryEvidenceIngestor`
5. `BoundedSourceContentAcquirer`
6. `SafeContentNormalizer`
7. `NormalizedContentClaimBridge`
8. `EvidenceConflictReevaluator`
9. `ExternalResearchMemoryRecord`
10. `EvidenceBackedHypothesisGenerator`
11. `StrategyExperimentBuilder`
12. `TrustedValidationEvidenceAdapter`
13. `AutonomousValidationLoopV2`
14. `StrategyRobustnessRanker`
15. `PromotionCandidateGate`
16. `HumanGatedPromotionService`

The final state remains `awaiting_human_approval` when no candidate-specific
approval token is supplied.

## Contracts

- Downloaded content is treated as inert evidence and never executed.
- Network use remains policy-gated and fixture-backed in release checks.
- Source metadata alone cannot become a claim.
- Actual validation evidence must originate from structured real
  research/backtest result types.
- Fixture-backed release evidence is allowed only in isolated deterministic
  checks.
- Human approval remains mandatory before production strategy changes.

## Release Checks

New commands:

```bash
python -m gaon.runtime.cli gaon-autonomous-external-research-execution-release-check
python -m gaon.runtime.cli gaon-authoritative-experiment-execution-release-check
python -m gaon.runtime.cli gaon-autonomous-learning-e2e-release-check
```

## Safety

Schema remains v36. No live trading, KIS/Broker order, automatic Champion
promotion, approval bypass, strategy mutation, source instruction execution,
fabricated evidence, fabricated claims, or fabricated metrics is introduced.
