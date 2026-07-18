# Gaon LLM Brain Architecture

Status: Sprint 51-55 conversational release

Gaon LLM Brain adds a persistent conversation layer, bounded runtime context, and a safe read-only tool framework on top of the existing StrategyLab runtime. It does not add a required paid provider, vector database, broker connection, live KIS integration, or arbitrary command execution.

## Components

- `LLMConversationBrain`: creates and persists conversation sessions and messages.
- `ConversationContextOrchestrator`: retrieves bounded read-only context from recent conversation, champion registry, validation reports, paper revalidation reports, and v5 pipeline history.
- `SafeToolExecutor`: executes registered read-only tools only and records every request to `llm_tool_audit`.
- `TelegramConversationAgent`: bridges Telegram messages into the persistent conversation brain while preserving allowed-chat, offset, and duplicate protections.

## Storage

- v22: `conversation_sessions`, `conversation_messages`
- v23: `conversation_summaries`
- v24: `llm_tool_audit`
- v25: `telegram_conversation_links`

Unsupported future schema versions fail closed through the existing migration guard.

## Safety Boundaries

- No live trading.
- No automatic approval.
- No shell, SQL, secret, broker, KIS, or order tools.
- Provider failures fall back to deterministic Korean persona responses.
- Telegram duplicate protection remains handled by persisted offsets and processed message keys.

## Current Limitations

The release is a deterministic/free-only conversation foundation. Real LLM provider use remains optional through the existing Provider Registry, and market data, calendar data, stock analysis execution, and backtest execution are still separate integrations.
