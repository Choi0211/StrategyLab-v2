# Backtest Engine

Status: Sprint 4 Foundation

## Purpose

The Backtest Engine converts market data and strategy signals into deterministic research artifacts.

Sprint 4 implements the contract and a simple deterministic runner only. Full portfolio accounting, risk scoring, optimization, walk-forward, and Monte Carlo behavior are later sprint responsibilities.

## Input Contracts

The Sprint 4 runner accepts:

- `MarketDataset`
- tuple of `Signal`
- `StrategyConfig`
- `BacktestConfig`

## BacktestConfig

`BacktestConfig` records:

- initial capital
- transaction cost rate
- slippage rate
- quantity per signal

All values are explicit and validated.

## TradeRecord

Each trade records:

- timestamp
- symbol
- side
- price
- quantity
- fees
- slippage
- reason

## EquityCurvePoint

Each equity point records:

- timestamp
- cash
- holdings value
- total equity
- drawdown

## Result ID

`BacktestResult.result_id` is generated from a stable SHA-256 hash of:

- market bars
- signals
- strategy config
- backtest config

The same inputs produce the same result ID.

## SimpleBacktestRunner

The Sprint 4 runner is intentionally simple:

- processes signals in deterministic timestamp/symbol order
- buys `quantity_per_signal` units for buy signals when cash is available
- sells up to `quantity_per_signal` units for sell signals when holdings exist
- ignores hold signals for trade generation
- applies transaction cost and slippage deterministically
- emits trade log and equity curve

## Non-Goals

Sprint 4 does not implement:

- full Portfolio Engine
- multi-strategy allocation
- position sizing engine
- risk scoring
- real broker integration
- live trading
- optimizer
- production champion selection

