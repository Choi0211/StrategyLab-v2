# V1 Integration Rollout Plan

Status: Sprint 23 v2 release candidate plan

StrategyLab-v2 does not modify or import MyMoneyGuard V1. It defines public contracts that a future private adapter may implement after review.

## Rollout Stages

1. Read-only
   - account summary
   - positions
   - market status
   - runtime and strategy status

2. Paper
   - synthetic command proposal
   - deterministic validation
   - no broker execution

3. Shadow
   - compare StrategyLab proposals with private production state
   - no live order placement
   - record evidence and mismatch reasons

4. Approval-Gated Execution
   - explicit approval reference required
   - execution disabled by default
   - emergency stop and risk gates required

## Required Approval Before Private Connection

- final architecture review
- secret handling review
- rollback plan
- audit logging plan
- dry-run and shadow-mode evidence
- user approval

## Non-Goals

- no MyMoneyGuard rewrite
- no broker SDK in public repo
- no KIS API in public repo
- no live Telegram order execution from public repo
