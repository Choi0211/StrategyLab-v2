# Telegram Setup

Status: production smoke connection with fail-closed execution gates.

This integration connects Gaon Runtime to the Telegram Bot API for research conversation smoke tests only. It cannot approve, trade, run shell commands, mutate GitHub, change policies, or access MyMoneyGuard.

## Safety Boundary

- Do not commit real bot tokens.
- Do not commit `.env` files.
- Do not paste token values into docs, tests, logs, issues, or pull requests.
- Unit and integration tests use fake HTTP clients and make no real Telegram network calls.
- The repository does not auto-load `.env`; inject environment variables from PowerShell, bash, or a private operations script.
- `telegram-poll-once` persists the next Telegram offset and processed message IDs in the existing SQLite runtime store to prevent duplicate replies across repeated manual runs.
- The persistent runtime command `gaon.runtime.cli run --db <path>` reuses the same poll path under `GaonRuntimeService` when execute gates are enabled. It is a bounded polling loop, not a webhook server.

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
10. For 24/7 operation, run `gaon.runtime.cli run --db <path>` under systemd.
11. Return to dry-run mode when smoke testing is complete.

## Conversational MVP Smoke Prompts

Sprint 152 supports deterministic Korean conversational routing for common
research prompts. After deployment and import-path verification, test:

- `안녕하세요`
- `삼성전자 분석해줘`
- `삼성전자와 SK하이닉스 비교해줘`
- `왜 그렇게 판단했어?`
- `쉽게 설명해줘`
- `자세히 보여줘`

The final Telegram response must be Korean, must not expose raw JSON or
internal IDs, and must not fabricate metrics outside structured safe-tool
output. If one symbol in a comparison fails, Gaon must say the comparison is
partial instead of ranking the successful symbol alone.

Release check:

```bash
python -m gaon.runtime.cli gaon-conversation-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

Hotfix 152.1 follow-up context release check:

```bash
python -m gaon.runtime.cli gaon-conversation-context-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

This check verifies that follow-up prompts such as `왜 그렇게 판단했어?`,
`쉽게 설명해줘`, and `자세히 보여줘` use the prior research result from the
same Telegram chat only. A missing-context follow-up must not call unrelated
status, history, Champion, or pipeline tools.

Hotfix 152.2 persistent Telegram follow-up release check:

```bash
python -m gaon.runtime.cli gaon-telegram-followup-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

This check simulates separate Telegram polling ticks by recreating the runtime
agent for each message while reusing the same SQLite store. The sequence is:

- `삼성전자와 sk하이닉스 비교해줘`
- `왜 그절? 판간했어?`
- `왜 그렇게 판단했어?`
- `쉽게 설명해줘`
- `자세히 보여줘`

All follow-ups must use the prior comparison context from the same chat. The
response must not claim a stable winner when one symbol has only one trade and
the other has zero trades, and it must not fall back to Champion, V5, market
condition speculation, or fixture context.

Hotfix 152.3 result presentation release check:

```bash
python -m gaon.runtime.cli gaon-result-presentation-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

This check verifies that Telegram-facing research responses preserve metric
units, render expectancy as a capital-denominated amount, hide internal
fingerprints and raw provenance keys, use Korean data-quality/source labels, and
deduplicate warning prefixes.

Sprint 153 conversational reasoning release check:

```bash
python -m gaon.runtime.cli gaon-conversational-reasoning-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

This check verifies evidence-bound follow-up explanations for prompts such as:

- `삼성전자 지금 사도 돼?`
- `위험은 어느 정도야?`
- `쉽게 설명해줘`
- `전문적으로 설명해줘`
- `3년 기간으로 다시 해줘`

Gaon must not expose hidden chain-of-thought, must not recommend buying or
selling from insufficient evidence, and must not rerun or mutate strategy
parameters without an explicit authoritative request.

Sprint 154 natural conversation release check:

```bash
python -m gaon.runtime.cli gaon-natural-conversation-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

