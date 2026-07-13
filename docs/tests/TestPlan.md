# StrategyLab v2 Test Plan

Status: Sprint 1

## Unit Tests

Sprint 1 requires:

- import smoke tests
- example config loader tests
- logger initialization tests
- module registry tests
- plugin loader discovery tests

Sprint 1 uses the Python standard library test runner so the foundation can be verified without external dependencies:

```bash
PYTHONPATH=src python -m unittest discover -s tests/unit
```

## Integration Tests

No integration tests are required in Sprint 1.

## Research Validation

Research validation is not applicable in Sprint 1 because no research engine, strategy logic, market data engine, or backtest engine behavior is implemented.

## Secret Check

Every sprint must verify that forbidden secret-bearing files are not tracked.
