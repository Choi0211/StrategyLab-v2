# Telegram Setup

Status: production smoke connection with fail-closed execution gates.

This integration connects Gaon Runtime to the Telegram Bot API for research conversation smoke tests only. It cannot approve, trade, run shell commands, mutate GitHub, change policies, or access MyMoneyGuard.

## Safety Boundary

- Do not commit real bot tokens.
- Do not commit `.env` files.
- Do not paste token values into docs, tests, logs, issues, or pull requests.
- Unit and integration tests use fake HTTP clients and make no real Telegram network calls.
- The repository does not auto-load `.env`; inject environment variables from PowerShell, bash, or a private operations script.
- This phase supports one-shot commands only. It does not implement a daemon, webhook server, infinite polling loop, or offset persistence store.

## Setup Flow

1. Create a bot in BotFather.
2. Send a first private message to the bot.
3. Set runtime environment variables locally.
4. Run `config-check`.
5. Run `telegram-get-me`.
6. Run `telegram-discover-chat`.
7. Add the discovered chat ID to `GAON_TELEGRAM_ALLOWED_CHAT_IDS`.
8. Run `telegram-send-smoke`.
9. Run `telegram-poll-once`.
10. Return to dry-run mode when smoke testing is complete.

## Windows PowerShell Example

```powershell
$env:GAON_RUNTIME_MODE = "execute"
$env:GAON_DRY_RUN = "false"
$env:GAON_TELEGRAM_ENABLED = "true"
$env:GAON_TELEGRAM_BOT_TOKEN = "<set-private-token-outside-repo>"

py -3.11 -m gaon.runtime.cli config-check
py -3.11 -m gaon.runtime.cli telegram-get-me --execute
py -3.11 -m gaon.runtime.cli telegram-discover-chat --execute

$env:GAON_TELEGRAM_ALLOWED_CHAT_IDS = "<discovered-chat-id>"
py -3.11 -m gaon.runtime.cli telegram-send-smoke --execute --chat-id <discovered-chat-id>
py -3.11 -m gaon.runtime.cli telegram-poll-once --execute
```

To continue from a known Telegram offset:

```powershell
py -3.11 -m gaon.runtime.cli telegram-poll-once --execute --offset 123456
```

Return to dry-run:

```powershell
$env:GAON_RUNTIME_MODE = "dry-run"
$env:GAON_DRY_RUN = "true"
```

## Linux/macOS Bash Example

```bash
export GAON_RUNTIME_MODE="execute"
export GAON_DRY_RUN="false"
export GAON_TELEGRAM_ENABLED="true"
export GAON_TELEGRAM_BOT_TOKEN="<set-private-token-outside-repo>"

python3.11 -m gaon.runtime.cli config-check
python3.11 -m gaon.runtime.cli telegram-get-me --execute
python3.11 -m gaon.runtime.cli telegram-discover-chat --execute

export GAON_TELEGRAM_ALLOWED_CHAT_IDS="<discovered-chat-id>"
python3.11 -m gaon.runtime.cli telegram-send-smoke --execute --chat-id <discovered-chat-id>
python3.11 -m gaon.runtime.cli telegram-poll-once --execute
```

## CLI Commands

- `telegram-get-me --execute`: validates the bot token and prints bot metadata without exposing the token.
- `telegram-discover-chat --execute`: reads recent updates and prints unique private `chat_id` values with a 30-character message preview.
- `telegram-send-smoke --execute --chat-id <ID>`: sends the fixed smoke message only when `<ID>` is allowlisted.
- `telegram-poll-once --execute [--offset N]`: processes pending private text messages once and prints `next_offset` for the next manual run.

`telegram-discover-chat` is allowed to run without `GAON_TELEGRAM_ALLOWED_CHAT_IDS` because its purpose is chat ID discovery. `telegram-send-smoke` and `telegram-poll-once` require an allowlist.

## Supported Messages

Private text messages are passed to Conversation Runtime. The current supported commands are:

- `/start`
- `/help`
- `/status`
- `/today`
- `/research`
- `/memory ORB`
- `/conflicts`
- `/revalidate`
- `/daily`
- `/weekly`
- `/approvals`

Unsupported updates such as edited messages, channel posts, callback queries, group messages, missing text, and malformed update IDs are ignored or rejected without sending arbitrary responses.

## Conversational Assistant

Sprint 13 adds deterministic Korean natural-language handling. The same Telegram path now supports examples such as:

- `안녕`
- `가온`
- `도움말`
- `상태 알려줘`
- `오늘 뭐부터 할까?`
- `오늘 시장 어때?`
- `삼성전자 분석해줘`
- `오늘 일정 알려줘`
- `백테스트 돌려줘`
- `지난 연구 알려줘`

The assistant explains disconnected capabilities instead of pretending to execute them. Real LLM providers, market data, schedules, stock analysis, and Telegram-triggered backtest execution remain separate future connections.

## Durable Offset State

Sprint 17 adds SQLite runtime state for processed message IDs and Telegram update offsets. This prevents duplicate processing after restart when the production service uses the runtime store. The database must not store bot tokens or raw secret-bearing payloads.
