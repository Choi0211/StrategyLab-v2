# StrategyLab v2 Test Plan

Status: Sprint 11

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

Sprint 3 adds:

- strategy parameter default tests
- strategy parameter type validation tests
- strategy parameter bounds validation tests
- strategy config round-trip tests
- strategy registry registration tests
- strategy registry duplicate rejection tests
- deterministic signal generation tests
- signal output contract tests

Sprint 4 adds:

- backtest config construction tests
- trade record construction tests
- equity curve record construction tests
- known-scenario runner tests
- deterministic result ID tests
- deterministic trade log tests
- deterministic equity curve tests
- transaction cost tests
- slippage tests

Sprint 5 adds:

- cash ledger debit/credit tests
- position buy/sell/value tests
- portfolio snapshot tests
- allocation target validation tests
- rebalance instruction tests
- fixed quantity sizing tests

Sprint 6 adds:

- max drawdown tests
- exposure tests
- risk score tests
- emergency stop tests
- circuit breaker tests
- ATR position sizing tests

Sprint 7 adds:

- deterministic AI review prompt tests
- AI review result schema validation tests
- fallback review tests

Sprint 8 adds:

- dashboard summary assembly tests
- metric card and table view contract tests

Sprint 9 adds:

- broker order/fill contract tests
- paper broker fill tests
- paper broker rejection tests

Sprint 10 adds:

- release artifact existence tests
- release verification script
- end-to-end integration test
- GitHub Actions verification on Ubuntu and Windows with Python 3.11 and 3.12

Sprint 11 adds:

- Gaon package import smoke test
- Learning Memory evidence requirement tests
- required Learning Memory category tests
- Knowledge lifecycle transition tests
- user approval requirement for `Validated` knowledge
- policy update evidence and rollback tests
- forbidden autonomous action contract tests
- Research Brain import smoke test
- Research Goal evidence and Learning Memory export tests
- Research Plan deterministic construction tests
- Research Session goal/plan matching tests
- Research Interview question/answer alignment tests
- Research Journal immutability and duplicate rejection tests

## Integration Tests

Sprint 11 keeps the existing end-to-end StrategyLab integration test and does not add external-service integration.

## Research Validation

Research validation in Sprint 4 is limited to a known-scenario deterministic fixture. No production research validation is required yet.

## Secret Check

Every sprint must verify that forbidden secret-bearing files are not tracked.
