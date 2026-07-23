# Changelog

## Sprint 56-60 - Gaon LLM Agent

- Added generic OpenAI-compatible provider diagnostics and tool-call support.
- Added native provider-requested safe read-only tool execution.
- Added multi-turn follow-up handling with bounded tool-result memory.
- Added safe conversational agent planner with approval-boundary stops.
- Added LLM agent release hardening, CLI diagnostics, prompt-injection tests, and low-resource VPS limits.

## Sprint 51-55 - Gaon LLM Brain

- Added persistent LLM conversation sessions and messages.
- Added bounded contextual memory orchestration from read-only runtime state.
- Added safe read-only tool registry, execution policy, and audit storage.
- Added Telegram conversational agent routing while preserving offset and duplicate protection.
- Added assistant/conversation/tool CLI inspection commands and release checks.

## Sprint 47 Strategy Execution Runtime

- Added Strategy Execution Runtime with `strategy_execution_policy_v1`.
- Added explicit `DISABLED`, `PAPER`, and `LIVE` modes with default `DISABLED`.
- Added active-Champion binding and stale Champion execution blocking.
- Added PAPER execution orchestration using the existing paper adapter stack.
- Added LIVE planning gates against paper revalidation, while keeping live execution blocked because the broker adapter is unavailable.
- Added runtime schema v18 with strategy execution plan and run tables.
- Added CLI commands for policy, status, plan, run, show, and history.
- Preserved safety boundaries: no live KIS, no broker credentials, no real orders, no automatic approval, no automatic rollback, and no MyMoneyGuard dependency.

## Sprint 46 Paper Revalidation and Kill/Rollback Gates

- Added deterministic Paper Revalidation Engine with `paper_revalidation_policy_v1`.
- Added `LIVE_ELIGIBLE`, `HOLD`, `KILL`, `ROLLBACK_RECOMMENDED`, and `REVIEW` safety decisions.
- Added runtime schema v17 with paper revalidation request and report tables.
- Added CLI commands for policy display, revalidation, report show, and history.
- Added events and metrics for live eligibility, hold, kill, rollback recommendation, and review outcomes.
- Preserved safety boundaries: no live KIS, no broker credentials, no real orders, no automatic rollback, no automatic approval, and no registry mutation.

## Sprint 45 Paper Trading Forward Test

- Added paper-only Champion forward-test sessions.
- Reused existing `PaperTradingAdapter`, `TradingExecutionService`, `TradingRiskPolicy`, and `SQLiteTradingRepository`.
- Added session lifecycle commands for create, start, pause, resume, complete, cancel, show, list, simulated order, and summary.
- Added runtime schema v16 with paper trading session, observation, and summary tables.
- Added events and metrics for paper session lifecycle and simulated orders.
- Added unit and integration coverage for active-Champion-only creation, stale Champion rejection, lifecycle transitions, summary generation, persistence, CLI smoke, and v15-to-v16 migration.
- Preserved safety boundaries: no live KIS, no broker credentials, no real orders, no paper-to-live promotion, no automatic trading, and no MyMoneyGuard dependency.

## Sprint 44 Champion Registry and Approval Promotion

- Added approval-gated Champion Registry for the stable `default` slot.
- Added explicit bootstrap, promotion request, approve, reject, history, registry show, and rollback CLI commands.
- Added runtime schema v15 with Champion registry, version history, promotion request, and promotion decision tables.
- Added events and metrics for bootstrap, promotion request, approval, rejection, activation, and rollback.
- Added unit and integration coverage for idempotent promotion requests, approval, rejection, rollback, persistence, and migration.
- Preserved safety boundaries: no direct `PROMOTION_CANDIDATE` activation, no live KIS, no broker orders, no automatic trading, no automatic approval, and no MyMoneyGuard dependency.

## Sprint 43 Champion / Challenger Evaluation Engine

- Added deterministic Champion / Challenger Evaluation Engine.
- Added `StrategyRole`, `ChampionChallengerDecision`, request, policy, comparison, report, repository, event, and metric contracts.
- Added `champion_challenger_policy_v1` with validation, fingerprint, return improvement, MDD degradation, profit factor, sample period, and trade count comparisons.
- Added runtime schema v14 with Champion / Challenger evaluation request and report tables.
- Added CLI commands for policy display, evaluation, report show, and history.
- Documented that `PROMOTION_CANDIDATE` is not `PROMOTED` and cannot trigger trading or active strategy switching.

