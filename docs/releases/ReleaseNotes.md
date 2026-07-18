# StrategyLab v2.1 Release Candidate Notes

Status: v2.1 Release Candidate  
Base: StrategyLab v1.0 Stable Release

## Sprint 51-55 Conversational Release

Gaon now has a persistent conversational brain foundation for StrategyLab v5. It stores conversation history, builds bounded verified context, exposes read-only tools through a deny-by-default policy, and connects Telegram ordinary text to the persistent brain.

This release does not add live trading, MyMoneyGuard access, broker orders, arbitrary shell or SQL tools, automatic approval, required Ollama, or required paid provider fallback.

## Sprint 47 Strategy Execution Runtime

Included:

- `strategy_execution_policy_v1`
- `DISABLED`, `PAPER`, and `LIVE` execution modes
- default `DISABLED` mode
- active Champion version and fingerprint binding
- PAPER execution through the existing paper adapter stack
- LIVE planning gates using Paper Revalidation status
- runtime schema v18
- events, metrics, CLI commands, unit tests, and integration tests

Not included:

- KIS adapter
- live broker orders
- live execution enablement
- automatic Champion promotion
- automatic rollback
- automatic approval
- MyMoneyGuard dependency

## Sprint 46 Paper Revalidation and Kill/Rollback Gates

Included:

- `paper_revalidation_policy_v1`
- `LIVE_ELIGIBLE`, `HOLD`, `KILL`, `ROLLBACK_RECOMMENDED`, and `REVIEW`
- paper session, summary, active Champion fingerprint, and evidence consistency gates
- runtime schema v17
- events, metrics, CLI commands, unit tests, and integration tests

Not included:

- live trading enablement
- KIS adapter
- broker orders
- automatic Champion rollback
- automatic Champion Registry mutation
- automatic approval
- MyMoneyGuard dependency

## Sprint 45 Paper Trading Forward Test

Included:

- paper-only forward-test sessions for the active Champion
- `paper_forward_test_policy_v1`
- session lifecycle: pending, active, paused, completed, failed, cancelled
- simulated paper order observations using the existing paper adapter stack
- deterministic performance summaries without fabricated unavailable metrics
- runtime schema v16
- events, metrics, CLI commands, unit tests, and integration tests

Not included:

- live KIS
- broker credentials
- real orders
- paper-to-live automatic promotion
- automatic Champion changes from paper results
- automatic approval
- MyMoneyGuard dependency

## Sprint 44 Champion Registry and Approval Promotion

Included:

- runtime schema v15 for Champion registry, history, promotion requests, and promotion decisions
- explicit first Champion bootstrap
- promotion request creation only from Sprint 43 `promotion_candidate` evaluations
- explicit approval and rejection workflow
- active Champion registry update after approval only
- immediate previous Champion rollback with preserved history
- events, metrics, CLI inspection, unit tests, and integration tests

Not included:

- automatic Champion promotion
- direct `PROMOTION_CANDIDATE` activation
- active strategy switching
- Paper Trading forward-test sessions
- live KIS
- broker credentials
- real orders
- automatic trading
- automatic approval
- MyMoneyGuard integration

## Sprint 43 Champion / Challenger Evaluation Engine

Included:

- runtime schema v14 for Champion / Challenger evaluation requests and reports
- deterministic `champion_challenger_policy_v1`
- structured request, policy, comparison, report, decision, and role contracts
- validation status hard gate using Sprint 42 `ValidationReport`
- fingerprint existence and difference gates
- return improvement gate using percentage-point improvement
- MDD degradation gate using Sprint 42 positive-fraction convention
- profit factor comparison when both values exist
- sample period and trade count explainability
- persistence, events, metrics, CLI inspection, and bounded Executive Planner / Research Agent route

Not included:

- automatic Champion promotion
- active strategy switching
- live KIS
- broker credentials
- real orders
- automatic trading
- automatic approval
- MyMoneyGuard integration
- arbitrary shell execution
- paid-provider fallback

`PROMOTION_CANDIDATE` is not `PROMOTED`.

## Sprint 42 Strategy Validation Engine

Included:

- runtime schema v13 for validation requests and validation reports
- deterministic validation contracts: `ValidationRequest`, `ValidationPolicy`, `ValidationRule`, `ValidationRuleResult`, `ValidationReport`, `ValidationStatus`, `ValidationSeverity`, and `ValidationEvidence`
- `validation_policy_v1` with conservative defaults for trade count, maximum drawdown, profit factor, sample duration, and fingerprint completeness
- MDD normalization to a documented positive-fraction convention
- optional metric handling without fabrication
- multi-run aggregation for passing window ratio and catastrophic window detection
- non-ML overfitting heuristic warnings
- lifecycle events, metrics, persistence, CLI inspection, Research Agent integration, and Executive Planner validation routing

Not included:

- Champion ranking
- Challenger ranking
- Champion promotion
- active strategy switching
- parameter optimization
- paper trading promotion
- live KIS
- broker orders
- automatic trading
- automatic approval
- MyMoneyGuard integration
- live market data
- network calls
- paid-provider fallback

