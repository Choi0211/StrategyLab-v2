# StrategyLab v2 Sprint 2 Brief

Sprint ID: Sprint 2  
Sprint Name: Market Engine  
Status: Planned  
Target Branch: develop-v2  
Repository: Choi0211/StrategyLab-v2  
Date: 2026-07-14  
Depends On: Sprint 1 Core Refactoring and Project Foundation

## 1. Objective

Sprint 2 builds the market data foundation for StrategyLab v2. The sprint creates data contracts, validation rules, provenance tracking, an in-memory adapter, and sample fixtures that later strategy and backtest sprints can rely on.

This sprint does not connect to real broker APIs or paid market data APIs.

## 2. In Scope

- Market data domain models.
- OHLCV bar representation.
- Market dataset representation.
- Data source metadata.
- Data provenance record.
- Validation result model.
- Market data adapter interface.
- In-memory market data adapter for tests.
- Cache interface boundary.
- Required-column validation.
- Missing-value validation.
- Duplicate timestamp validation.
- Symbol universe validation.
- Date range validation.
- Sample data fixtures for unit tests.
- Market data documentation.
- Data validation documentation.

## 3. Out of Scope

- KIS API connection.
- Kiwoom API connection.
- IBKR API connection.
- Alpaca API connection.
- Live market data download.
- Real account or order data.
- Paid data vendor integration.
- Backtest execution.
- Strategy signal generation.
- Portfolio accounting.
- AI analysis.
- Dashboard UI.
- Notification delivery.

## 4. Deliverables

- `src/strategylab/market/models.py`
- `src/strategylab/market/validation.py`
- `src/strategylab/market/adapters.py`
- `src/strategylab/market/cache.py`
- `tests/unit/test_market_models.py`
- `tests/unit/test_market_validation.py`
- `tests/unit/test_market_adapters.py`
- `docs/architecture/MarketEngine.md`
- `docs/research/DataContract.md`
- updated `docs/tests/TestPlan.md`
- updated `docs/tests/TestResults.md`

## 5. Acceptance Criteria

- Market data can be represented without pandas or external dependencies.
- In-memory adapter can return sample datasets by symbol and date range.
- Valid sample data passes validation.
- Missing required OHLCV fields fail validation.
- Duplicate timestamps fail validation.
- Missing values fail validation.
- Empty datasets fail validation.
- Symbol universe mismatch fails validation.
- Date range metadata is recorded.
- Data provenance records source, collected time, preprocessing steps, symbol universe, date range, frequency, and timezone.
- Unit tests pass.
- Secret check passes.
- Documentation is updated.

## 6. Test Plan

Unit tests:

- Market model construction.
- Provenance construction.
- Validation pass for valid fixture.
- Validation failure for missing fields.
- Validation failure for duplicate timestamps.
- Validation failure for missing values.
- Validation failure for empty dataset.
- Validation failure for symbol mismatch.
- In-memory adapter retrieval.
- In-memory adapter date filtering.

Integration tests:

- Not required in Sprint 2 unless market adapter boundaries require one.

Research validation:

- Not applicable in Sprint 2 because no strategy or backtest behavior is implemented.

Secret checks:

- Verify no `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, real data dumps, or log files are tracked.

## 7. Documentation Plan

Create:

- `docs/architecture/MarketEngine.md`
- `docs/research/DataContract.md`

Update:

- `docs/tests/TestPlan.md`
- `docs/tests/TestResults.md`

Documentation must describe:

- Market dataset model.
- Required OHLCV fields.
- Validation rules.
- Provenance requirements.
- Adapter boundary.
- What Sprint 2 intentionally excludes.

## 8. Commit Plan

Expected commit sequence:

1. `docs(v2): explain sprint roadmap and market sprint scope`
2. `feat(v2-market): add market data foundation`

The first commit covers planning documentation. The second commit should happen only after Sprint 2 implementation, tests, and documentation are complete.

## 9. Known Constraints

- Public repository must not include private market data, broker credentials, or real account state.
- Sprint 2 uses Python standard library only unless a later sprint explicitly approves external dependencies.
- The in-memory adapter is for test and research fixture behavior only.

## 10. Sprint 2 Gate Decision

Sprint 2 implementation may begin after this brief is accepted.

Implementation must remain limited to the scope above.

