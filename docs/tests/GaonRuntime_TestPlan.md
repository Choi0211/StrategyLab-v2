# Gaon Runtime Test Plan

## Unit

- configuration fail-closed and secret masking
- Windows-safe `Asia/Seoul` default timezone validation
- `UTC` timezone validation
- invalid timezone, boolean, mode, HH:MM, and weekday rejection
- CLI dry-run default and explicit execute flag behavior
- Telegram Bot API client success paths for `getMe`, `getUpdates`, and `sendMessage`
- Telegram HTTP 401, 429, 500, malformed JSON, `ok=false`, timeout, and token masking behavior
- event bus ordering, duplicate rejection, failure isolation
- conversation intents and unknown fallback
- Telegram parsing, authorization, ignored update types, formatting, splitting, chat discovery, smoke-send gates, and offset reporting
- Notion dry-run mapping and idempotency
- notification deduplication
- daily/weekly deterministic reports
- scheduler duplicate run prevention
- Learning Memory claims snapshot and retrieval modes

## Integration

- Telegram status flow
- Telegram fake HTTP discover-chat flow
- Telegram allowed poll-once to sendMessage flow
- Telegram unauthorized poll-once no-send flow
- Telegram long response same-chat flow
- Research completion notification flow
- Daily and weekly report Notion mapping flow
- Repository snapshot and same memory query after import

No tests make real network calls or require real tokens.
