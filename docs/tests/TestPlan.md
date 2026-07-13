# StrategyLab v2 Test Plan

Status: Sprint 2

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

Sprint 2 adds:

- market model construction tests
- provenance construction tests
- validation pass for valid fixture
- validation failure for missing values
- validation failure for duplicate timestamps
- validation failure for empty dataset
- validation failure for symbol mismatch
- validation failure for date range mismatch
- validation failure for invalid OHLC
- validation failure for negative volume
- in-memory adapter retrieval tests
- in-memory adapter date filtering tests

## Integration Tests

No integration tests are required in Sprint 2.

## Research Validation

Research validation is not applicable in Sprint 2 because no strategy or backtest behavior is implemented.

## Secret Check

Every sprint must verify that forbidden secret-bearing files are not tracked.
