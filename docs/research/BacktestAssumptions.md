# Backtest Assumptions

Status: Sprint 4 Foundation

## Explicit Assumptions

Sprint 4 backtests require:

- initial capital
- transaction cost rate
- slippage rate
- quantity per signal

Defaults exist only for the test runner and are visible in `BacktestConfig`.

## Execution Price

Sprint 4 uses close price from the matching market bar.

Buy execution price:

```text
close * (1 + slippage_rate)
```

Sell execution price:

```text
close * (1 - slippage_rate)
```

## Transaction Cost

Transaction cost is:

```text
execution_price * quantity * transaction_cost_rate
```

## Slippage

Slippage amount is:

```text
close * quantity * slippage_rate
```

## Quantity

Sprint 4 uses fixed `quantity_per_signal`.

Position sizing and capital allocation are Sprint 5 responsibilities.

## Determinism

The same dataset, signals, strategy config, and backtest config must produce:

- same result ID
- same trade log
- same equity curve

## Research Validation Boundary

Sprint 4 only validates known deterministic fixtures. Real strategy evaluation begins after portfolio, risk, and later research modules are implemented.

