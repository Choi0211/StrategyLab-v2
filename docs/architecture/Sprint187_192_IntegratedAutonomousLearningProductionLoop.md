# Sprint 187-192 - Integrated Autonomous Learning Production Loop

Status: COMPLETE

## Context

Sprint 186 added safe production content acquisition for Autonomous Learning V2. The remaining production loop needed explicit stage boundaries from acquired content to human-gated promotion review.

## Goal

Connect the production Autonomous Learning V2 path as:

1. Real KRX/Yahoo baseline research.
2. Bounded external metadata discovery.
3. Allowlisted safe content acquisition.
4. Grounded evidence records from acquired content and normalized claims.
5. Evidence-backed hypothesis records.
6. Candidate strategy experiment records.
7. Authoritative real-data candidate validation.
8. Robustness ranking.
9. Human promotion gate.

## Contracts

- Metadata-only sources cannot create grounded evidence.
- Fixture-backed evidence cannot request human promotion approval.
- Candidate strategy fingerprints must match authoritative backtest strategy fingerprints.
- Candidate backtests must come from real authoritative research output.
- Promotion review can be requested only after evidence, hypothesis, experiment, validation, and ranking stages pass.
- The loop never mutates strategy config, promotes a Champion automatically, or submits broker/KIS orders.

## Release Checks

- `gaon-production-grounded-evidence-release-check`
- `gaon-production-evidence-backed-hypothesis-release-check`
- `gaon-production-strategy-experiment-release-check`
- `gaon-production-authoritative-candidate-validation-release-check`
- `gaon-production-robustness-ranking-release-check`
- `gaon-production-human-promotion-gate-release-check`
- `gaon-production-autonomous-learning-loop-release-check`

## Schema

No migration. Runtime schema remains v36.

## Operational Verification

Run:

```powershell
$env:PYTHONPATH='src;tests/unit;tests/integration;tests/fixtures'
python -m gaon.runtime.cli gaon-production-autonomous-learning-loop-release-check
python -m gaon.runtime.cli deployment-import-path-check
```

Production deployments must continue to verify editable imports from `/opt/strategylab-v2/src/gaon`.