## Sprint 42 Strategy Validation Engine

- Added deterministic Strategy Validation Engine for normalized Sprint 41 `BacktestResult` records.
- Added `ValidationRequest`, `ValidationPolicy`, `ValidationRule`, `ValidationRuleResult`, `ValidationReport`, status, severity, and evidence contracts.
- Added conservative `validation_policy_v1` with MDD, trade count, sample period, profit factor, fingerprint, multi-run, and overfitting heuristic checks.
- Added runtime schema v13 with `validation_requests` and `validation_reports`.
- Added validation lifecycle events, runtime metrics, Research Agent validation routing, Executive Planner validation capability, and CLI commands.
- Documented that Validation PASS does not automatically promote, deploy, trade, approve, or switch strategies.

## Hotfix Telegram Runtime Worker and systemd Service

- Wired persistent Telegram polling into `GaonRuntimeService` through a bounded runtime worker.
- Updated CLI `run` so default execution is a persistent service loop and `run --once` performs exactly one tick.
- Reused the existing `telegram-poll-once` logic, SQLite Telegram state repository, offset persistence, processed message duplicate guard, and execute/dry-run gates.
- Isolated transient Telegram failures so the runtime can continue on later ticks, with durable runtime events and metrics.
- Updated systemd service execution from one-shot `health` to persistent `run --db /var/lib/strategylab/gaon-runtime.sqlite`.

## Hotfix Telegram Poll Offset Persistence

- Connected `telegram-poll-once` execute path to the existing SQLite Telegram state repository.
- Added saved offset loading when `--offset` is omitted and documented explicit `--offset` precedence.
- Added processed message duplicate protection so repeated poll executions do not send duplicate replies.
- Persisted highest safe `next_offset` for sent, duplicate, unauthorized, and ignored updates.
- Added unit and integration coverage for offset persistence, duplicate skipping, restart preservation, explicit offsets, and unauthorized/ignored update progression.

## Sprint 41 v1 Backtest Adapter Foundation

- Added runtime schema v12 for backtest requests and normalized backtest results.
- Added BacktestRequest, BacktestStrategyRef, BacktestDatasetRef, BacktestPeriod, BacktestExecutionContext, BacktestResult, BacktestMetrics, BacktestTradeSummary, and BacktestStatus contracts.
- Added BacktestAdapter, FakeBacktestAdapter, LocalProcessBacktestAdapter, SQLiteBacktestRepository, and BacktestExecutionService.
- Added v1 result normalization, optional metric preservation, stable reproducibility fingerprints, bounded local-process invocation handling, lifecycle events, runtime metrics, CLI commands, and v11-to-v12 migration coverage.
- Exposed the adapter through the existing Executive Planner and Research Agent in a bounded fake-adapter path.
- The real v1 backtest engine is not required for automated tests.
- Did not add Champion/Challenger ranking, strategy promotion, active strategy switching, paper trading promotion, live strategy deployment, KIS integration, MyMoneyGuard integration, automatic trading, automatic approval, arbitrary shell execution, network calls, or private repository dependencies.

## Sprint 40 Trading Adapter Foundation

- Added runtime schema v11 for trading requests and structured simulation results.
- Added structured trading models for intents, actions, sides, order types, requests, decisions, execution context, results, statuses, account snapshots, and position snapshots.
- Added TradingRiskPolicy, TradingExecutionService, SQLiteTradingRepository, and deterministic PaperTradingAdapter.
- Extended Executive Planner and Agent Dispatcher with a safe trading simulation route.
- Added durable trading lifecycle events, runtime metrics, deterministic trading CLI commands, unit tests, integration tests, and v10-to-v11 migration coverage.
- Live trading is not implemented.
- Did not add KIS REST, KIS WebSocket, broker authentication, real account access, real order execution, automatic trading, automatic approval, MyMoneyGuard integration, live market data, Telegram trading commands, paid-provider fallback, or unrestricted shell execution.

## Sprint 39 Daily Research Pipeline

