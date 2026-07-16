# StrategyLab-v2

AI-assisted quantitative strategy research platform.

StrategyLab v2 is the first research lab inside the Gaon Platform. Gaon is Youngha's AI Engineering Partner: a partner for research, development, learning, validation, and project memory.

StrategyLab v2 is developed as a public research, backtest, optimization, test, and documentation repository. Live trading credentials, account data, execution state, and operational logs belong in the private MyMoneyGuard system, not in this repository.

This project's purpose is not to write as much code as possible, but to build a long-term maintainable AI Engineering Platform. Architecture consistency, verifiability, documentation, and tests take priority over feature volume.

이 프로젝트의 목적은 코드를 많이 작성하는 것이 아니라, 장기간 유지 가능한 AI Engineering Platform을 구축하는 것이다. 기능 추가보다 아키텍처의 일관성, 검증 가능성, 문서화, 테스트를 우선한다.

## Release Candidate Status

StrategyLab v2 is currently a Foundation Release Candidate on `develop-v2`.

Included foundations:

- Core configuration, logging, module registry, and plugin boundaries
- Market data models, validation, provenance, and in-memory adapter
- Strategy metadata, parameters, registry, configs, and deterministic signals
- Deterministic backtest result, trade log, and equity curve contracts
- Portfolio cash, position, allocation, sizing, and snapshot models
- Risk metrics, ATR sizing, emergency stop, and circuit breaker contracts
- AI research review input/output schema and deterministic prompt assembly
- Dashboard view models and backtest summary shell
- Broker interface and deterministic paper broker adapter
- Release notes, changelog, runbook, and verification script

## Installation

Windows PowerShell:

```powershell
py -3.11 -m pip install -e .
```

Linux/macOS bash:

```bash
python3.11 -m pip install -e .
```

No broker credential or `.env` file is required.

## Tests

Windows PowerShell:

```powershell
$env:PYTHONPATH = "src;tests/unit;tests/integration"
py -3.11 -m unittest discover -s tests/unit
py -3.11 -m unittest discover -s tests/integration
```

Linux/macOS bash:

```bash
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m unittest discover -s tests/unit
PYTHONPATH="src:tests/unit:tests/integration" python3.11 -m unittest discover -s tests/integration
```

## Release Verification

Windows PowerShell:

```powershell
py -3.11 scripts/verify_release.py
```

Linux/macOS bash:

```bash
python3.11 scripts/verify_release.py
```

Expected result:

```text
StrategyLab v2 release verification passed.
Unit tests: PASS
Integration tests: PASS
Required files: PASS
```

## Basic Usage

```python
from strategylab.market import InMemoryMarketDataAdapter
from strategylab.strategies import CloseAboveThresholdStrategy
from strategylab.backtest import BacktestConfig, SimpleBacktestRunner

adapter = InMemoryMarketDataAdapter(dataset)
market_data = adapter.load(symbols=("AAA",))
strategy = CloseAboveThresholdStrategy()
strategy_config = strategy.build_config({"threshold": 100.0})
signals = strategy.generate_signals(market_data, strategy_config)
result = SimpleBacktestRunner().run(market_data, signals, strategy_config, BacktestConfig(initial_capital=1000.0))
```

## Paper Broker Example

```python
from strategylab.broker import BrokerOrder, OrderSide, PaperBrokerAdapter

broker = PaperBrokerAdapter({"AAA": 100.0})
fill = broker.submit_order(BrokerOrder("AAA", OrderSide.BUY, 1))
```

The paper broker is deterministic and does not connect to a real broker.

## Module Structure

- `strategylab.core`: configuration, logging, module registry, plugin boundary
- `strategylab.market`: market data contracts, validation, provenance
- `strategylab.strategies`: strategy interface, parameters, registry, signals
- `strategylab.backtest`: deterministic backtest result contracts
- `strategylab.portfolio`: cash, positions, allocations, snapshots
- `strategylab.risk`: drawdown, exposure, ATR sizing, guardrail decisions
- `strategylab.research`: AI review schema and prompt assembly
- `strategylab.dashboard`: display-ready view models
- `strategylab.broker`: broker interface and paper adapter
- `strategylab.reports`: report boundary
- `strategylab.notification`: notification boundary

## MyMoneyGuard Separation

StrategyLab-v2 is the public research and test platform. MyMoneyGuard remains the private live trading and operations system.

StrategyLab-v2 may define future adapter contracts for MyMoneyGuard V1 reuse, but it must not modify, redevelop, import private runtime state from, or depend on the private MyMoneyGuard system.

StrategyLab-v2 must not contain:

- KIS API keys or secrets
- account numbers
- Telegram tokens
- `.env`
- `kis_token.json`
- real trade state
- production logs
- private MyMoneyGuard files

## Safety Rule

Do not commit `.env`, token files, account files, real trade state, production logs, or broker secrets. Use `.env.example` and `config/config.example.yaml` only.

## Master Documents

- `docs/architecture/GaonPlatformMasterSpecification.md`: top-level Gaon Platform development specification
- `docs/architecture/MasterBlueprint.md`: StrategyLab v2 master blueprint
- `docs/architecture/SprintRoadmap.md`: sprint operating roadmap
