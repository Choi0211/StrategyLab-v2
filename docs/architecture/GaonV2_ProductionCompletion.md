# Gaon v2 Production Completion

Status: COMPLETE
Branch: `feature/gaon-v2-production-completion`  
Schema: v36 unchanged

## Context

Gaon v2 already contains the Autonomous Learning V2, safe content acquisition,
multi-source research, Autonomous Quant Partner, production validation, Hotfix
248.1 real robustness execution, Sprint 249-256 real execution, and Hotfix
256.1 validation-semantics/leakage integrity layers.

This closeout does not add a new research strategy. It verifies that the
existing production components compose into one bounded, evidence-first
operating loop and that promotion remains human-gated.

## Audit Summary

- `already_complete`: real/fixture provenance, KRX/Yahoo data-quality gates,
  multi-source evidence contracts, content acquisition safety, counter-evidence
  records, candidate experiment lineage, real validation execution, tournament
  ranking, promotion candidate gate, human approval tokens, Champion registry,
  Champion version history, rollback, Telegram authoritative rendering.
- `partially_complete`: provider categories that are wired but honestly report
  unavailable/not configured in production when no endpoint is configured.
- `wired_but_not_live`: provider categories that honestly report
  `provider_not_configured` or `content_unavailable` in production.
- `missing`: none for the deterministic production-completion contract. Live
  Telegram/VPS acceptance remains an operational verification step.

## Completion Design

The final completion layer reuses existing components:

- `autonomous_quant_partner_payload()` for the bounded research loop.
- Production-grade validation sections for multi-symbol, OOS, walk-forward,
  regime, parameter, cost-stress, Monte Carlo, and tournament checks.
- `PromotionCandidateGate` and `HumanGatedPromotionService` for the first
  human approval boundary and immutable candidate freeze.
- `ChampionRegistryService` for the second explicit Champion replacement
  approval, retained version history, and rollback.

The release checks run in deterministic release-validation mode. They may use
synthetic deterministic validation data, but must expose
`check_mode=deterministic_release_validation` and may not present fixture-backed
evidence as production promotion evidence.

## New Release Checks

- `gaon-production-final-autonomous-research-release-check`
- `gaon-production-final-conversation-release-check`
- `gaon-production-two-stage-approval-release-check`
- `gaon-production-candidate-freeze-release-check`
- `gaon-production-champion-replacement-release-check`
- `gaon-production-champion-rollback-release-check`
- `gaon-production-final-safety-boundary-release-check`
- `gaon-production-gaon-v2-completion-release-check`
- `gaon-production-v2-final-closeout-release-check`

The final closeout command extends the component aggregate with durable
restart/replay checks for Stage 1 candidate freeze, Stage 2 Champion approval,
Champion replacement atomicity, rollback recovery, market-data lineage,
provider readiness, and Korean final-response policy.

## Invariants

- No live trading.
- No KIS/Broker order.
- No automatic Champion promotion.
- No approval bypass.
- No strategy mutation before explicit approval.
- No fixture-backed production promotion.
- No metadata-only promotion evidence.
- No fabricated evidence or metrics.
- Unknown or insufficient validation remains fail-closed.

## Operational Verification

Local deterministic closeout:

```bash
python -m gaon.runtime.cli gaon-production-gaon-v2-completion-release-check
python -m gaon.runtime.cli gaon-production-v2-final-closeout-release-check
```

VPS deployment verification:

```bash
cd /opt/strategylab-v2
git pull origin main
.venv/bin/pip install -e .
systemctl restart strategylab-gaon
.venv/bin/python -m gaon.runtime.cli deployment-import-path-check --expected-source /opt/strategylab-v2/src/gaon
.venv/bin/python -m gaon.runtime.cli gaon-production-gaon-v2-completion-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
.venv/bin/python -m gaon.runtime.cli gaon-production-v2-final-closeout-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

Telegram production acceptance should use the real user-facing prompt and verify
that Gaon either stops at `needs_more_evidence` with honest blockers or reaches
human approval readiness without applying strategy changes.

## Rollback

Code rollback follows normal Git deployment rollback. Champion rollback uses the
existing `champion-rollback` CLI and Champion registry history; approval and
activation records remain retained for audit.