- Added runtime schema v10 for daily research profiles and runs.
- Added DailyResearchTopic, DailyResearchProfile, DailyResearchRun, DailyResearchRunStatus, and DailyResearchResult contracts.
- Added DailyResearchRepository with duplicate profile rejection, deterministic listing, enable/disable workflow, durable run storage, and duplicate run protection.
- Added DailyResearchPipeline on top of the Sprint 38 ScheduledJobRepository; no second scheduler was introduced.
- Added deterministic daily research execution through ResearchRequest, deterministic planner, bounded fake evidence search, context builder, markdown/json report generation, and pending-review knowledge proposal persistence.
- Added durable events, runtime metrics, CLI commands, unit tests, integration tests, and v9-to-v10 migration coverage.
- Did not add Telegram delivery, email, Notion sync, GitHub polling, live market data, Trading Adapter execution, broker/KIS/MyMoneyGuard access, external AI calls, vector DB, automatic approval, shell execution, or plugin execution.

## Sprint 38 Scheduler Automation

- Added runtime schema v9 for durable scheduled automation jobs and runs.
- Added ScheduleDefinition, ScheduledJob, ScheduledRun, ScheduledRunStatus, and ScheduledExecutionRequest contracts.
- Added ScheduledJobRepository with explicit creation, enable/disable, lookup, deterministic listing, due lookup, bounded attempts, and duplicate run protection.
- Added ScheduledAutomationRunner that routes due jobs through Executive Planner and Agent Dispatcher without bypassing approval or capability boundaries.
- Added scheduled lifecycle durable events, runtime metrics, and schedule CLI smoke commands.
- Did not add Daily Research business logic, Telegram delivery, live Trading/KIS execution, automatic approval, paid-provider fallback, or private repository dependencies.

## Sprint 37 Multi-Agent Execution Framework

- Added Agent, AgentRequest, AgentExecutionContext, AgentResult, AgentCapability, and AgentStatus contracts.
- Added explicit AgentRegistry with duplicate registration rejection, unknown-agent rejection, stable lookup, capability inspection, and deterministic ordering.
- Added AgentDispatcher that consumes ExecutivePlan, validates capabilities, invokes one agent safely, isolates failures, and blocks approval-required plans.
- Added deterministic ResearchAgent, CodingAgent, MemoryAgent, and non-executing TradingAgentPlaceholder.
- Added agent lifecycle durable events, runtime metrics, and `agent-run` CLI smoke path.
- Did not add scheduler execution, daily research automation, Telegram-triggered execution, broker/KIS execution, automatic approval, arbitrary shell execution, or dynamic plugin loading.

## Sprint 36 Executive Planner

- Added immutable ExecutiveRequest, ExecutivePlan, RoutingDecision, AgentSelection, ToolSelection, and ExecutivePlanner contracts.
- Added deterministic routing for research, memory, runtime status, human review, and unsupported requests.
- Added provider-backed planning through the existing Assistant Provider Registry with free-only and paid-provider guardrails.
- Added approval-required flag propagation for execution-capable or policy-changing requests.
- Added ExecutivePlanCreated durable event helper, runtime metrics integration, and CLI plan inspection.
- Did not add multi-agent execution, scheduler execution, trading adapter execution, or Telegram integration.

## Sprint 35 Research Brain Orchestration

- Added schema v8 Research Brain run and checkpoint tables.
- Added deterministic ResearchOrchestratorV3 with run states, checkpoints, reports, resume, and metrics.
- Added research CLI smoke commands for plan, run, status, report, and resume paths.
- Added free-only runtime configuration defaults and paid-provider guardrails.
- Added Phase B Research Brain architecture, runtime operations, free-only mode, and release candidate documentation.

## Sprint 30 Validated Research Planning

- Added bounded ResearchRequest, ResearchPlan, and ResearchStep contracts.
- Added deterministic planner with stable plan hash and plan lifecycle event support.
- Added allowlisted research step types, dependency validation, cycle rejection, and step limit enforcement.
- Added optional provider-backed planner with free-only enforcement and structured output validation.
- Added planner metrics coverage.

## Sprint 31 Safe Evidence Search Providers

