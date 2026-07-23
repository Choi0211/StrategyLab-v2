# Backtest Contract

Sprint 105 defines a versioned JSON contract for external backtest engines.

Request models:

- `BacktestRequest`
- `BacktestStrategySpec`
- `BacktestDatasetReference`
- `BacktestExecutionAssumptions`

Result models:

- `BacktestResult`
- `BacktestMetrics`
- `BacktestTrade`
- `BacktestEquityPoint`

The reproducibility fingerprint includes strategy specification, dataset
fingerprint, cost assumptions, engine version, and request version.
