# StrategyLab v2 Sprint 4 Brief

Sprint ID: Sprint 4  
Sprint Name: Backtest v2  
Status: Planned  
Target Branch: develop-v2  
Repository: Choi0211/StrategyLab-v2  
Date: 2026-07-14  
Depends On: Sprint 3 Strategy Framework

## 1. Objective

Sprint 4 creates the deterministic backtest foundation for StrategyLab v2. It defines canonical backtest inputs and outputs, trade records, equity curve records, and a simple deterministic runner that converts strategy signals into research artifacts.

This sprint creates the backtest contract. It does not implement the full Portfolio Engine, Risk Engine, optimizer, live trading, or broker integration.

## 2. In Scope

- Backtest configuration model.
- Backtest result model.
- Trade record model.
- Equity curve record model.
- Backtest runner interface.
- Deterministic simple backtest runner.
- Transaction cost parameter.
- Slippage parameter.
- Initial capital handling.
- Trade log generation.
- Equity curve generation.
- Backtest result ID derived from deterministic inputs.
- Known-scenario unit fixture.
- Documentation for backtest assumptions and result schema.

## 3. Out of Scope

- Full portfolio accounting engine.
- Multi-strategy portfolio allocation.
- Position sizing engine.
- Risk scoring.
- Walk-forward implementation beyond placeholder contracts.
- Monte Carlo implementation beyond placeholder contracts.
- Grid search implementation beyond placeholder contracts.
- Broker integration.
- Live trading.
- AI review.
- Dashboard UI.

## 4. Deliverables

- `src/strategylab/backtest/models.py`
- `src/strategylab/backtest/runner.py`
- `src/strategylab/backtest/workflows.py`
- updated `src/strategylab/backtest/__init__.py`
- `tests/unit/test_backtest_models.py`
- `tests/unit/test_backtest_runner.py`
- `tests/unit/test_backtest_determinism.py`
- `docs/architecture/BacktestEngine.md`
- `docs/research/BacktestAssumptions.md`
- updated `docs/tests/TestPlan.md`
- updated `docs/tests/TestResults.md`

## 5. Acceptance Criteria

- Same dataset, strategy config, and backtest config produce the same result ID.
- Same inputs produce identical trades and equity curve.
- Trade records include timestamp, symbol, side, price, quantity, fees, slippage, and reason.
- Equity curve records include timestamp, cash, holdings value, total equity, and drawdown.
- Initial capital is respected.
- Transaction cost and slippage are applied deterministically.
- Known-scenario fixture passes.
- Unit tests pass.
- Secret check passes.
- Documentation is updated.

## 6. Test Plan

Unit tests:

- Backtest config construction.
- Trade record construction.
- Equity curve record construction.
- Known-scenario runner output.
- Deterministic result ID.
- Deterministic trade log.
- Deterministic equity curve.
- Transaction cost application.
- Slippage application.

Integration tests:

- Not required in Sprint 4.

Research validation:

- Limited to known-scenario deterministic fixture. No real strategy research validation is required in Sprint 4.

Secret checks:

- Verify no `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, real data dumps, or log files are tracked.

## 7. Documentation Plan

Create:

- `docs/architecture/BacktestEngine.md`
- `docs/research/BacktestAssumptions.md`

Update:

- `docs/tests/TestPlan.md`
- `docs/tests/TestResults.md`

Documentation must describe:

- backtest input contract
- backtest result schema
- trade log schema
- equity curve schema
- deterministic assumptions
- what Sprint 4 intentionally excludes

## 8. Commit Plan

Expected commit sequence:

1. `docs(v2): define sprint 4 backtest scope`
2. `feat(v2-backtest): add deterministic backtest foundation`

The first commit covers Sprint 4 planning. The second commit should happen only after implementation, tests, and documentation are complete.

## 9. Known Constraints

- Sprint 4 must not implement full portfolio/risk behavior.
- Sprint 4 must not connect to brokers.
- Backtest output must remain deterministic for identical inputs.
- Public repository must not include secrets or real account data.

## 10. Sprint 4 Gate Decision

Sprint 4 implementation may begin after this brief is accepted.

Implementation must remain limited to the scope above.

