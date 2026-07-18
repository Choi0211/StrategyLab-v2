# Validation Policy Operations

Status: Sprint 42

Use validation after a normalized backtest result exists.

## CLI

```powershell
py -3.11 -m gaon.runtime.cli validation-policy-show
py -3.11 -m gaon.runtime.cli validation-run --db runtime.sqlite --backtest-id backtest-result:<fingerprint>
py -3.11 -m gaon.runtime.cli validation-run --db runtime.sqlite --fingerprint <fingerprint>
py -3.11 -m gaon.runtime.cli validation-show --db runtime.sqlite validation:backtest-result:<fingerprint>
py -3.11 -m gaon.runtime.cli validation-history --db runtime.sqlite
```

CLI smoke uses local SQLite state only. It does not require a private v1 repository, live market data, Telegram, MyMoneyGuard, broker credentials, KIS credentials, Ollama, paid AI APIs, or network access.

## Result Meaning

- `PASS`: validation rules are satisfied.
- `FAIL`: at least one hard-fail rule failed.
- `REVIEW`: no hard-fail rule failed, but available evidence is incomplete or weak.

`PASS` is a research validation result only. It does not automatically promote, deploy, trade, or approve a strategy.

## MDD

Maximum drawdown is normalized internally to a positive fraction:

- `-0.20` -> `0.20`
- `0.20` -> `0.20`
- `20.0` -> `0.20`

Values outside the supported range are rejected instead of silently reinterpreted.
