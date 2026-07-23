# External Backtest Operations

Run the JSON contract demo:

```bash
python -m gaon.runtime.cli backtest-contract-demo --db runtime.sqlite --symbol 005930
```

Run the deterministic external adapter demo:

```bash
python -m gaon.runtime.cli external-backtest-demo --db runtime.sqlite --symbol 005930
```

The current public implementation is fixture-backed and does not invoke a
private engine. Future v1 integration should exchange `BacktestRequest` JSON
and `BacktestResult` JSON at this boundary.
