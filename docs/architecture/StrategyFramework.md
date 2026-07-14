# Strategy Framework

Status: Sprint 3 Foundation

## Purpose

The Strategy Framework defines how StrategyLab v2 strategies are described, configured, registered, and asked to produce deterministic signal records.

Sprint 3 provides the contract only. It does not run backtests, choose champions, size positions, or execute trades.

## Core Contracts

### StrategyMetadata

Every strategy declares:

- `name`
- `version`
- `description`
- `author`

The strategy name is the registry key.

### ParameterDefinition

Each parameter declares:

- name
- type
- default
- optional minimum
- optional maximum
- description

Supported parameter types:

- integer
- float
- string
- boolean

### ParameterSchema

`ParameterSchema` validates user-provided values, applies defaults, rejects unknown parameters, and rejects invalid types or bounds.

### StrategyConfig

`StrategyConfig` is the serializable strategy run configuration:

- strategy name
- strategy version
- validated parameter values

It supports dictionary export/import for later experiment tracking.

### Signal

`Signal` is the canonical strategy output record:

- symbol
- timestamp
- signal type
- strength
- reason
- strategy name

Signal types:

- buy
- sell
- hold

Strength must be between `0.0` and `1.0`.

## Registry

`StrategyRegistry` registers strategy classes by metadata name.

Rules:

- duplicate registration is rejected
- unknown lookup raises an error
- registration does not run backtests or import private code

## Example Strategy

`CloseAboveThresholdStrategy` is a deterministic Sprint 3 fixture strategy.

It emits:

- `buy` when close is greater than or equal to threshold
- `hold` otherwise

This is not a production trading strategy. It exists to verify the strategy contract.

## Non-Goals

Sprint 3 does not implement:

- backtest execution
- portfolio accounting
- position sizing
- risk scoring
- walk-forward validation
- Monte Carlo validation
- grid search
- champion approval
- live trading
- broker integration
- AI strategy generation

