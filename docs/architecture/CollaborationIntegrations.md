# Collaboration Integrations

Status: Dry-Run Contracts

Telegram and Notion are collaboration views over Gaon's source state. They are not source-of-truth systems.

## Telegram

Telegram integration provides:

- update payload parsing
- allowed chat ID authorization
- message formatting and splitting
- Conversation Runtime bridge
- dry-run response contracts

No network call is made in unit or integration tests.

## Notion

Notion integration provides:

- research and learning-memory mapping contracts
- daily and weekly report payload mapping
- idempotency keys
- dry-run sync result

Notion failure must not mutate Research Brain or Learning Memory source state.
