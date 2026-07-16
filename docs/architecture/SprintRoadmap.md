# StrategyLab v2 Sprint Roadmap

Status: Active  
Branch: develop-v2  
Source of Truth: `docs/architecture/GaonPlatformMasterSpecification.md` and `docs/architecture/MasterBlueprint.md`

## Purpose

This roadmap explains what each StrategyLab v2 sprint is meant to achieve. It is written as an operating guide for development, review, and scope control.

StrategyLab is the first research lab inside the Gaon Platform. Sprint work must preserve the Gaon rules: evidence before approval, public/private separation, no live trading code in the public repository, no MyMoneyGuard V1 redevelopment, and documentation plus tests for every sprint.

Every sprint follows the same order:

1. Sprint Brief
2. Implementation
3. Unit Test
4. Integration Test where applicable
5. Research Validation where applicable
6. Commit
7. Documentation

No sprint may accept unrelated feature additions after its scope is frozen.

## Sprint 0: Blueprint and Repository Governance

Sprint 0 defines the rules of the project before implementation starts.

What it establishes:

- StrategyLab v2 mission
- public/private repository separation
- Git branch strategy
- secret exclusion policy
- v2 module map
- Sprint discipline

What it does not do:

- write production code
- add market data logic
- add strategy logic
- connect to broker systems

Completion signal:

- Master Blueprint is committed
- `develop-v2` exists
- public repository contains no secrets

Current status: Complete.

## Sprint 1: Core Refactoring and Project Foundation

Sprint 1 creates the empty but testable foundation of StrategyLab v2.

What it builds:

- Python project metadata
- package skeleton
- safe example config
- logger setup
- module registry
- plugin loader boundary
- baseline unit tests
- developer setup documentation

What it does not do:

- download market data
- run strategies
- run backtests
- call AI APIs
- call broker APIs
- build a dashboard

Completion signal:

- project imports successfully
- config loads without secrets
- logger initializes
- module registry matches Blueprint
- tests pass
- documentation is updated

Current status: Complete.

## Sprint 2: Market Engine

Sprint 2 creates the market data foundation.

What it builds:

- market data model
- data source metadata model
- data provenance model
- validation result model
- in-memory market data adapter
- cache interface
- validation rules
- sample data fixtures

What it does not do:

- connect to KIS, Kiwoom, IBKR, Alpaca, or paid APIs
- store real account data
- download live data
- run strategies
- run backtests

Completion signal:

- valid sample data is accepted
- missing required columns are rejected
- duplicate timestamps are detected
- data provenance is recorded
- no secret is required

Current status: Next.

## Sprint 3: Strategy Framework

Sprint 3 defines how strategies are written, registered, configured, and tested.

What it builds:

- strategy interface
- strategy registry
- parameter schema
- signal output contract
- example strategy stubs
- strategy config round-trip support

What it does not do:

- optimize strategies
- run full backtests
- approve champions
- use private live-trading code

Completion signal:

- strategies can be registered as plugins
- invalid parameters are rejected
- signal output is deterministic for the same input
- strategy configs can be exported and reloaded

Current status: Planned.

## Sprint 4: Backtest v2

Sprint 4 creates the deterministic backtest execution foundation.

What it builds:

- backtest runner
- canonical result schema
- trade log contract
- equity curve contract
- walk-forward workflow skeleton
- grid search workflow skeleton
- Monte Carlo workflow skeleton

What it does not do:

- execute live trades
- select production champions
- connect to broker systems

Completion signal:

- same input produces same output
- known scenario fixture passes
- result schema supports later metrics and reports

Current status: Planned.

## Sprint 5: Portfolio Engine

Sprint 5 creates portfolio accounting and allocation behavior.

What it builds:

- cash model
- position model
- allocation model
- position sizing logic
- rebalancing logic
- portfolio performance state

What it does not do:

- place orders
- reconcile broker holdings
- mutate live accounts

Completion signal:

- cash and holdings reconcile
- allocation limits are enforced
- rebalancing behavior is testable

Current status: Planned.

## Sprint 6: Risk Engine

Sprint 6 creates risk metrics and research-time constraints.

What it builds:

- drawdown metrics
- exposure metrics
- ATR sizing support
- risk score
- emergency stop model
- circuit breaker model

What it does not do:

- control private live trading directly
- override broker or account state

Completion signal:

- risk formulas are unit-tested
- emergency stop behavior is visible and explainable
- risk outputs can be included in reports

Current status: Planned.

## Sprint 7: AI Research

Sprint 7 adds AI-assisted research review without giving AI autonomous trading authority.

What it builds:

- AI review interface
- strategy analysis input schema
- parameter suggestion workflow
- failure analysis workflow
- report draft integration

What it does not do:

