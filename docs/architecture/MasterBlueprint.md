# StrategyLab v2 Master Blueprint

Version: 2.0-blueprint-002  
Status: Planning / Blueprint Gate  
Base Release: StrategyLab v1.0 Stable Release  
Base Tag: v1.0  
Release Check: 7/7 PASS  
Target Repository: Choi0211/StrategyLab-v2  
Target Branch: develop-v2  
Architecture: Modular  
Development Method: Sprint  
Release Target: v2.0 Stable  
Date: 2026-07-13  
Owner Role: Chief AI Architect / Quant Research Lead
Parent Specification: `docs/architecture/GaonPlatformMasterSpecification.md`

## 1. Executive Intent

StrategyLab v2 will be developed as the first research lab inside the Gaon Platform. Gaon is Youngha's AI Engineering Partner, and StrategyLab is the public, modular, reproducible quant research platform that Gaon operates first.

The parent standard for this Blueprint is the Gaon Platform Master Development Specification. If a StrategyLab decision conflicts with that specification, the Gaon Platform specification controls unless the user explicitly approves a Blueprint amendment.

StrategyLab v2 is separated from the private MyMoneyGuard operating system so that research, backtesting, optimization, testing, and documentation can proceed without exposing secrets, account data, execution state, or operational logs.

v1.0 is complete and stable. v2 development starts only after this Master Blueprint is accepted.

Mandatory development order:

1. Blueprint
2. Sprint Planning
3. Implementation
4. Unit Test
5. Integration Test
6. Research Validation
7. Git Commit
8. Documentation
9. Next Sprint

No feature may be added during an active sprint unless it is required to fix a sprint-blocking bug.

## 2. Repository Strategy

### 2.1 Public Repository

Repository:

- `Choi0211/StrategyLab-v2`

Purpose:

- Research platform
- Strategy modules
- Backtest engine
- Optimization tools
- Test suite
- Documentation
- Example-only configuration

Allowed in public repository:

- Source code
- Unit and integration tests
- Research validation fixtures
- Documentation
- `.env.example`
- `config.example.yaml`
- Synthetic or public sample data
- Broker interface abstractions
- Paper trading abstractions

Forbidden in public repository:

- KIS API key or secret
- Account number
- Telegram token or chat ID
- `.env`
- `.env` backups
- `kis_token.json`
- Real trade state JSON
- Production logs
- Server paths, private deployment details, or operational credentials

### 2.2 Private System

Private system:

- `MyMoneyGuard`

Purpose:

- Live trading
- Broker secrets
- Account data
- Telegram credentials
- Real execution state
- Operational logs
- Server-specific configuration

StrategyLab v2 may provide adapters that can later connect to MyMoneyGuard, but v2 must never require private secrets to run tests or research workflows.

## 3. Vision

StrategyLab v2 is an AI-assisted strategy research platform.

It is not merely an auto-trading tool. It is part of a long-term AI Engineering Platform whose purpose is sustained research, evidence, validation, documentation, and maintainable architecture.

It must support the full research loop:

1. Research
2. Backtest
3. Strategy comparison
4. AI analysis
5. Evidence-based decision support
6. Optional paper-trading or broker-interface validation

AI assists research. AI does not silently make trading decisions.

## 4. Design Philosophy

### Principle 1: Research First

Every strategy must pass through a research and validation workflow before it can be considered for execution or private-system integration.

### Principle 2: Everything Is Modular

Each capability must be separated into clear modules:

- Core Module
- Market Data Module
- Strategy Module
- Portfolio Module
- Risk Module
- Backtest Module
- AI Research Module
- Broker Connector Module
- Dashboard Module
- Report Generator Module
- Notification Module

Modules must avoid hidden dependencies and must expose testable interfaces.

### Principle 3: No Hidden Logic

Every important calculation must be traceable through:

- Configuration
- Logs
- Reports
- Statistics
- Experiment records
- Test fixtures

### Principle 4: AI Assisted, Not AI Autonomous

AI may analyze, summarize, explain, rank, and suggest. It must not silently execute trades, override risk rules, or mutate research results without explicit workflow control.

### Principle 5: Reproducibility First

Every official experiment must be reproducible from stored metadata, strategy version, data provenance, parameters, and Git commit hash.

## 5. Overall Architecture

```text
StrategyLab
  -> Core Engine
  -> Market Data Engine
  -> Strategy Engine
  -> Portfolio Engine
  -> Risk Engine
  -> Backtest Engine
  -> AI Research Engine
  -> Broker Connector
  -> Dashboard
  -> Report Generator
  -> Notification Engine
```

