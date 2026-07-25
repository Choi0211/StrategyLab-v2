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

Expected safety posture:

- no live trading
- no broker order
- no automatic Champion promotion
- no approval bypass
- no arbitrary shell or SQL
- no private repository dependency