- call live trading APIs
- silently approve strategies
- mutate experiment results as source of truth

Completion signal:

- prompt/input assembly is deterministic
- AI response schema is validated
- AI outputs are stored as review metadata

Current status: Planned.

## Sprint 8: Dashboard

Sprint 8 creates a GUI layer for research workflows.

What it builds:

- dashboard shell
- performance view
- portfolio view
- experiment view
- AI review view
- chart placeholders or initial charts

What it does not do:

- hide domain logic inside UI code
- bypass research validation
- expose secrets

Completion signal:

- UI maps to explicit domain operations
- domain logic remains testable without UI
- build or smoke test passes

Current status: Planned.

## Sprint 9: Broker Integration and Paper Trading

Sprint 9 creates safe broker abstractions and paper trading support.

What it builds:

- broker interface
- paper trading adapter
- example-only broker config
- private-system adapter boundary
- secret absence tests

What it does not do:

- store real broker credentials
- execute real trades from the public repository
- read MyMoneyGuard private files

Completion signal:

- broker interfaces are testable without credentials
- paper trading simulation works with sample data
- secret checks pass

Current status: Planned.

## Sprint 10: Release Candidate

Sprint 10 stabilizes StrategyLab v2.0 for release.

What it builds:

- release checklist
- full test pass
- research validation pass
- release notes
- migration notes
- performance sanity check

What it does not do:

- add new features
- change architecture without a blueprint amendment

Completion signal:

- full unit suite passes
- integration suite passes
- research validation passes
- release documentation is complete
- public repository contains no secrets

Current status: Planned.

## Sprint 11: Research Brain

Sprint 11 starts the Gaon research-partner layer for StrategyLab.

What it builds:

- research goal model
- research planner
- research session
- research interview contract
- research journal
- memory foundation

What it does not do:

- add live trading
- add private MyMoneyGuard access
- implement PluginLab, AudioLab, DevLab, LearningLab, JUCE, Unreal, or Wwise

Current status: Planned.

## Sprint 12: Memory and Evidence

Sprint 12 creates the evidence-backed memory foundation.

What it builds:

- memory records
- knowledge records
- evidence records
- citation model
- duplicate detection
- research history

Current status: Planned.

## Sprint 13: Strategy Generator

Sprint 13 creates deterministic strategy hypothesis generation.

What it builds:

- hypothesis model
- experiment queue
- parameter space
- deterministic seed handling

Current status: Planned.

## Sprint 14: V1 Adapter Contract

Sprint 14 defines contracts for future MyMoneyGuard V1 reuse.

What it builds:

- BacktestPort
- OptimizerPort
- WalkForwardPort
- MonteCarloPort
- golden fixture
- mock adapter
- version check

What it does not do:

- modify MyMoneyGuard V1
- reimplement MyMoneyGuard V1 internals
- connect to private files or live accounts

Current status: Planned.

## Sprint 15: Validation

Sprint 15 formalizes strategy validation and champion lifecycle.

What it builds:

- champion league
- walk-forward validation
- Monte Carlo validation
- overfitting checks
- rejected, champion, and retired states

Current status: Planned.

## Sprint 16: AI Provider

Sprint 16 abstracts AI providers and adds evidence controls.

What it builds:

- OpenAI provider boundary
- local LLM provider boundary
- knowledge search
- citation enforcement
- hallucination guard

Current status: Planned.

## Sprint 17: Telegram Research Interface

Sprint 17 adds a research-only Telegram conversation boundary.

What it builds:

- conversation model
- research request
- research status
- research report

What it does not do:

- execute trades
- send live broker orders
- expose account or token data

Current status: Planned.

## Sprint 18: Dashboard Expansion

Sprint 18 expands the dashboard for research operations.

What it builds:

- research dashboard
- experiment dashboard
- Notion sync boundary
- research journal view

Current status: Planned.

## Sprint 19: Research Loop

Sprint 19 connects the core StrategyLab research cycle.

Target loop:

```text
Research
  -> Knowledge
  -> Strategy
  -> Experiment
  -> Validation
  -> Memory
  -> Next Research
```

Current status: Planned.

## Sprint 20: Release Candidate

Sprint 20 prepares the Gaon-backed StrategyLab release candidate.

What it builds:

- shadow mode
- approval workflow
- export
- rollback
- acceptance test
- documentation

Completion signal:

- final audit passes
- architecture, security, public/private separation, V1 compatibility, documentation, tests, and release readiness are verified
- no merge to `main` occurs before final audit approval

Current status: Planned.

## Operating Rule

When a new idea appears, it must be classified before action:

- `bug`: may enter the active sprint if it blocks the sprint
- `blueprint-gap`: requires blueprint amendment
- `future-backlog`: record for later
- `rejected`: conflicts with StrategyLab v2 rules
