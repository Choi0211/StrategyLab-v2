# Gaon LLM Brain Operations

## CLI Checks

```bash
python -m gaon.runtime.cli assistant-status
python -m gaon.runtime.cli conversation-release-check
python -m gaon.runtime.cli tool-registry-show
python -m gaon.runtime.cli tool-audit-history --db runtime.sqlite
python -m gaon.runtime.cli conversation-status --db runtime.sqlite
```

## Telegram Flow

Telegram update -> persisted offset and duplicate guard -> allowed chat check -> `TelegramConversationAgent` -> `LLMConversationBrain` -> Telegram response.

Dry-run mode does not perform live Telegram side effects.

## Provider Policy

The default provider is deterministic. Network providers are optional and must pass the existing free-only and paid-provider gates. If a provider is unavailable or unsafe, Gaon falls back to deterministic responses and records warnings.

## Unsupported Actions

The conversational release does not execute broker orders, live KIS operations, arbitrary shell commands, arbitrary SQL, secret reads, or automatic approvals.
