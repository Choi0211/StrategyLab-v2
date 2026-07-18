# StrategyLab v2.1 Release Candidate Notes

Status: v2.1 Release Candidate  
Base: StrategyLab v1.0 Stable Release

## Sprint 37 Multi-Agent Execution Framework

Included:

- common bounded agent contracts
- explicit agent registry
- ExecutivePlan-consuming dispatcher
- deterministic ResearchAgent, CodingAgent, and MemoryAgent
- non-executing TradingAgent placeholder
- capability validation
- approval-required blocking
- failure isolation
- durable lifecycle events
- runtime metrics
- deterministic `agent-run` CLI smoke

Not included:

- scheduler execution
- cron or daily research automation
- Telegram-triggered agent execution
- broker or KIS execution
- automatic trading
- automatic approval
- arbitrary shell execution
- unrestricted filesystem mutation
- arbitrary plugin loading

## Sprint 36 Executive Planner

Included:

- immutable executive request and plan contracts
- deterministic routing for research, memory, runtime status, human review, and unsupported requests
- provider-backed routing through the existing Assistant Provider Registry
- free-only and paid-provider guardrails
- approval-required flag support
- durable event helper, runtime metrics, CLI plan inspection, unit tests, and integration tests

Not included:

- multi-agent execution
- scheduler execution
- trading adapter execution
- Telegram integration
- automatic approval

## Gaon Phase B v3.0 Research Brain RC

Included:

- Sprint 30 validated research planning with deterministic and provider-backed plan contracts
- Sprint 31 safe evidence provider contracts with fake, fixture, RSS/Atom, and disabled optional web providers
- Sprint 32 evidence ranking, citation assignment, context budgeting, and contradiction preservation
- Sprint 33 evidence-backed knowledge proposals stored separately from trusted knowledge
- Sprint 34 auditable research approval workflow with stale proposal and replay protection
- Sprint 35 Research Brain v3 orchestration, run states, checkpoints, reports, resume, CLI smoke paths, schema v8, and free-only runtime defaults

Not included:

- live broker, KIS, account, or MyMoneyGuard integration
- live Telegram, Notion, GitHub, OpenAI, Claude, Gemini, or paid provider calls in automated tests
- automatic trusted knowledge promotion
- automatic policy update
- automatic approval or trading execution

## Gaon Phase A v2.1

Included:

- assistant provider registry and deterministic fallback routing
- explicit plugin lifecycle management
- internal metrics and observability
- durable event store and safe replay
- long-term memory namespace/lifecycle foundation
- runtime service integration and event replay dry-run CLI

This release candidate is not production trading ready.

## Sprint 18-23 Production Hardening

Included:

- HMAC-SHA256 approval token digest storage and single-use approval consumption
- SQLite runtime repository layer and schema v2 migration
- schema v3 durable queue, durable scheduler, idempotent duplicate guard, and recovery contracts
- controlled runtime service loop with readiness, graceful stop, bounded drain, CLI run/status/backup, and redacted structured logs
- security and chaos tests for replay, tampering, prompt injection as data, provider failure, duplicate storms, restart recovery, scheduler idempotency, log redaction, and backup restore
- broker-free TradingAdapter protocol, risk-gate contracts, fake adapter tests, and v1 rollout plan

Not included:

- live Telegram daemon verification
- live OpenAI provider verification
- live Notion synchronization verification
- live broker verification
- private MyMoneyGuard integration
- automatic trading or approval

## Gaon Runtime Collaboration

Included:

- runtime configuration with secret masking
- deterministic in-process event bus
- deterministic Korean Conversation Runtime
- Sprint 13 natural-language intent router and Gaon persona layer
- Sprint 14 read-only memory-aware conversation context
- Assistant Provider interface for future LLM providers without SDK or network implementation
- Sprint 15 guarded assistant provider integration with deterministic fallback and OpenAI-compatible fake-transport tests
- Sprint 16 guarded research orchestration with explicit approval gates and in-memory queue
- Sprint 17 SQLite runtime state, health checks, service skeleton, backup helper, and VPS deployment docs
- Telegram production smoke client and dry-run adapter
- Telegram one-shot smoke commands for bot metadata, chat discovery, smoke send, and poll-once processing
- Notion dry-run mapper and sync contracts
- notification engine
- daily report and weekly review contracts
- in-memory scheduler
- safe dry-run CLI
- Learning Memory claims snapshot and retrieval hardening

Not included:

- long-running Telegram daemon or webhook server
- offset persistence storage
- real Notion network execution
- real LLM provider connection
- market data, calendar, stock analysis, or Telegram-triggered backtest execution
- automatic Learning Memory mutation from conversation
- external AI API
- vector DB or embeddings
- MyMoneyGuard/KIS access
- live trading
- automatic approvals

## Sprint 12-B Learning Memory Repository

Sprint 12-B adds deterministic repository and detection contracts for Learning Memory.

Included:

- `LearningRepository` protocol
- `InMemoryLearningRepository`
- duplicate candidate detection without automatic merge
- conflict candidate detection without automatic resolution
- chronological lookup
- project/strategy/market AND filters
- append-only audit workflow
- KnowledgeApproval and PolicyApproval scope matching
- ISO 8601 UTC timestamp validation
- golden JSON and migration compatibility fixtures
- related-memory retrieval with score breakdown
- repository JSON export/import
- explicit v0 to v1 migration path
- Research Brain conversion and no-auto-save memory preparation
- separate `PreferenceApproval`

Not included:

- real DB
- vector DB
- embedding or related-memory ranking
- external AI API
- Telegram or Dashboard runtime
- MyMoneyGuard access
- live trading

## Sprint 12-A Learning Memory Contracts

Sprint 12-A adds domain contracts only.

Included:

- LearningRecord
- KnowledgeClaim
- ResearchOutcome
- FailurePattern
- SuccessPattern
- UserPreference
- ConversationSummary
- ConfidenceScore
- LearningProposal
- PolicyRevision
- RevalidationSchedule
- KnowledgeApproval
- PolicyApproval
- AuditEvent

Not included:

- search engine
- real DB
- vector DB
- external AI API
- Telegram or Dashboard runtime
- MyMoneyGuard access
- live trading

## Sprint 11 Development Start

Sprint 11 starts the Gaon Research Brain and Learning Memory foundation.

Included in Sprint 11 start:

- Gaon Development Contract v1.0.
- `gaon.learning` package boundary.
- Learning Memory evidence rules.
- Knowledge lifecycle and user approval rule for `Validated`.
- Policy update candidate approval and rollback metadata.
- ADR/RFC documentation for Learning Memory core.
- Research Brain contracts for evidence-backed goals, plans, sessions, interviews, and journals.
- Research Brain hardening for session transitions, pending interview answers, and versioned JSON round-trip serialization.

## Included

- Blueprint and sprint governance.
- Public/private separation policy.
- Core project foundation.
- Market data contracts and validation.
- Strategy parameter and signal framework.
- Deterministic backtest contracts.
- Portfolio accounting foundation.
- Risk metric foundation.
- AI review schema foundation.
- Dashboard view model foundation.
- Safe broker interface and paper adapter.
- End-to-end integration test from market fixture through strategy, portfolio sizing, risk validation, backtest, and paper broker fill.
- GitHub Actions verification on Ubuntu and Windows with Python 3.11 and 3.12.

## Not Included

- Live trading.
- Real broker API credentials.
- Private MyMoneyGuard access.
- Production deployment.
- Full optimizer.

## Verification

Run:

```bash
PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit
PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration
python scripts/verify_release.py
```
