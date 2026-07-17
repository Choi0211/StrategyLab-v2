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

Tests do not require real tokens.