- Added provider-neutral search contracts with normalized source metadata.
- Added fake, local fixture, RSS/Atom, and optional disabled-by-default web search providers.
- Added canonical URL normalization, domain allow/deny filtering, result limits, content-size limits, duplicate URL removal, timeout and bounded retry behavior.
- Added search metrics and durable event helper coverage without live network tests.

## Sprint 32 Evidence Ranking and Context Building

- Added EvidenceItem, EvidenceBundle, citation, and evidence-to-context contracts.
- Added canonical URL normalization reuse, content hashing, exact duplicate removal, conservative near-duplicate detection, stable ranking, and citation ID assignment.
- Added memory/external evidence merge, context budget enforcement, truncation diagnostics, and contradiction preservation.
- Added explicit source-quality rule hook with conservative defaults.

## Sprint 33 Evidence-Backed Knowledge Proposals

- Added schema v6 knowledge proposal and trusted knowledge tables.
- Added evidence-linked research knowledge claims, proposal confidence, stable proposal hashes, explicit versions, provenance, review/expiration metadata, and insufficient-evidence status.
- Added contradiction surfacing and proposal lifecycle event/metrics helpers.
- Kept proposal persistence separate from trusted knowledge and disallowed direct trusted promotion.

## Sprint 34 Auditable Research Approval Workflow

- Added schema v7 research approval decision table and idempotency index.
- Added proposal hash/version-bound approval requests and approve/reject/revise decision contracts.
- Added stale proposal rejection, repeated decision idempotency, promotion replay protection, audit events, and approval/rejection metrics.
- Added dry-run research proposal CLI smoke commands.

## Sprint 24 Provider Registry and Routing

- Added explicit assistant provider registry with stable-name lookup, duplicate registration protection, and unknown provider fail-fast behavior.
- Added configuration-based deterministic and OpenAI-compatible provider selection.
- Added health-based deterministic fallback with structured fallback reason.
- Added routing tests with fake OpenAI-compatible transport only; no real provider network calls are required.

## Sprint 25 Explicit Plugin Lifecycle

- Added explicit plugin metadata, capability, health, registry, and manager contracts.
- Added allowlist-only lifecycle for configure, start, health, and reverse-order stop.
- Added duplicate plugin ID rejection, disabled-plugin guard, failure isolation, and redacted failure records.
- Added fake Telegram, Notion, and Trading plugin tests without live network calls.

## Sprint 26 Runtime Metrics and Observability

- Added standard-library internal metrics collector for counters, gauges, and timing observations.
- Added immutable metrics snapshot/export model and CLI `metrics` output.
- Added bounded component and label validation to prevent prompt, message, chat ID, token, API key, secret, or arbitrary payload leakage.
- Added concurrency and CLI tests without external observability dependencies.

## Sprint 27 Durable Event Store and Safe Replay

- Added schema v4 durable append-only event store and replay checkpoint tables.
- Added deterministic event append/read, duplicate protection, bounded replay batches, oversized payload rejection, and v3-to-v4 migration coverage.
- Added dry-run replay with side effects suppressed by default and checkpoint advancement only during non-dry-run successful projection processing.
- Added projection failure isolation and replay failure recording.

## Sprint 28 Long-Term Memory Foundation

- Added schema v5 long-term memory table and deterministic SQLite repository.
- Added `MemoryNamespace`, `MemoryLifecycle`, `MemoryRecord`, retention policy, conflict flags, and revalidation flags.
- Enforced proposal-first writes, trusted-workflow validation, system namespace authorization, and secret marker rejection.
- Added deterministic read-only context retrieval and backup/restore coverage without vector DB or automatic LLM validation.

## Sprint 29 Phase A Integration and v2.1 RC

- Integrated metrics and explicit plugin lifecycle into the controlled runtime service.
- Added event replay dry-run CLI diagnostic.
- Added Gaon Phase A architecture document, provider/plugin/event/memory ADRs, and project vision document.
- Updated README, release notes, operations guidance, and test results for v2.1 Release Candidate status.

## Sprint 23 v2 Release Candidate and Trading Adapter Contract

- Added broker-free `gaon.adapters.TradingAdapter` protocol and fake adapter contract tests.
- Added read-only account, position, market, and runtime status contracts.
- Added order command lifecycle, risk gate contracts, execution-disabled default, and approval reference requirement.
- Added v1 integration rollout plan: read-only -> paper -> shadow -> approval-gated execution.
- Documented that no live broker, KIS API, MyMoneyGuard private code, or Telegram-triggered order execution is connected.