Research pipeline:

```text
Market Data
  -> Data Validation
  -> Strategy Definition
  -> Signal Generation
  -> Portfolio Simulation
  -> Risk Analysis
  -> Backtest / Optimization
  -> Experiment Registry
  -> AI Research Review
  -> Report Generation
```

## 6. Core Modules

### 6.1 Core Engine

Responsibilities:

- Program lifecycle
- Configuration management
- Logging
- Task scheduling
- Module loading
- Plugin loading
- Shared utilities

Acceptance criteria:

- Application settings are loaded from safe example config by default.
- No secret is required to run local tests.
- Modules can be discovered without importing private-system code.

### 6.2 Market Data Engine

Responsibilities:

- Load and normalize market data.
- Validate data quality.
- Preserve data provenance.
- Support public or synthetic sample data for tests.

Target markets and assets:

- Korean equities
- US equities
- ETF
- Index
- Sector data
- FX
- Interest rates
- Futures
- Commodities
- Volume and liquidity data
- Minute and daily bars where supported

Acceptance criteria:

- Invalid data fails before official backtest execution.
- Every official experiment records data source, collection time, preprocessing steps, symbol universe, date range, frequency, and validation status.

### 6.3 Strategy Engine

Responsibilities:

- Manage strategies as plugins.
- Validate strategy parameters.
- Generate deterministic signals.
- Support strategy registration and discovery.

Initial strategy families:

- Turtle
- Breakout
- Momentum
- Mean Reversion
- Opening Gap
- AI Strategy
- Pair Trading
- Volatility Strategy

Acceptance criteria:

- New strategies can be added as plugins without modifying core engine logic.
- The same strategy config and data snapshot produce the same signals.

### 6.4 Portfolio Engine

Responsibilities:

- Manage positions.
- Manage cash.
- Manage allocation and weights.
- Calculate position size.
- Support capital allocation.
- Support rebalancing.
- Generate portfolio performance state.

Acceptance criteria:

- Cash, holdings, trades, and equity curve reconcile.
- Position sizing can be tested independently.

### 6.5 Risk Engine

Responsibilities:

- Calculate risk metrics.
- Enforce research-time risk constraints.
- Detect unsafe or unstable strategy behavior.

Target capabilities:

- Max drawdown
- Daily loss limit
- Sector exposure
- Correlation
- ATR position sizing
- Risk score
- Emergency stop
- Circuit breaker

Acceptance criteria:

- Risk calculations are covered by unit tests.
- Any emergency-stop or circuit-breaker result is visible in reports and experiment records.

### 6.6 Backtest Engine

Responsibilities:

- Run deterministic backtests.
- Apply transaction costs and slippage.
- Support research validation workflows.
- Produce canonical outputs for metrics and reports.

Target capabilities:

- Walk-forward analysis
- Monte Carlo analysis
- Parameter sweep
- Grid search
- Rolling test
- Out-of-sample validation
- Benchmark comparison
- Performance comparison

Acceptance criteria:

- Re-running the same experiment with the same inputs produces the same result.
- Official backtests include strategy version, data version, parameters, and Git commit hash.

### 6.7 AI Research Engine

Responsibilities:

- Analyze strategies and results.
- Review backtest evidence.
- Suggest parameter candidates.
- Explain failure modes.
- Generate research summaries.

Target capabilities:

- Strategy analysis
- Signal analysis
- Parameter suggestion
- Market regime analysis
- Risk analysis
- Strategy recommendation
- Failure reason analysis
- Automatic research report draft
- AI review

Acceptance criteria:

- AI output is stored as review metadata, not as hidden source-of-truth.
- AI recommendations include supporting evidence and caveats.

### 6.8 Broker Connector

Responsibilities:

- Provide broker interface abstractions.
- Keep live credentials out of the public repository.
- Support future integration with private execution systems.

Target connectors:

- Korea Investment Securities interface
- Kiwoom interface
- IBKR interface
- Alpaca interface
- Paper trading interface

Acceptance criteria:

- Public code contains interfaces and examples only.
- No real credential is required for tests.
- Live trading execution remains controlled by private systems.

### 6.9 Dashboard

Responsibilities:

- Provide GUI access to research workflows.
- Display portfolio, performance, risk, strategy state, and AI review.

Target views:

- Strategy workspace
- Market data view
- Backtest run view
- Portfolio view
- Risk view
- Experiment registry
- Report view

Acceptance criteria:

- Dashboard actions map to explicit domain operations.
- Domain logic remains testable without GUI execution.

