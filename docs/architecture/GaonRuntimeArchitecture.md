# Gaon Runtime Architecture

Status: Runtime Collaboration Blueprint  
Branch: feature/gaon-runtime-collaboration

Gaon Runtime connects Conversation, Event Bus, Notification, Reports, Scheduler, Telegram dry-run, and Notion dry-run contracts on top of Research Brain and Learning Memory.

## Principles

- dry-run by default
- no real token required for tests
- no MyMoneyGuard, KIS, broker, trading, vector DB, embedding, or external AI API
- deterministic rule-based behavior
- explicit events and correlation IDs
- no approval side effects from Telegram or Notion

## Components

- `gaon.runtime.config`: environment-backed safe configuration
- `gaon.runtime.events`: immutable event contract
- `gaon.runtime.event_bus`: deterministic in-process event bus
- `gaon.runtime.conversation`: rule-based conversation runtime
- `gaon.runtime.notifications`: notification request/result and deduplication
- `gaon.runtime.reports`: daily report and weekly review contracts
- `gaon.runtime.scheduler`: in-memory due-job calculation
- `gaon.integrations.telegram`: dry-run Telegram contracts and runtime bridge
- `gaon.integrations.notion`: dry-run Notion mapping and sync contracts

## Learning Memory Follow-Up

Repository snapshots now include `records`, `claims`, and `audit_events`.

Related Memory Retrieval supports:

- `STRICT`
- `BROAD`
- `GLOBAL`

Ranking is deterministic rule-based. It does not use vector similarity, embeddings, or external AI ranking.
