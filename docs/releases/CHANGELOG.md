# Changelog

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
