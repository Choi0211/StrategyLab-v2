# Runtime Configuration

Gaon Runtime uses environment variables and defaults to dry-run.

See `.env.example` for the complete list.

Secrets must not be committed. Runtime repr masks token values.

## Supported Timezones

Current supported timezone values are:

- `UTC`
- `Asia/Seoul`

This phase does not claim general IANA timezone support. `UTC` uses `datetime.timezone.utc`; `Asia/Seoul` uses a fixed UTC+09:00 fallback so Windows runners without IANA tzdata still validate the default configuration. Any other timezone string fails closed with `ConfigurationError`.

## Validation

- `GAON_RUNTIME_MODE` must be `dry-run` or `execute`.
- Boolean values must be one of `true/false`, `yes/no`, `on/off`, or `1/0`.
- `GAON_DAILY_REPORT_TIME` and `GAON_WEEKLY_REPORT_TIME` must use `HH:MM`.
- `GAON_WEEKLY_REPORT_DAY` must be a valid English weekday name.
- Unknown scalar values fail closed with `ConfigurationError`.
- CLI commands default to dry-run. `--dry-run` and `--execute` are mutually exclusive where present.

Required execute-mode conditions:

- integration enabled explicitly
- token provided through environment
- dry-run disabled explicitly
- execute mode selected explicitly
- `GAON_APPROVAL_SIGNING_SECRET` provided through environment

Telegram message execution also requires `GAON_TELEGRAM_ALLOWED_CHAT_IDS`. The only exception is `telegram-discover-chat --execute`, which exists to discover the first private chat ID and never sends a Telegram message.

Tests do not require real tokens.

## Telegram Production Smoke Commands

Dry-run remains the default:

```powershell
py -3.11 -m gaon.runtime.cli telegram-poll-once
```

Production smoke commands require all gates:

```powershell
$env:GAON_RUNTIME_MODE = "execute"
$env:GAON_DRY_RUN = "false"
$env:GAON_TELEGRAM_ENABLED = "true"
$env:GAON_TELEGRAM_BOT_TOKEN = "<private-token>"
$env:GAON_APPROVAL_SIGNING_SECRET = "<private-approval-signing-secret>"
py -3.11 -m gaon.runtime.cli telegram-get-me --execute
```

The project does not auto-load `.env` and does not add `python-dotenv`. Keep secrets outside Git and inject them through the operating environment.

## Runtime State

Sprint 19 stores operational runtime state through repository interfaces over SQLite schema v2. The database may contain Telegram offsets, processed message IDs, scheduler job state, research proposals, approvals, runs, audit events, and notification delivery attempts. It must not contain tokens, API keys, account IDs, or private trading state.

Sprint 18 approval security stores only HMAC-SHA256 approval token digests. Raw approval tokens must not be stored in SQLite, logs, audit payloads, fixtures, or exceptions. Approval consumption is single-use and binds the approval to the target run.

Schema v1 databases are migrated in place to v2 without deleting existing offsets, processed message IDs, proposals, approvals, runs, audit events, or notification attempts. Unsupported schema versions fail closed.

Health commands:

```powershell
py -3.11 -m gaon.runtime.cli health --db runtime.sqlite
py -3.11 -m gaon.runtime.cli readiness --db runtime.sqlite
py -3.11 -m gaon.runtime.cli db-check --db runtime.sqlite
```