## Sprint 22 Security, Chaos, and Resilience Coverage

- Replaced SQLite file-copy backup with `sqlite3.Connection.backup()` and atomic destination replacement.
- Added deterministic tests for prompt-injection-as-data, provider failure, duplicate storm, restart recovery, duplicate scheduler tick, log redaction, bounded retry, and backup restore.

## Sprint 21 Production Runtime Loop

- Added controlled `GaonRuntimeService` loop with readiness, recovery, stop event, bounded drain, tick injection, and structured redacted logs.
- Added CLI commands for `run`, `status`, and `backup`.

## Sprint 20 Durable Queue, Scheduler, and Recovery

- Added schema v3 runtime queue with PENDING, LEASED, RUNNING, SUCCEEDED, FAILED, and CANCELLED states.
- Added lease timeout recovery, durable scheduler idempotency, and DB-backed duplicate message guard.

## Sprint 19 SQLite Repository Layer

- Added runtime repository protocols and SQLite implementations for Telegram state, audit events, approvals, proposals, runs, scheduler jobs, and notification attempts.
- Added schema v2 migration and centralized runtime JSON serialization validation.

## Sprint 18 Approval Security Hardening

- Added explicit approval states and HMAC-SHA256 token digest storage.
- Added single-use approval consumption bound to actor, chat, proposal, approval, expiry, nonce, and run ID.
- Added execute-mode approval signing secret validation.

## Sprint 14 Memory-Aware Conversation

- Added read-only conversation context contracts for retrieved memory, research context, references, and build results.
- Added deterministic Learning Memory context builder with STRICT/BROAD/GLOBAL fallback.
- Added duplicate record removal, warning propagation, conflict and revalidation state summaries, and confidence-as-ranking-signal messaging.
- Connected memory context to selected research and memory intents without mutating repositories.
- Added Telegram memory query end-to-end coverage with fake runtime flow.

## Sprint 15 Guarded Assistant Provider Integration

- Expanded Assistant Provider contracts with capabilities, health, metadata, and provider error classes.
- Added deterministic fallback provider and OpenAI-compatible HTTP provider with injectable transport.
- Added prompt builder that separates instructions from user text and retrieved memory data.
- Added provider response validation, secret masking, timeout/malformed response fallback, and safety bypass for order/approval requests.
- Added fake Telegram/provider end-to-end coverage without real network calls.

## Sprint 16 Guarded Research Assistant Orchestration

- Added deterministic research request planner, proposal, approval, run, review, and queue contracts.
- Added explicit approval validation with actor, chat, token, and expiry checks.
- Added run state machine with terminal states and approval-gated running transition.
- Added in-memory deterministic queue with deduplication and retry limits.
- Added research orchestration unit and integration flow tests without autonomous execution.

## Sprint 17 Production Runtime Service

- Added SQLite runtime state schema, migrations, offset recovery, processed message idempotency, audit event storage, and backup helper.
- Added health/readiness/db-check CLI paths without secret output.
- Added service and worker foundations with readiness gate, duplicate guard, and bounded retry policy.
- Added systemd service example, env example, install/upgrade/rollback guide scripts, and VPS operations documentation.
- Added restart recovery and runtime service smoke tests.

## Sprint 13 Conversational Assistant Foundation

- Added deterministic Korean natural-language intent routing for greetings, Gaon calls, help, status, market status, stock analysis, schedules, backtests, recent research, and memory search requests.
- Added Gaon persona responses that address the user as `영하님` and avoid claiming disconnected work was executed.
- Added `AssistantProvider` request/response contracts for future OpenAI or local LLM integrations without adding any network provider or SDK dependency.
- Updated Conversation Runtime to record the response route and preserve event bus publication and approval/order safety boundaries.
- Added Telegram ordinary text end-to-end tests through the existing safe production smoke path.
- Documented that market data, schedule, stock analysis, and backtest execution are future provider/adapter connections.

## Telegram Production Connection

