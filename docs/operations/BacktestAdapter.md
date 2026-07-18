# Backtest Adapter Operations

Status: Sprint 41

The real v1 backtest engine is not required for automated tests. Sprint 41 defines the safe adapter boundary and deterministic integration path.

## CLI

```powershell
py -3.11 -m gaon.runtime.cli backtest-status --db runtime.sqlite
py -3.11 -m gaon.runtime.cli backtest-list-strategies --db runtime.sqlite
py -3.11 -m gaon.runtime.cli backtest-run --db runtime.sqlite --strategy turtle_v5 --dataset sample_krx --start 2024-01-01 --end 2026-01-01
py -3.11 -m gaon.runtime.cli backtest-history --db runtime.sqlite
```

To inspect a result:

```powershell
py -3.11 -m gaon.runtime.cli backtest-show --db runtime.sqlite backtest-result:<fingerprint>
```

## Safety

The CLI uses `FakeBacktestAdapter` and runtime schema v12 persistence. It does not require a private v1 repository, live KIS, broker credentials, live market data, MyMoneyGuard, network access, or paid AI APIs.

The adapter boundary must not be used for Champion promotion, active strategy switching, paper-to-live promotion, live deployment, automatic trading, or automatic approval.
