# Gaon Phase B v3.0 Release Candidate

Branch: `feature/gaon-phase-b-research-brain-v3`

Phase B completes the Research Brain v3 foundation across Sprints 30 to 35.

## Included

- Sprint 30: validated research planning.
- Sprint 31: safe evidence search providers.
- Sprint 32: evidence ranking, citations, and context building.
- Sprint 33: evidence-backed knowledge proposals.
- Sprint 34: auditable research approval workflow.
- Sprint 35: durable Research Brain orchestration, checkpoints, reports, CLI smoke paths, and schema v8.

## Database Migrations

- v6: `knowledge_proposals`, `trusted_knowledge`
- v7: `research_approval_decisions`
- v8: `research_brain_runs`, `research_brain_checkpoints`

## Verification Scope

- Unit tests
- Integration tests
- `scripts/verify_release.py`
- CLI smoke commands for runtime and research paths

Automated verification uses deterministic local providers and fake transports only.

## Known Limits

- No live broker, KIS, MyMoneyGuard, account, or trading integration.
- No live Telegram, Notion, GitHub, OpenAI, Claude, Gemini, or paid provider call in tests.
- Knowledge proposals still require explicit review before promotion.
- Research reports are deterministic dry-run artifacts until live providers are reviewed and connected.

## Rollback

Rollback by reverting the six Phase B commits or by returning runtime databases to a backup taken before schema v6-v8 migration. Production trading systems are out of scope for this public repository.
