# Collaboration Integrations

Status: Telegram production smoke connection plus dry-run Notion contracts

Telegram and Notion are collaboration views over Gaon's source state. They are not source-of-truth systems.

## Telegram

Telegram integration provides:

- standard-library Telegram Bot API client
- `getMe`, `getUpdates`, `sendMessage`, `deleteWebhook`, and `getWebhookInfo` operations
- update payload parsing
- allowed chat ID authorization
- message formatting and splitting
- Conversation Runtime bridge
- one-shot smoke CLI commands
- dry-run response contracts and fake-transport tests

Production Telegram execution is fail-closed behind `GAON_RUNTIME_MODE=execute`, `GAON_DRY_RUN=false`, `GAON_TELEGRAM_ENABLED=true`, a bot token, and explicit `--execute`. Message sending also requires `GAON_TELEGRAM_ALLOWED_CHAT_IDS`.

No real network call is made in unit or integration tests.

## Notion

Notion integration provides:

- research and learning-memory mapping contracts
- daily and weekly report payload mapping
- idempotency keys
- dry-run sync result

Notion failure must not mutate Research Brain or Learning Memory source state.