### 6.10 Report Generator

Responsibilities:

- Generate human-readable research reports.
- Support multiple export formats.

Target report types:

- Daily
- Weekly
- Monthly
- Yearly
- Research report

Target formats:

- PDF
- Markdown
- CSV
- HTML

Acceptance criteria:

- Reports include strategy summary, data assumptions, backtest assumptions, metrics, risk findings, AI review, and research conclusion.

### 6.11 Notification Engine

Responsibilities:

- Provide notification abstractions.
- Support research and operational alerts without embedding secrets.

Target channels:

- Telegram
- Discord
- Slack
- Email
- Push

Target alerts:

- Trade alert
- AI analysis alert
- Risk alert
- Fill alert
- Error alert

Acceptance criteria:

- Public repository stores only interface code and example configuration.
- Real tokens are excluded.

## 7. Folder Structure

Target structure:

```text
StrategyLab-v2/
  src/
    strategylab/
      core/
      config/
      data/
      market/
      strategies/
      portfolio/
      risk/
      backtest/
      research/
      broker/
      dashboard/
      reports/
      notification/
  tests/
    unit/
    integration/
    research_validation/
  docs/
    architecture/
      MasterBlueprint.md
      SystemArchitecture.md
      ModuleSpecifications.md
    research/
      StrategyResearch.md
      ExperimentLog.md
    releases/
      CHANGELOG.md
      ReleaseNotes.md
    operations/
      Deployment.md
      Runbook.md
    tests/
      TestPlan.md
      TestResults.md
  config/
    config.example.yaml
  scripts/
  logs/
  .env.example
  .gitignore
  pyproject.toml
  README.md
```

`logs/` may exist locally but runtime log files must be ignored by Git.

## 8. Experiment Governance

### 8.1 Research Reproducibility

Every official backtest must store:

- Data version
- Strategy version
- Parameters
- Git commit hash
- Engine version
- Run timestamp
- Environment metadata
- Result artifacts

The same inputs must reproduce the same outputs.

### 8.2 Experiment Registry

Every experiment must receive a unique ID.

The registry must store:

- Experiment ID
- Strategy name and version
- Parameter set
- Data provenance
- Metrics including MDD, CAGR, Sharpe, and Profit Factor
- Report path
- AI review path or metadata
- Research conclusion
- Superseded/deprecated status where applicable

### 8.3 Data Provenance

Every official dataset must record:

- Source
- Collection time
- Preprocessing steps
- Symbol universe
- Date range
- Frequency
- Timezone
- Validation result

## 9. Backtest Assumptions

Every official backtest must define:

- Initial capital
- Benchmark
- Trading calendar
- Rebalance schedule
- Execution price convention
- Transaction cost model
- Slippage model
- Position sizing rule
- Maximum position constraints
- Cash handling
- Missing price handling
- Corporate action policy where applicable

Defaults may exist, but they must be visible and documented.

## 10. Development Workflow

Mandatory sequence:

```text
Blueprint
  -> Sprint Planning
  -> Implementation
  -> Unit Test
  -> Integration Test
  -> Research Validation
  -> Git Commit
  -> Documentation
  -> Next Sprint
```

Forbidden:

- Adding features during an active sprint
- Implementing immediately after a design change without sprint planning
- Committing without tests
- Closing a sprint without documentation
- Adding secrets to the public repository

## 11. Git Branch Strategy

```text
main
  -> release/v2.0
      -> develop-v2
          -> feature/<module-name>
```

Branch roles:

- `main`: stable operating version only
- `release/v2.0`: release candidate integration and final verification
- `develop-v2`: sprint integration branch
- `feature/*`: individual sprint or module work

All sprint implementation should target feature branches and merge into `develop-v2` after tests.

## 12. Sprint Plan

### Sprint 0: Blueprint and Repository Governance

Objective:

- Establish this Master Blueprint and public/private repository separation.

Deliverables:

- Master Blueprint
- Repository strategy
- Branch strategy
- Secret exclusion policy

Exit criteria:

- Blueprint accepted
- `develop-v2` created
- Blueprint committed to GitHub

### Sprint 1: Core Refactoring and Project Foundation

Objective:

- Create the v2 project structure and core module foundation.

Deliverables:

- `pyproject.toml`
- package skeleton
- configuration loader
- logger
- module loader
- plugin loader foundation
- baseline test harness

Tests:

- Import smoke tests
- Config load tests
- Logger initialization tests
- Module discovery tests

Documentation:

- Architecture overview
- Developer setup guide

