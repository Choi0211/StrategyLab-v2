# Strategy Authoring Guide

Status: Sprint 3 Foundation

## Strategy Authoring Flow

To add a StrategyLab v2 strategy, define:

1. metadata
2. parameter schema
3. deterministic signal generation
4. unit tests
5. documentation

## Minimal Strategy Shape

```python
class MyStrategy(Strategy):
    metadata = StrategyMetadata(name="my_strategy", version="0.1.0")
    parameter_schema = ParameterSchema(definitions=(...))

    def generate_signals(self, dataset, config):
        parameters = self.parameter_schema.validate(config.parameters)
        ...
```

## Parameter Rules

Parameters must:

- have explicit defaults
- have explicit types
- define min/max bounds where meaningful
- be validated before signal generation

Unknown parameters are rejected.

## Signal Rules

Signals must:

- be deterministic for the same dataset and config
- include symbol
- include timestamp
- include signal type
- include strength between `0.0` and `1.0`
- include a human-readable reason
- include strategy name

## Public Repository Rule

Strategies must not:

- import private MyMoneyGuard code
- read `.env`
- read broker tokens
- read account files
- place orders
- mutate live state

## Sprint 3 Boundary

Sprint 3 strategies generate signals only. Backtest interpretation, order simulation, position sizing, risk scoring, and champion selection are later sprint responsibilities.

