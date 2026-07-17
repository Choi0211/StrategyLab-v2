# Changelog

## Sprint 30 Validated Research Planning

- Added bounded ResearchRequest, ResearchPlan, and ResearchStep contracts.
- Added deterministic planner with stable plan hash and plan lifecycle event support.
- Added allowlisted research step types, dependency validation, cycle rejection, and step limit enforcement.
- Added optional provider-backed planner with free-only enforcement and structured output validation.
- Added planner metrics coverage.

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
