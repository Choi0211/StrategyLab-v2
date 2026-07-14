# StrategyLab v2 Sprint 3 Brief

Sprint ID: Sprint 3  
Sprint Name: Strategy Framework  
Status: Planned  
Target Branch: develop-v2  
Repository: Choi0211/StrategyLab-v2  
Date: 2026-07-14  
Depends On: Sprint 2 Market Engine

## 1. Objective

Sprint 3 creates the strategy definition framework for StrategyLab v2. It defines how strategies describe metadata, validate parameters, register with the platform, and produce deterministic signal records from market datasets.

This sprint creates the strategy contract. It does not implement full trading systems, optimizers, backtests, portfolio accounting, or champion approval.

## 2. In Scope

- Strategy metadata model.
- Strategy parameter schema.
- Supported parameter types.
- Parameter validation.
- Strategy configuration model.
- Strategy interface.
- Strategy registry.
- Signal model.
- Signal output contract.
- Example deterministic strategy stub.
- Strategy config export/import round trip.
- Unit tests for registry, parameter validation, signal determinism, and config serialization.
- Strategy framework documentation.
- Strategy authoring guide.

## 3. Out of Scope

- Backtest execution.
- Portfolio accounting.
- Position sizing.
- Risk scoring.
- Walk-forward validation.
- Monte Carlo validation.
- Grid search optimization.
- Champion selection.
- Live trading.
- Broker integration.
- AI strategy generation.
- Dashboard UI.

## 4. Deliverables

- `src/strategylab/strategies/models.py`
- `src/strategylab/strategies/parameters.py`
- `src/strategylab/strategies/interface.py`
- `src/strategylab/strategies/registry.py`
- `src/strategylab/strategies/examples.py`
- updated `src/strategylab/strategies/__init__.py`
- `tests/unit/test_strategy_parameters.py`
- `tests/unit/test_strategy_registry.py`
- `tests/unit/test_strategy_config.py`
- `tests/unit/test_strategy_signals.py`
- `docs/architecture/StrategyFramework.md`
- `docs/research/StrategyAuthoring.md`
- updated `docs/tests/TestPlan.md`
- updated `docs/tests/TestResults.md`

## 5. Acceptance Criteria

- A strategy can declare metadata.
- A strategy can declare typed parameters with defaults.
- Invalid parameter values are rejected before signal generation.
- A strategy config can be converted to a dictionary and reconstructed.
- A strategy registry can register and retrieve strategy classes.
- Duplicate strategy registration is rejected.
- Example strategy produces deterministic signals from the same market dataset and config.
- Signal records contain symbol, timestamp, signal type, strength, reason, and strategy name.
- Unit tests pass.
- Secret check passes.
- Documentation is updated.

## 6. Test Plan

Unit tests:

- Parameter schema accepts valid values.
- Parameter schema rejects wrong types.
- Parameter schema rejects values outside min/max bounds.
- Strategy config round trip.
- Strategy registry registration and retrieval.
- Strategy registry duplicate rejection.
- Example strategy signal determinism.
- Signal output contract fields.

Integration tests:

- Not required in Sprint 3.

Research validation:

- Not applicable in Sprint 3 because no backtest or research evaluation behavior is implemented.

Secret checks:

- Verify no `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, real data dumps, or log files are tracked.

## 7. Documentation Plan

Create:

- `docs/architecture/StrategyFramework.md`
- `docs/research/StrategyAuthoring.md`

Update:

- `docs/tests/TestPlan.md`
- `docs/tests/TestResults.md`

Documentation must describe:

- Strategy interface.
- Parameter schema.
- Config serialization.
- Registry behavior.
- Signal output contract.
- What Sprint 3 intentionally excludes.

## 8. Commit Plan

Expected commit sequence:

1. `docs(v2): define sprint 3 strategy framework scope`
2. `feat(v2-strategy): add strategy framework foundation`

The first commit covers Sprint 3 planning. The second commit should happen only after implementation, tests, and documentation are complete.

## 9. Known Constraints

- Sprint 3 must not run backtests or choose champions.
- Strategy behavior must be deterministic for the same input dataset and configuration.
- Strategy classes must not import private MyMoneyGuard code.
- Public repository must not include secrets or real account data.

## 10. Sprint 3 Gate Decision

Sprint 3 implementation may begin after this brief is accepted.

Implementation must remain limited to the scope above.

