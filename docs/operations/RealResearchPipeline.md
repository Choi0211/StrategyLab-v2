# Real Research Pipeline Operations

Demo:

```bash
python -m gaon.runtime.cli krx-real-research-demo --db runtime.sqlite
```

Release check:

```bash
python -m gaon.runtime.cli krx-real-research-release-check --db runtime.sqlite
```

The check is repeatable on persistent SQLite databases. It creates unique run
IDs, stores source-aware research memory, and produces a Korean report.

When `GAON_REAL_MARKET_DATA_ENABLED=true` and
`GAON_MARKET_DATA_PROVIDER=yahoo-chart`, `krx-real-research-demo` and the
`krx_real_research` safe tool use the real public provider. If the provider is
unavailable, the pipeline fails closed with `real_data_unavailable` instead of
showing fixture results as real research.

Expected safety posture:

- no live trading
- no broker order
- no automatic Champion promotion
- no approval bypass
- no arbitrary shell or SQL
- no private repository dependency
