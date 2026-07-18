# Conversation Runtime

Status: Sprint 13 deterministic conversational foundation

Conversation Runtime receives source messages and returns deterministic Korean responses. It supports slash commands and ordinary Korean text without requiring an LLM provider.

Sprint 51-55 adds `LLMConversationBrain` for persistent sessions, bounded contextual memory orchestration, read-only safe tool calls, and Telegram conversation routing. The default route remains deterministic and free-only unless an explicitly configured provider passes the Provider Registry gates.

## Persona

- Always address the user as `영하님`.
- Use polite Korean.
- Stay calm, professional, and evidence-oriented.
- Do not guess unknown facts.
- Do not claim that disconnected systems were queried or executed.
- Do not place investment orders or perform automatic approvals.

## Supported Intents

- GREETING
- CALL_GAON
- HELP
- STATUS
- TODAY_PLAN
- MARKET_STATUS
- STOCK_ANALYSIS
- SCHEDULE
- BACKTEST
- RECENT_RESEARCH
- SEARCH_MEMORY
- RESEARCH_STATUS
- CONFLICTS
- DUPLICATES
- REVALIDATION_DUE
- DAILY_REPORT
- WEEKLY_REVIEW
- SYNC_NOTION
- APPROVAL_STATUS
- UNKNOWN

Specific intents are checked before broad intents. For example, `오늘 시장 어때?` maps to MARKET_STATUS, while the single word `오늘` remains UNKNOWN.

## Provider Boundary

`AssistantProvider` is a Protocol boundary for future OpenAI or local LLM integrations. Sprint 13 does not implement a network provider, add external SDK dependencies, or require API keys. When no provider is configured, Conversation Runtime uses deterministic `rule_based` responses.

Responses include a `route` field so callers can distinguish `rule_based` and future `provider` responses without breaking existing response fields.

## Memory Context

Sprint 14 adds optional memory context. Conversation Runtime calls the context builder only for research and memory intents, then appends a read-only summary to the persona response. The route records this as `rule_based+context`.

The context layer uses Learning Memory retrieval only. It does not save records, validate claims, resolve conflicts, or treat confidence as approval.

## Current Limitations

- No real LLM connection.
- No market data feed.
- No calendar or schedule provider.
- No stock analysis engine.
- No backtest executor from Telegram conversation.
- No automatic Learning Memory retrieval in the response path.

The assistant can understand these requests and explain the current connection state, but it must not fabricate results.

## Safety

Conversation Runtime does not:

- approve knowledge
- apply policy
- change user preferences
- execute research automatically
- execute shell or arbitrary code
- place trades
- mutate GitHub or repositories
- access private projects or private runtime data

Approval, order, and execution-like requests return an approval-required safety boundary and remain candidates for a future explicit approval runtime.