### Sprint 2: Market Engine

Objective:

- Build market data ingestion and validation foundation.

Deliverables:

- Market data interface
- cache interface
- validation rules
- sample data fixtures
- data provenance model

Tests:

- Valid dataset acceptance
- Missing data detection
- Duplicate timestamp detection
- Provenance record tests

Documentation:

- Data contract
- Validation rules

### Sprint 3: Strategy Framework

Objective:

- Build plugin-style strategy framework.

Deliverables:

- Strategy interface
- strategy registry
- parameter schema
- signal output contract
- example strategies

Tests:

- Strategy registration
- Parameter validation
- Signal determinism
- Config round trip

Documentation:

- Strategy authoring guide

### Sprint 4: Backtest v2

Objective:

- Build deterministic backtest and research validation workflows.

Deliverables:

- Backtest runner
- walk-forward workflow
- grid search
- Monte Carlo workflow
- canonical result schema

Tests:

- Deterministic repeatability
- Known-scenario fixture
- Walk-forward smoke test
- Grid search smoke test
- Monte Carlo smoke test

Documentation:

- Backtest engine guide

### Sprint 5: Portfolio Engine

Objective:

- Build portfolio accounting and allocation logic.

Deliverables:

- Position model
- cash model
- allocation model
- position sizing
- rebalancing
- performance state

Tests:

- Cash/holding reconciliation
- Allocation validation
- Position sizing tests
- Rebalancing tests

Documentation:

- Portfolio engine guide

### Sprint 6: Risk Engine

Objective:

- Build risk metrics and constraints.

Deliverables:

- Drawdown metrics
- exposure metrics
- ATR sizing
- risk score
- emergency stop
- circuit breaker

Tests:

- Risk formula tests
- Emergency-stop behavior tests
- Edge case tests

Documentation:

- Risk engine guide

### Sprint 7: AI Research

Objective:

- Add AI-assisted research review and strategy analysis.

Deliverables:

- AI review interface
- strategy analysis prompt contract
- parameter suggestion workflow
- failure analysis workflow
- report draft integration

Tests:

- Deterministic prompt/input assembly tests
- AI response schema validation
- Fallback behavior tests

Documentation:

- AI research guide

### Sprint 8: Dashboard

Objective:

- Provide GUI workflows for research, backtesting, metrics, and portfolio review.

Deliverables:

- dashboard shell
- charts
- performance view
- portfolio view
- experiment view
- AI review view

Tests:

- UI smoke tests where applicable
- Domain-to-UI mapping tests
- Build test

Documentation:

- Dashboard guide

### Sprint 9: Broker Integration and Paper Trading

Objective:

- Provide safe broker interfaces and paper trading workflow.

Deliverables:

- Broker interface
- paper trading adapter
- example-only broker config
- private-system adapter boundary

Tests:

- Interface contract tests
- Paper trading simulation tests
- Secret absence tests

Documentation:

- Broker connector guide
- Secret management guide

### Sprint 10: Release Candidate

Objective:

- Stabilize v2.0 for release.

Deliverables:

- Full integration test pass
- research validation pass
- performance sanity check
- release notes
- migration notes
- v2.0 release checklist

Tests:

- Full unit suite
- Full integration suite
- Full research validation suite
- Documentation verification

Documentation:

- Release notes
- Changelog
- Runbook

### Sprint 11 to Sprint 20: Gaon Platform Research Expansion

Sprint 11 through Sprint 20 continue StrategyLab under the Gaon Platform Master Development Specification.

Planned scope:

- Sprint 11: Research Brain
- Sprint 12: Memory, Knowledge, Evidence, Citation, and Research History
- Sprint 13: Strategy Generator
- Sprint 14: V1 Adapter Contract
- Sprint 15: Validation and Champion lifecycle
- Sprint 16: AI Provider abstraction and hallucination guard
- Sprint 17: Telegram research interface with no trading
- Sprint 18: Research and experiment dashboards
- Sprint 19: full research loop
- Sprint 20: Release Candidate, shadow mode, approval, rollback, acceptance test, and documentation

Sprint 11 through Sprint 20 must not include PluginLab, AudioLab, DevLab, LearningLab, JUCE, Unreal, Wwise, or unrelated product work.

## 13. Documentation Standard

Required documentation:

```text
docs/
  architecture/
    MasterBlueprint.md
    SystemArchitecture.md
    ModuleSpecifications.md
  research/
    StrategyResearch.md
    ExperimentLog.md
  releases/
    CHANGELOG.md
    ReleaseNotes.md
  operations/
    Deployment.md
    Runbook.md
  tests/
    TestPlan.md
    TestResults.md
```

