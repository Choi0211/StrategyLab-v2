# Real Research Operations

Run the integrated release check:

```bash
python -m gaon.runtime.cli real-research-integration-release-check --db runtime.sqlite
```

Run the demo:

```bash
python -m gaon.runtime.cli real-research-demo --db runtime.sqlite --symbol 005930
```

The report must identify whether data and backtest output are fixture-backed.
This release defaults to `fixture_backed=true`.
