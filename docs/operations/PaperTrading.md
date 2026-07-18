# Paper Trading Operations

Status: Sprint 40

Live trading is not implemented.

The Sprint 40 trading commands operate only against deterministic fake or paper adapters. They require no broker credential, account number, KIS token, MyMoneyGuard file, live market data, Telegram connection, or external AI provider.

## Commands

```powershell
py -3.11 -m gaon.runtime.cli trading-status --db runtime.sqlite
py -3.11 -m gaon.runtime.cli trading-account --db runtime.sqlite
py -3.11 -m gaon.runtime.cli trading-positions --db runtime.sqlite
py -3.11 -m gaon.runtime.cli trading-simulate-buy --db runtime.sqlite --symbol 005930 --quantity 1 --price 70000
py -3.11 -m gaon.runtime.cli trading-simulate-sell --db runtime.sqlite --symbol 005930 --quantity 1 --price 70000
py -3.11 -m gaon.runtime.cli trading-cancel-simulated-order --db runtime.sqlite --request-id cli-request
py -3.11 -m gaon.runtime.cli trading-history --db runtime.sqlite
```

## Expected Behavior

- `trading-status` reports the paper adapter state.
- `trading-account` returns a deterministic paper account snapshot.
- `trading-positions` returns deterministic paper positions.
- `trading-simulate-buy` and `trading-simulate-sell` create structured simulation results only.
- `trading-history` reads persisted simulation results from runtime schema v11.

## Safety

The public repository must not contain or load broker credentials. Any live trading, real order, KIS, broker API, private account, or MyMoneyGuard request must remain blocked until a future private adapter is designed, reviewed, approved, and connected outside this public repository.