This check verifies presentation-only follow-ups such as:

- `한 줄로 말해줘`
- `비유해서 설명해줘`
- `예를 들어 설명해줘`
- `전문적으로 설명해줘`
- `전문용어 빼줘`

Gaon must reuse the same-chat research evidence, must not run the research tool
again for presentation-only requests, must keep internal metadata hidden, and
must not fabricate investment recommendations or unsupported performance
figures.

Hotfix 154.1 presentation integrity release check:

```bash
python -m gaon.runtime.cli gaon-presentation-integrity-release-check --db /var/lib/strategylab/gaon-runtime.sqlite
```

This check verifies the production-style sequence:

- `삼성전자 분석해줘`
- `지금 사도 돼?`
- `한 줄로 말해줘`
- `비유해서 설명해줘`
- `예를 들어 설명해줘`
- `전문적으로 설명해줘`
- `전문용어 빼줘`
- `조금 더 짧게`
- `자세히 보여줘`

The final answers must preserve authoritative source and quality metadata, must
not combine multiple renderer outputs into one response, must not rerun the
research tool for presentation-only follow-ups, and must not expose unsupported
unknown-source wording.

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
py -3.11 -m gaon.runtime.cli telegram-poll-once --execute --db runtime.sqlite
py -3.11 -m gaon.runtime.cli run --once --db runtime.sqlite
```

To continue from a known Telegram offset:

```powershell
py -3.11 -m gaon.runtime.cli telegram-poll-once --execute --offset 123456
```

When `--offset` is provided, it takes precedence over the saved SQLite offset for that poll. After processing, the highest safe `next_offset` is still persisted.

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
python3.11 -m gaon.runtime.cli telegram-poll-once --execute --db runtime.sqlite
python3.11 -m gaon.runtime.cli run --once --db runtime.sqlite
```

## CLI Commands

- `telegram-get-me --execute`: validates the bot token and prints bot metadata without exposing the token.
- `telegram-discover-chat --execute`: reads recent updates and prints unique private `chat_id` values with a 30-character message preview.
- `telegram-send-smoke --execute --chat-id <ID>`: sends the fixed smoke message only when `<ID>` is allowlisted.
- `telegram-poll-once --execute [--db runtime.sqlite] [--offset N]`: processes pending private text messages once, skips already processed messages, persists the highest safe `next_offset`, and prints poll results. If `--offset` is omitted, the saved SQLite offset is used.
- `run --db runtime.sqlite`: starts the persistent Gaon runtime. When `GAON_RUNTIME_MODE=execute`, `GAON_DRY_RUN=false`, and `GAON_TELEGRAM_ENABLED=true`, each service tick performs bounded Telegram polling through the same SQLite state.
- `run --once --db runtime.sqlite`: executes exactly one bounded runtime tick and exits. Use this for smoke tests and systemd validation without starting a long-running process.

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

Sprint 51-55 adds persistent conversational Telegram routing for ordinary Korean text. It reuses the same runtime SQLite database for offsets, processed messages, conversation sessions, and Telegram conversation links.

## Durable Offset State

Sprint 17 adds SQLite runtime state for processed message IDs and Telegram update offsets. The hotfix poll path now uses the same store for `telegram-poll-once` and the persistent runtime worker, so repeated CLI executions and service restarts do not reply to the same update twice. Ignored and unauthorized updates also advance offset safely when their Telegram update IDs are valid. The database must not store bot tokens or raw secret-bearing payloads.

## systemd Runtime

`deploy/systemd/strategylab-gaon.service` runs:

```text
/opt/strategylab-v2/.venv/bin/python -m gaon.runtime.cli run --db /var/lib/strategylab/gaon-runtime.sqlite
```

The environment file remains outside Git at `/etc/strategylab/gaon.env`. The service file contains no token, chat ID, approval secret, KIS credential, broker credential, or MyMoneyGuard path. Stop and restart are handled through the runtime service shutdown path; offsets are committed after each processed Telegram update.
