# Gaon v5.0 Release Candidate

Status: Release Candidate

Gaon v5.0 RC is the first complete public StrategyLab system pipeline. It links
research fixtures, backtest results, validation, Champion/Challenger evaluation,
explicit promotion approval, Champion activation, paper forward-test,
revalidation, approved handoff packages, explicit deployment approval, and
approval-gated deployment with backup, dry-run, verification, and rollback.

## Scope

- deterministic v5 pipeline orchestration
- SQLite pipeline checkpoints and resume state
- two approval boundaries
- fake/local-safe deployment adapters
- release verification and documentation

## Architecture

Research -> Backtest -> Validation -> Champion Evaluation -> Promotion Approval
-> Champion Activation -> Paper Forward Test -> Paper Revalidation -> Handoff
Package -> Deployment Approval -> Deployment -> Verification -> Completed.

If deployment modifies a target and verification fails, rollback is attempted
and the rollback result is persisted.

## Sprint 30-50 Milestones

- runtime collaboration, scheduling, daily research
- trading adapter foundation without live broker dependency
- v1 backtest adapter boundary
- validation engine
- Champion/Challenger evaluation
- approval-gated Champion registry
- paper forward-test and revalidation
- strategy handoff package
- approval-gated deployment workflow
- v5 release-candidate orchestration

## Supported Workflows

- deterministic v5 release demo
- pipeline status/history/show
- explicit Champion promotion approval
- explicit handoff deployment approval
- fake deployment success and rollback tests
- SQLite backup and restore

## Safety Boundaries

- no automatic approval
- no direct KIS or broker order execution from v2
- no private repository dependency
- no committed secrets
- no arbitrary shell execution
- backup required before deployment
- dry-run required before deployment
- post-apply verification required
- rollback failure surfaced explicitly
- profitability is not guaranteed

## Known Limitations

- LLM natural conversation remains limited without an active LLM provider.
- Autonomous unrestricted web research is not complete.
- Autonomous strategy invention/coding loop is not complete.
- Real external v1 deployment adapter must be configured separately.
- Private runtime integration is not part of public automated tests.
- Human approval remains required for strategy promotion and deployment.

## Deployment Requirements

- Python 3.11 or 3.12
- runtime SQLite DB outside Git
- environment file outside Git
- systemd service for continuous runtime if deployed on VPS
- generic external deployment adapter for production v1 runtime

## Rollback Procedure

1. Stop the runtime service.
2. Back up the current runtime DB.
3. Restore the previous runtime SQLite backup if DB rollback is required.
4. Use the deployment backup recorded by the deployment workflow.
5. Restart/reload the target runtime.
6. Run health and Telegram checks.
7. Record the incident and recovery refs.

## Post-v5 Roadmap

Phase 2A / Sprint 51-55: LLM Brain and Natural Conversation.

Phase 2B / Sprint 56-60: Autonomous Internet Research.

Phase 2C / Sprint 61-65: Autonomous Strategy Lab.

Phase 2D / Sprint 66-70: Autonomous Improvement Loop.
