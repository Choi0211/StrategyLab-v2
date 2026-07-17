# Free-Only Mode

Status: default enabled

Gaon Phase B defaults to free-only operation. The runtime must not require paid providers, live external APIs, private repositories, broker credentials, or production tokens for tests or release verification.

## Environment

```text
GAON_FREE_ONLY_MODE=true
GAON_PAID_PROVIDER_ENABLED=false
GAON_ASSISTANT_ENABLED=false
GAON_ASSISTANT_PROVIDER=deterministic
GAON_DRY_RUN=true
```

If `GAON_FREE_ONLY_MODE=true`, setting `GAON_PAID_PROVIDER_ENABLED=true` is rejected during configuration loading.

## Allowed By Default

- deterministic planner
- fake and local fixture evidence providers
- RSS/Atom provider contract with bounded behavior
- dry-run CLI smoke commands
- SQLite runtime state
- unit and integration tests with fake transports

## Not Enabled By Default

- paid AI provider calls
- live Telegram execution
- Notion mutation
- GitHub mutation
- broker/KIS/MyMoneyGuard access
- live order placement
- automatic approval or policy mutation

## Review Rule

Free-only mode can be relaxed only by explicit future design, review, environment change, and rollback documentation. Confidence scores, evidence counts, or provider output never grant that approval automatically.