Validation PASS does not automatically promote or deploy a strategy.

## Sprint 41 v1 Backtest Adapter Foundation

Included:

- runtime schema v12 for backtest requests and normalized results
- structured BacktestRequest, BacktestStrategyRef, BacktestDatasetRef, BacktestPeriod, BacktestExecutionContext, BacktestResult, BacktestMetrics, BacktestTradeSummary, and BacktestStatus models
- BacktestAdapter contract
- deterministic FakeBacktestAdapter
- LocalProcessBacktestAdapter boundary for a future fixed v1 entrypoint with JSON request/response
- normalized v1 result conversion with optional metrics, warnings, errors, engine version, duration, parameters, dataset reference, and reproducibility metadata
- stable fingerprint generation for future validation and Champion/Challenger comparison
- SQLiteBacktestRepository, BacktestExecutionService, lifecycle events, metrics, CLI commands, and tests
- bounded Executive Planner to Research Agent to BacktestAdapter flow

Not included:

- real v1 engine dependency in automated tests
- Champion/Challenger ranking
- strategy promotion
- active strategy switching
- paper trading promotion
- live strategy deployment
- KIS integration
- MyMoneyGuard integration
- automatic trading
- automatic approval
- arbitrary shell execution
- network calls
- private repository dependency

## Sprint 40 Trading Adapter Foundation

Included:

- runtime schema v11 for trading requests and simulation results
- structured TradingIntent, TradingAction, OrderSide, OrderType, TradingRequest, TradingDecision, TradingExecutionContext, TradingResult, TradingStatus, AccountSnapshot, and PositionSnapshot models
- TradingRiskPolicy guardrails for quantity, symbol format, max notional, max position, duplicate request, unsupported order type, disabled adapter, and live execution blocking
- FakeTradingAdapter compatibility and deterministic PaperTradingAdapter
- TradingExecutionService with structured errors, no-crash failure isolation, durable events, metrics, and persistence
- Executive Planner and Agent Dispatcher route for paper trading simulation
- CLI commands for `trading-status`, `trading-account`, `trading-positions`, `trading-simulate-buy`, `trading-simulate-sell`, `trading-cancel-simulated-order`, and `trading-history`

Not included:

- live trading
- KIS REST
- KIS WebSocket
- broker authentication
- real account access
- real balance query
- real order execution
- automatic trading
- automatic approval
- MyMoneyGuard integration
- live market data
- Telegram trading commands
- paid-provider fallback
- unrestricted shell execution

## Sprint 39 Daily Research Pipeline

Included:

- runtime schema v10 for daily research profiles and runs
- daily research profile creation, enable, disable, list, and show workflows
- Sprint 38 scheduler integration without adding a second scheduler
- due execution with disabled profile skip, duplicate run protection, bounded failure isolation, durable state, events, and metrics
- deterministic ResearchRequest to planner to bounded evidence search to context builder to synthesis to report flow
- markdown and json report output
- pending-review KnowledgeProposal persistence without trusted knowledge promotion
- CLI commands for `daily-research-create`, `daily-research-list`, `daily-research-show`, `daily-research-enable`, `daily-research-disable`, `daily-research-run`, and `daily-research-report`

Not included:

- Telegram delivery
- email delivery
- Notion synchronization
- GitHub polling
- live market data
- Trading Adapter execution
- broker, KIS, or MyMoneyGuard access
- external AI provider calls
- vector DB or embeddings
- automatic knowledge approval
- automatic policy change
- shell or plugin execution

## Sprint 38 Scheduler Automation

Included:

- runtime schema v9 for scheduled automation jobs and runs
- durable scheduled job creation, enable, disable, lookup, list, and due detection
- bounded scheduled execution through Executive Planner and Agent Dispatcher
- disabled-job skip, duplicate run protection, bounded retry, blocked approval-required flow, and failure isolation
- scheduled lifecycle durable events and runtime metrics
- deterministic schedule CLI smoke commands

Not included:

- Daily Research topic logic
- morning market report business logic
- Telegram delivery
- GitHub polling automation
- Notion synchronization
- Trading Adapter execution
- KIS connection
- broker orders
- automatic trading
- automatic approval
- unrestricted shell execution
- unrestricted filesystem mutation
- arbitrary plugin loading

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
# Sprint 48

StrategyLab can now generate a portable handoff package from an active Champion
and a LIVE_ELIGIBLE paper revalidation report. The generated package requires
explicit human approval before deployment eligibility.

# Sprint 49

StrategyLab can now plan and run an approval-gated deployment workflow against
generic deployment adapters. Public tests use fake and local-safe adapters only;
private production integration remains outside this repository.

# Sprint 50

Gaon v5.0 RC completes the first bounded end-to-end StrategyLab system pipeline.
It remains approval-gated, broker-free in public tests, and independent of any
private repository.

# Sprint 50 Hotfix

`v5-demo --dry-run` now creates a unique default pipeline run id and namespaces
demo fixture entities so repeated runs against the same persistent DB do not
collide with `v5-release-check` or prior demos.
