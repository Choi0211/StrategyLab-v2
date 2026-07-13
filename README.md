# StrategyLab-v2

AI-assisted quantitative strategy research platform.

StrategyLab v2 is developed as a public research, backtest, optimization, test, and documentation repository. Live trading credentials, account data, execution state, and operational logs belong in the private MyMoneyGuard system, not in this repository.

## Sprint 1 Status

Sprint 1 establishes the project foundation:

- safe example configuration
- core package skeleton
- logger initialization
- module registry
- plugin loader interface
- baseline tests
- developer documentation

## Safety Rule

Do not commit `.env`, token files, account files, real trade state, production logs, or broker secrets. Use `.env.example` and `config/config.example.yaml` only.

## Local Test

```bash
PYTHONPATH=src python -m unittest discover -s tests/unit
```