- Added a standard-library Telegram Bot API client with injectable HTTP transport.
- Added `getMe`, `getUpdates`, `sendMessage`, `deleteWebhook`, and `getWebhookInfo` operations.
- Added safe error mapping for authentication, rate limit, server, malformed JSON, `ok=false`, timeout, and oversized response cases.
- Added production smoke CLI commands: `telegram-get-me`, `telegram-discover-chat`, `telegram-send-smoke`, and `telegram-poll-once`.
- Added fail-closed execution gates for runtime mode, dry-run, Telegram enablement, bot token, explicit `--execute`, and allowed chat IDs.
- Added private text update parsing, ignored update results, chat discovery deduplication, message preview limiting, and manual offset reporting.
- Added fake HTTP unit/integration tests; no real Telegram token or network call is required in automated tests.

## Gaon Runtime Collaboration

- Fixed Windows-safe runtime timezone validation for `UTC` and `Asia/Seoul`.
- Strengthened runtime config validation for mode, booleans, HH:MM times, weekdays, and execute-mode guards.
- Replaced ambiguous CLI `--dry-run` defaults with explicit mutually exclusive dry-run/execute flags.
- Hardened Learning Memory snapshots with `claims` export/import.
- Added STRICT/BROAD/GLOBAL related-memory modes, token overlap, aliases, and EvidenceType quality scoring.
- Added `gaon.runtime` configuration, events, in-memory event bus, conversation runtime, notifications, reports, scheduler, and safe dry-run CLI.
- Added Telegram dry-run contracts, update parsing, authorization, formatting, and conversation bridge.
- Added Notion dry-run contracts, mapping, idempotent sync, and report payloads.
- Added runtime collaboration docs, ADRs, RFC, operations guides, unit tests, and integration tests.

## Sprint 12-B Learning Memory Repository

- Added `LearningRepository` protocol and deterministic `InMemoryLearningRepository`.
- Added duplicate and conflict candidate detectors without automatic merge or resolution.
- Added chronological lookup, project/strategy/market AND filters, and defensive copy storage behavior.
- Added append-only audit event workflow with target queries.
- Strengthened KnowledgeApproval and PolicyApproval scope matching.
- Added ISO 8601 UTC timestamp validation for Learning Memory contracts.
- Added golden JSON and migration compatibility fixtures.
- Added Sprint 12-B repository tests and documentation updates.
- Added related-memory deterministic retrieval with score breakdown.
- Added repository JSON export/import and explicit v0 to v1 migration path.
- Added synthetic golden fixtures under `tests/fixtures/learning_memory/`.
- Added Research Brain to Learning Memory conversion and no-auto-save preparation workflow.
- Added `PreferenceApproval` as a separate approval contract.

## Sprint 12-A Learning Memory Contracts

- Accepted ADR-0004 and ADR-0005 for Sprint 12 implementation.
- Updated RFC-0003 to accepted for implementation.
- Added Sprint 12-A Learning Memory domain contracts.
- Reused existing `EvidenceRecord` instead of creating a duplicate evidence model.
- Added separate `KnowledgeApproval` and `PolicyApproval` contracts.
- Added approval gates, rollback gates, confidence limits, preference protection, and versioned JSON tests.

## Sprint 11 Development Start

- Added Gaon Development Contract v1.0.
- Added `gaon.learning` package boundary.
- Added Learning Memory, Evidence, Knowledge, Experience, Policy, and Confidence contracts.
- Added tests for evidence requirements, knowledge validation approval, policy rollback metadata, and forbidden autonomous actions.
- Added Sprint 11 Brief, ADR-0001, RFC-0001, Learning Memory guide, and Conversation Engine boundary.
- Updated roadmap terminology from Memory to Learning Memory for Sprint 12 planning.
- Added Research Brain contracts for Research Goal, Plan, Session, Interview, and Journal.
- Hardened Research Brain with explicit session transitions, terminal completed sessions, pending interview answers, and versioned JSON round-trip support.

## v2.0 Foundation Release Candidate

- Added Core foundation.
- Added Market Engine foundation.
- Added Strategy Framework foundation.
- Added Backtest v2 deterministic foundation.
- Added Portfolio Engine foundation.
- Added Risk Engine foundation.
- Added AI Research review contract.
- Added Dashboard view model foundation.
- Added Broker Connector and Paper Trading foundation.
- Added release verification script and documentation.
# Sprint 48

