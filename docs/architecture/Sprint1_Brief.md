# StrategyLab v2 Sprint 1 Brief

Sprint ID: Sprint 1  
Sprint Name: Core Refactoring and Project Foundation  
Status: Planned  
Target Branch: develop-v2  
Repository: Choi0211/StrategyLab-v2  
Date: 2026-07-13  
Depends On: StrategyLab v2 Master Blueprint v2.0-blueprint-002

## 1. Objective

Sprint 1 establishes the public StrategyLab v2 project foundation. The sprint creates the package skeleton, configuration conventions, logger, module discovery boundary, plugin loader foundation, baseline tests, and developer documentation.

This sprint must not implement market data, strategies, backtesting, portfolio accounting, risk models, AI research, broker integration, dashboard, reporting, or notifications beyond empty interfaces or placeholders required to define module boundaries.

## 2. In Scope

- Python project metadata.
- `src/strategylab/` package skeleton.
- Core module directory.
- Empty module packages for planned v2 domains.
- Safe example configuration.
- `.env.example`.
- `.gitignore` review for secrets and logs.
- Configuration loader for example config only.
- Logger initialization.
- Module registry or discovery foundation.
- Plugin loader interface foundation.
- Baseline unit test structure.
- Import smoke tests.
- Config load tests.
- Logger initialization tests.
- Module discovery tests.
- Developer setup documentation.
- Architecture overview documentation update.

## 3. Out of Scope

- Real broker credentials.
- Live trading.
- Paper trading execution.
- Market data download.
- Backtest execution.
- Strategy implementation beyond minimal example stubs.
- AI API calls.
- Dashboard UI.
- Notification delivery.
- Private MyMoneyGuard integration.
- Any secret-bearing config.

## 4. Deliverables

- `pyproject.toml`
- `README.md` update
- `.env.example`
- `config/config.example.yaml`
- `src/strategylab/__init__.py`
- `src/strategylab/core/`
- domain package placeholders:
  - `market`
  - `strategies`
  - `portfolio`
  - `risk`
  - `backtest`
  - `research`
  - `broker`
  - `dashboard`
  - `reports`
  - `notification`
- baseline tests under `tests/unit/`
- `docs/architecture/SystemArchitecture.md`
- `docs/operations/DeveloperSetup.md`
- Sprint 1 test result document

## 5. Acceptance Criteria

- Project imports successfully.
- Config loader reads `config/config.example.yaml`.
- Config loader does not require `.env` or any secret.
- Logger initializes with safe defaults.
- Module discovery returns the expected v2 module list.
- Plugin loader interface exists and is testable without real plugins.
- Tests pass locally.
- No forbidden secret files are added.
- Documentation is updated before sprint closure.
- Commit message references Sprint 1 scope.

## 6. Test Plan

Unit tests:

- `test_import_smoke.py`
- `test_config_loader.py`
- `test_logger.py`
- `test_module_registry.py`
- `test_plugin_loader.py`

Integration tests:

- None required in Sprint 1 unless project bootstrap requires one.

Research validation:

- Not applicable in Sprint 1. Record as `N/A` in test results.

Secret checks:

- Verify `.env`, `.env.*`, `kis_token.json`, runtime logs, account files, and real credential files are absent from Git.
- Verify only `.env.example` and `config.example.yaml` are committed.

## 7. Documentation Plan

Update or create:

- `docs/architecture/SystemArchitecture.md`
- `docs/operations/DeveloperSetup.md`
- `docs/tests/TestPlan.md`
- `docs/tests/TestResults.md`

Documentation must describe:

- Package layout.
- Core module responsibilities.
- Safe config policy.
- How to run tests.
- What Sprint 1 intentionally does not include.

## 8. Commit Plan

Expected commit:

- `feat(v2-core): establish sprint 1 project foundation`

Commit only after:

- Unit tests pass.
- Secret check passes.
- Documentation is updated.

## 9. Known Constraints

- GitHub connector write API currently returns `403 Resource not accessible by integration`.
- Direct Git push currently stalls at authentication.
- Local work can proceed and be committed locally, but remote push requires GitHub/Codex write authentication to be refreshed.

## 10. Sprint 1 Gate Decision

Sprint 1 may begin after this brief is accepted.

Implementation must remain limited to the scope above.

