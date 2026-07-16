# ADR-0004: Learning Memory Storage Contract

Status: Accepted  
Date: 2026-07-16  
Sprint: 12  

## Context

Learning Memory must eventually support durable memory, search, filtering, audit logs, versioning, and rollback.

Sprint 12 must not implement a real database or vector database.

## Decision

Define a storage contract first.

The initial implementation will use deterministic in-memory repositories for tests only. Durable database and vector database backends are postponed until the contracts, fixtures, and migration rules are stable.

## Contract

The storage boundary must support:

- create learning record
- reject records without evidence
- detect duplicate candidates
- detect conflicting claims
- list records chronologically
- filter by project, strategy, and market
- filter by scope and record type
- retrieve related memories for a research plan
- append audit events
- query audit events by target and action
- export/import versioned repository JSON
- restore a prior policy revision through rollback metadata

Related memory retrieval ranking must evaluate:

- scope match
- project/strategy/market match
- evidence quality
- validation state
- recency
- conflict state
- revalidation status

Confidence can help sort results, but it cannot approve knowledge, apply policy, or change user preferences.

Sprint 12 runtime implementation uses `InMemoryLearningRepository` only. It is a deterministic contract/runtime for tests and research preparation, not a durable database.

## Non-Goals

- no SQLite/PostgreSQL implementation
- no vector DB
- no external embedding provider
- no AI provider call
- no Telegram/Dashboard integration

## Consequences

The first Sprint 12 implementation can be tested without infrastructure and later replaced by persistent storage without changing the domain contract.