- Added deterministic approved Champion strategy handoff packages.
- Added handoff approval/rejection persistence and CLI inspection commands.
- Added v19 runtime schema tables for handoff packages and approvals.

# Sprint 49

- Added approval-gated strategy deployment workflow.
- Added fake and local-safe deployment adapters.
- Added v20 runtime schema tables for deployment requests, runs, and backups.

# Sprint 50

- Added Gaon v5.0 Release Candidate pipeline orchestration.
- Added v21 pipeline run/checkpoint persistence and resume-safe approval waits.
- Added v5 CLI inspection and release-check commands.
- Added release, recovery, and VPS upgrade documentation.

# Sprint 50 Hotfix

- Made `v5-demo --dry-run` repeatable on persistent SQLite runtime databases.
- Namespaced demo-created IDs by run id without weakening existing uniqueness constraints.

# Sprint 61-70

- Added fixture-backed external web research foundation with normalized citations, freshness, trust metadata, and SSRF protections.
- Added read-only structured data tools for weather, exchange rates, market data, news search, and web search.
- Extended bounded agent planning to select external read-only research tools.
- Added strategy research planning, challenger experiment creation, deterministic fixture backtest, validation, Champion comparison, and advisory report generation.
- Added v28 runtime schema tables for strategy research plans, experiments, and reports.
- Added `external-research-release-check` and `strategy-research-demo` CLI commands.

# Sprint 71-80

- Added AI Quant Researcher foundation with fixture-backed KRX market data, news scoring, theme strength, supply-demand analysis, candidate strategy generation, automated fixture backtests, performance comparison, strategy improvement, evolution, and research reports.
- Added read-only `krx_market_data` Safe Tool.
- Added v29 runtime schema table for quant research reports.
- Added `quant-research-release-check` and `quant-research-demo` CLI commands.

# Sprint 81-90

- Added AI Quant Scientist foundation with feature discovery, feature selection, walk-forward validation, Monte Carlo robustness scoring, market regime detection, meta-strategy selection, portfolio allocation, ensemble decisions, explanations, and scientist reports.
- Added read-only `feature_discovery` Safe Tool with source, trust, and freshness metadata.
- Added v30 runtime schema tables for AI Scientist reports, feature importance, walk-forward windows, and Monte Carlo results.
- Added `feature-discovery-demo`, `feature-discovery-release-check`, `ai-scientist-demo`, and `ai-scientist-release-check` CLI commands.
- Preserved research-only safety boundaries: no orders, no automatic Champion promotion, no approval bypass, and no private repository dependency.

# Hotfix 90.1

- Hardened long Telegram response delivery with `finish_reason=length` truncation detection and bounded provider continuation.
- Raised the default assistant output limit to `2048` tokens and added `GAON_ASSISTANT_MAX_CONTINUATIONS`.
- Replaced Telegram hard slicing with source-preserving chunking below the API limit and visible `[n/m]` ordering.
- Added bounded retry and safe error classification for transient Telegram send failures.
- Added `long-response-release-check` and long-response reliability tests.

# Hotfix 90.2

- Made `long-response-release-check` repeatable on persistent SQLite databases by namespacing each check with a unique run id.
- Preserved schema v30 and Hotfix 90.1 long-response behavior.

# Sprint 91-100

- Added Self-Improving Quant Researcher foundation with deterministic research critique, traceable improvement planning, bounded iteration, lineage tracking, research memory, knowledge relationships, novelty detection, quality scoring, tournaments, and autonomous research orchestration.
- Added v31 runtime schema tables for research memories, lineage, critiques, iterations, quality scores, concepts, and concept relationships.
- Added read-only safe tools: `research_memory_search`, `strategy_critique`, `strategy_quality_score`, `research_candidate_compare`, and `research_lineage`.
- Added `research-critic-demo`, `research-memory-demo`, `research-iteration-demo`, `research-tournament-demo`, `autonomous-research-demo`, and `self-improving-research-release-check`.
- Preserved safety boundaries: no source-code self-modification, no shell, no arbitrary SQL, no live order, no automatic Champion promotion, no approval bypass, and no private repository dependency.
