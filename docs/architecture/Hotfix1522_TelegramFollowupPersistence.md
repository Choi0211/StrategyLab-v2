# Hotfix 152.2 - Telegram Follow-up Persistence and Typo Tolerance

Status: COMPLETE

## Context

Sprint 152 added a deterministic Korean conversational MVP and Hotfix 152.1
made follow-up responses use typed research context instead of unrelated tools.
Production Telegram polling can recreate `TelegramConversationAgent` and
`LLMConversationBrain` between polling ticks, so an in-memory-only context is
not sufficient for real chat follow-ups.

## Root Cause

The Telegram path is:

```text
Telegram update
-> TelegramRuntime
-> TelegramConversationAgent
-> LLMConversationBrain
-> conversational MVP route
-> krx_real_research safe tool
-> deterministic Korean renderer
-> Telegram send
```

`LLMConversationBrain` stored `ConversationalMVPContext` only in
`self._mvp_contexts`. That worked while multiple messages were handled by the
same Brain instance, but a later `telegram-poll-once` or runtime tick can build
a fresh Brain. The subsequent message still has the same Telegram chat/session
key, but the previous research context was no longer in memory.

## Design

Hotfix 152.2 persists context in the existing conversation session metadata:

```text
LLMConversationSession.metadata["conversation_mvp"]
  schema_version
  last_research_context
  last_response_context
```

`last_research_context` contains the authoritative research/comparison state:

- result kind
- symbols
- research result IDs
- rendered deterministic summary
- structured payloads and results
- source metadata
- fixture flag
- quality status
- detail payload
- created/updated timestamps

`last_response_context` records only the last conversational response surface:

- last intent
- bounded last text
- detail level
- route
- updated timestamp

Greeting, help, status, typo, and unknown messages update only
`last_response_context`; they do not erase `last_research_context`. A successful
new single-symbol or comparison analysis replaces `last_research_context`.

## Routing Rules

The deterministic MVP priority is:

```text
explicit new analysis
-> follow-up with persisted research context
-> greeting/help/status
-> authoritative safe tools
-> provider/generic fallback
-> unknown
```

Narrow typo tolerance is applied only to follow-up phrases such as:

- `왜 그절? 판간했어?`
- `왜 그렇게 판단했어?`
- `쉽게 설명해줘`
- `자세히 보여줘`

The typo handling does not expand arbitrary fuzzy matching for research,
orders, approval, shell, SQL, or strategy mutation.

## Grounding Rules

Follow-up responses reuse only the persisted authoritative structured result.
When a comparison has one symbol with `trade_count=1` and another with
`trade_count=0`, Gaon must not claim stable superiority or performance
confidence. Trade-count-zero results are rendered as insufficient for direct
performance evaluation.

## Observability

Context persistence logs structured debug metadata without full user message
content:

- context key hash
- result kind
- renderer/route
- context updated flag

No secrets, full Telegram messages, raw provider reasoning, or private
repository data are logged.

## Tests

Added coverage verifies:

- typo follow-up classification
- explain/simplify/detail routing
- context persistence across recreated Telegram runtime/Brain instances
- unknown/help messages do not erase research context
- comparison follow-ups keep both symbols
- `trade_count=1` versus `trade_count=0` does not produce a false winner
- new release check `gaon-telegram-followup-release-check`

## Release Check

```bash
python -m gaon.runtime.cli gaon-telegram-followup-release-check --db :memory:
```

The check simulates the production-like sequence:

```text
삼성전자와 sk하이닉스 비교해줘
왜 그절? 판간했어?
왜 그렇게 판단했어?
쉽게 설명해줘
자세히 보여줘
```

Each step rebuilds the Telegram agent while reusing the same SQLite runtime
store, proving the context is durable across polling ticks.

## Safety

No schema migration. No live trading. No KIS or broker order. No automatic
Champion promotion. No approval bypass. No strategy configuration mutation.