Every sprint must update documentation before closure.

## 14. Quality Gates

### Gate A: Blueprint Gate

Required:

- Master Blueprint accepted
- repository strategy confirmed
- secrets policy confirmed
- Sprint 1 brief created

### Gate B: Sprint Gate

Required:

- Sprint scope frozen
- acceptance criteria written
- test plan written
- documentation plan written

### Gate C: Test Gate

Required:

- Unit tests pass
- Integration tests pass where applicable
- Research validation passes where applicable
- Secret scan or secret-exclusion check passes

### Gate D: Commit Gate

Required:

- Tests pass before commit
- Commit message identifies sprint scope
- Public repository contains no secret material

### Gate E: Documentation Gate

Required:

- Documentation updated
- known limitations recorded
- future backlog recorded

## 15. v2 Success Criteria

StrategyLab v2 is successful when:

- All major capabilities are separated into independent modules.
- New strategies can be registered as plugins without core-code changes.
- Walk-forward, Monte Carlo, and Grid Search are supported.
- Risk management includes drawdown, exposure, and loss controls.
- AI research can analyze strategies and generate research reports.
- Broker interfaces support safe expansion without public secrets.
- Unit, integration, and research validation tests pass.
- Architecture, operations, tests, and release documents are current.

## 16. Definition of Done

A v2 item is done only when:

- It is included in the Master Blueprint.
- It is included in the sprint plan.
- Implementation is complete.
- Unit tests are complete and passing.
- Integration tests are complete and passing where applicable.
- Research validation is complete where applicable.
- Git commit is complete.
- Documentation is updated.
- Secrets are not present in the public repository.

## 17. Master Backlog

### P0: Required for v2.0

- Core engine foundation
- Public repository structure
- Secret exclusion policy
- Market data validation
- Strategy plugin framework
- Portfolio engine
- Risk engine
- Backtest v2
- Experiment registry
- AI research review
- Report generator
- Documentation set
- Release checklist

### P1: Important

- Dashboard charts
- Broker connector interfaces
- Paper trading adapter
- Notification abstractions
- Benchmark comparison
- Parameter sweep UX

### P2: Future Candidates

- Cloud experiment storage
- Advanced factor exposure analysis
- Multi-user collaboration
- Production live-trading automation
- Private MyMoneyGuard adapter hardening

## 18. Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Public secret leakage | Severe security issue | `.env.example` only, secret scan, strict forbidden-file policy |
| Scope creep | Delayed v2 release | Enforce Blueprint -> Sprint -> Test -> Commit -> Documentation |
| Hidden look-ahead bias | Invalid research conclusions | Timestamp-aware signal/execution separation |
| Non-deterministic experiments | Irreproducible research | Store strategy version, data version, params, commit hash |
| AI overreach | Unsafe decision automation | AI assists only; explicit workflow controls |
| UI/domain coupling | Hard-to-test platform | Keep domain logic independent from dashboard |
| Broker boundary confusion | Accidental live execution | Public repo provides interfaces and paper trading only |

## 19. Architecture Decisions

### DEC-0001: Public StrategyLab v2 Repository

Decision:

- StrategyLab v2 will be developed in `Choi0211/StrategyLab-v2`.

Rationale:

- A clean public research repository enables mobile-friendly GitHub/Codex development without exposing private operating secrets.

### DEC-0002: Public/Private Separation

Decision:

- StrategyLab-v2 contains research, backtesting, optimization, tests, documentation, and example config.
- MyMoneyGuard contains live trading, account data, secrets, execution state, operational logs, and deployment configuration.

Rationale:

- Public research development must not endanger live trading credentials or private operational state.

### DEC-0003: AI Assistance Boundary

Decision:

- AI may review and recommend, but it cannot silently execute trades or override risk constraints.

Rationale:

- StrategyLab is a research platform first; execution requires explicit private-system control.

### DEC-0004: Sprint Discipline

Decision:

- v2 development must follow Blueprint -> Sprint Planning -> Implementation -> Test -> Commit -> Documentation.

Rationale:

- Stable quant research software requires controlled scope, reproducible validation, and traceable documentation.

## 20. Immediate Next Step

After this Blueprint is accepted:

1. Create or verify `develop-v2`.
2. Commit this Blueprint to `docs/architecture/MasterBlueprint.md`.
3. Create Sprint 1 Brief: Core Refactoring and Project Foundation.
4. Begin Sprint 1 only after the brief is accepted.
