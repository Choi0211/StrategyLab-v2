# StrategyLab-v2

AI-assisted quantitative strategy research platform.

StrategyLab v2 is the first research lab inside the Gaon Platform. Gaon is Youngha's AI Engineering Partner: a partner for research, development, learning, validation, and project memory.

StrategyLab v2 is developed as a public research, backtest, optimization, test, and documentation repository. Live trading credentials, account data, execution state, and operational logs belong in the private MyMoneyGuard system, not in this repository.

This project's purpose is not to write as much code as possible, but to build a long-term maintainable AI Engineering Platform. Architecture consistency, verifiability, documentation, and tests take priority over feature volume.

이 프로젝트의 목적은 코드를 많이 작성하는 것이 아니라, 장기간 유지 가능한 AI Engineering Platform을 구축하는 것이다. 기능 추가보다 아키텍처의 일관성, 검증 가능성, 문서화, 테스트를 우선한다.

## Release Candidate Status

StrategyLab v2 is currently a Gaon Phase B v3.0 Research Brain Release Candidate branch built on the Phase A v2.1 platform foundations.

Included foundations:

- Gaon Learning Engine package boundary
- Sprint 12-A Learning Memory domain contracts
- Sprint 12-B in-memory Learning Repository, duplicate/conflict detection, audit workflow, UTC timestamp guard, and golden JSON fixtures
- Sprint 12 Runtime related-memory retrieval, repository JSON export/import, migration fixtures, and Research Brain preparation workflow
- Gaon Runtime collaboration contracts: Event Bus, deterministic Korean Conversation Runtime, Assistant Provider interface, Telegram production smoke client, Notion dry-run mapper, notifications, reports, scheduler, and safe CLI
- Sprint 18-22 approval hardening, SQLite repositories, durable queue/scheduler, controlled runtime loop, backup hardening, and security/chaos coverage
- Sprint 23 broker-free TradingAdapter contract and v1 rollout plan
- Phase A v2.1 provider registry, plugin lifecycle, metrics, durable event store, safe replay, and long-term memory foundation
- Phase B v3.0 Research Brain: validated planning, safe evidence providers, evidence context, knowledge proposals, approval workflow, durable orchestration, checkpoints, reports, and free-only defaults
- Sprint 39 Daily Research Pipeline on top of the Sprint 38 scheduler, with deterministic evidence, reports, pending-review proposals, events, metrics, and CLI inspection
- Sprint 40 safe Trading Adapter foundation with paper-only simulation, risk guardrails, events, metrics, persistence, and CLI inspection
- Sprint 41 safe v1 Backtest Adapter foundation with normalized results, reproducibility fingerprints, fake/local process boundary, events, metrics, persistence, and CLI inspection
- Sprint 42 deterministic Strategy Validation Engine with PASS/FAIL/REVIEW reports, conservative policy v1, schema v13 persistence, events, metrics, and CLI inspection
- Sprint 43 Champion / Challenger Evaluation Engine with deterministic promotion-candidate reports, schema v14 persistence, events, metrics, and CLI inspection
- Sprint 44 Champion Registry with explicit approval-based promotion, schema v15 persistence, version history, rollback, events, metrics, and CLI inspection
- Sprint 45 Paper Trading Forward Test with active-Champion-only paper sessions, schema v16 persistence, simulated order observations, summaries, events, metrics, and CLI inspection
- Sprint 46 Paper Revalidation Engine with `LIVE_ELIGIBLE`, `HOLD`, `KILL`, `ROLLBACK_RECOMMENDED`, and `REVIEW` safety decisions, schema v17 persistence, events, metrics, and CLI inspection
- Sprint 47 Strategy Execution Runtime with default `DISABLED` mode, active-Champion binding, paper execution, live blocked behavior, schema v18 persistence, events, metrics, and CLI inspection
- Sprint 48 approved Champion Strategy Handoff Package generation with explicit deployment approval, deterministic JSON checksums, schema v19 persistence, events, metrics, and CLI inspection
- Gaon Research Brain package boundary
- Research Goal, Plan, Session, Interview, and Journal contracts
- Learning Memory, Evidence, Knowledge, Experience, Policy, and Confidence contracts
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

## Telegram Smoke Usage

Telegram production smoke commands are one-shot research conversation checks. They do not approve, trade, run shell commands, mutate GitHub, or access MyMoneyGuard.

```powershell
$env:GAON_RUNTIME_MODE = "execute"
$env:GAON_DRY_RUN = "false"
$env:GAON_TELEGRAM_ENABLED = "true"
$env:GAON_TELEGRAM_BOT_TOKEN = "<private-token-outside-repo>"
py -3.11 -m gaon.runtime.cli telegram-get-me --execute
py -3.11 -m gaon.runtime.cli telegram-discover-chat --execute
$env:GAON_TELEGRAM_ALLOWED_CHAT_IDS = "<discovered-chat-id>"
py -3.11 -m gaon.runtime.cli telegram-send-smoke --execute --chat-id <discovered-chat-id>
py -3.11 -m gaon.runtime.cli telegram-poll-once --execute
```

## Phase A Runtime CLI

```powershell
py -3.11 -m gaon.runtime.cli config-check
py -3.11 -m gaon.runtime.cli health
py -3.11 -m gaon.runtime.cli db-check
py -3.11 -m gaon.runtime.cli status
py -3.11 -m gaon.runtime.cli metrics
py -3.11 -m gaon.runtime.cli event-replay-dry-run
```

These commands are deterministic and do not perform live Telegram, OpenAI, Notion, broker, KIS, VPS, or MyMoneyGuard calls.

See `docs/operations/TelegramSetup.md` for the full safe setup flow. The project does not auto-load `.env`, and automated tests never call the real Telegram network.

## Research Brain v3

Phase B v3.0 adds a deterministic Research Brain pipeline:

```powershell
py -3.11 -m gaon.runtime.cli research-plan --query "ORB evidence"
py -3.11 -m gaon.runtime.cli research-run --query "ORB evidence" --dry-run
py -3.11 -m gaon.runtime.cli research-status run-1
py -3.11 -m gaon.runtime.cli research-report run-1 --format markdown
py -3.11 -m gaon.runtime.cli research-resume run-1
```

The pipeline plans research, collects bounded deterministic evidence, builds cited context, creates review-only knowledge proposals, records approval workflow data, and stores Research Brain run/checkpoint state. It does not use live market data, paid AI providers, Telegram execution, Notion mutation, GitHub mutation, broker APIs, KIS, or MyMoneyGuard.

See `docs/architecture/research-brain.md`, `docs/operations/research-runtime.md`, `docs/operations/free-only-mode.md`, and `docs/releases/gaon-phase-b-v3.0-rc.md`.

## Executive Planner

Sprint 36 adds Executive Planner routing inspection:

```powershell
py -3.11 -m gaon.runtime.cli executive-plan --request "ORB 전략 연구해줘"
py -3.11 -m gaon.runtime.cli executive-plan --request "상태 알려줘" --json
```

Executive Planner produces a routing plan only. It does not execute multi-agent work, scheduler jobs, trades, Telegram actions, or external tools. Execution-capable or policy-changing requests are flagged with `approval_required=true`.

## Multi-Agent Framework

Sprint 37 adds bounded agent execution smoke:

```powershell
py -3.11 -m gaon.runtime.cli agent-run --agent research --request "research context"
py -3.11 -m gaon.runtime.cli agent-run --agent coding --request "inspect code" --json
py -3.11 -m gaon.runtime.cli agent-run --agent memory --request "memory lookup"
```

The dispatcher consumes an `ExecutivePlan`, invokes one explicitly registered agent, validates declared capabilities, isolates failures, emits lifecycle events, and records metrics. It does not add Scheduler execution, daily research automation, Telegram-triggered execution, broker/KIS execution, automatic approval, arbitrary shell execution, or unrestricted filesystem mutation.

## Scheduler Automation

Sprint 38 adds durable scheduled execution smoke:

```powershell
py -3.11 -m gaon.runtime.cli schedule-create --db runtime.sqlite --job-id smoke --name Smoke --request "research evidence" --next-run-at "2026-07-18T00:00:00Z" --agent research
py -3.11 -m gaon.runtime.cli schedule-list --db runtime.sqlite
py -3.11 -m gaon.runtime.cli schedule-show --db runtime.sqlite smoke
py -3.11 -m gaon.runtime.cli schedule-enable --db runtime.sqlite smoke
py -3.11 -m gaon.runtime.cli schedule-disable --db runtime.sqlite smoke
py -3.11 -m gaon.runtime.cli schedule-run-due --db runtime.sqlite --now "2026-07-18T00:00:00Z"
```

Scheduled execution always goes through Executive Planner and Agent Dispatcher. It does not add Daily Research business logic, Telegram delivery, live Trading/KIS execution, automatic approval, paid-provider fallback, or private repository dependencies.

## Daily Research Pipeline

Sprint 39 adds deterministic daily research profiles and runs on top of the existing Sprint 38 scheduler. It creates bounded cited reports and pending-review knowledge proposals only.

```powershell
py -3.11 -m gaon.runtime.cli daily-research-create --db runtime.sqlite --profile-id korea-open --topic "Korea Open" --query "KOSPI opening risk" --next-run-at "2026-07-18T00:00:00Z"
py -3.11 -m gaon.runtime.cli daily-research-list --db runtime.sqlite
py -3.11 -m gaon.runtime.cli daily-research-show --db runtime.sqlite korea-open
py -3.11 -m gaon.runtime.cli daily-research-run --db runtime.sqlite --due --now "2026-07-18T00:00:00Z"
py -3.11 -m gaon.runtime.cli daily-research-report --db runtime.sqlite korea-open --format markdown
py -3.11 -m gaon.runtime.cli daily-research-report --db runtime.sqlite korea-open --format json
py -3.11 -m gaon.runtime.cli daily-research-disable --db runtime.sqlite korea-open
py -3.11 -m gaon.runtime.cli daily-research-enable --db runtime.sqlite korea-open
```

This sprint does not add live Telegram delivery, email, Notion sync, GitHub polling, live market data, Trading Adapter execution, broker/KIS/MyMoneyGuard access, external AI calls, vector DB, automatic approval, shell execution, or plugin execution. See `docs/architecture/daily-research-pipeline.md`.

## Conversational Assistant

Sprint 13 adds a deterministic conversational assistant foundation. Telegram can now send ordinary Korean text such as `안녕`, `가온`, `오늘 시장 어때?`, `삼성전자 분석해줘`, and `백테스트 돌려줘` through the same safe Conversation Runtime.

This is not an LLM integration. No OpenAI SDK, local LLM, API key, market data feed, calendar provider, stock analysis engine, or backtest executor is connected in this sprint. Unsupported or unconnected tasks are acknowledged without pretending that data was queried or work was executed.

## Memory-Aware Conversation

Sprint 14 adds read-only Learning Memory context for research and memory intents. Gaon can summarize related records, warnings, evidence references, conflict state, and revalidation state without mutating the repository or treating confidence as approval.

## Assistant Provider

Sprint 15 adds a guarded provider boundary. The default deterministic provider needs no network. The OpenAI-compatible provider uses injectable standard-library HTTP plumbing for future execute-mode use, with fake transports in tests. Provider output is validated and falls back to rule-based responses on failure.

## Research Orchestration

Sprint 16 adds guarded research proposal, approval, run-state, and queue contracts. Research can be planned and approved explicitly, but it is not an autonomous agent loop and does not execute trades, shell commands, arbitrary code, or automatic Learning Memory writes.

## Production Runtime Service

Sprint 17-22 add SQLite-backed runtime state, health/readiness checks, bounded retry helpers, durable queue/scheduler recovery, controlled runtime loop commands, backup/restore hardening, and VPS deployment documentation. The service files are provided for reviewed deployment; this repository does not deploy to VPS automatically.

## Trading Adapter Contract

Sprint 23 adds `gaon.adapters.TradingAdapter` as a broker-free public contract. It defines read-only account, position, market, and runtime status methods plus an approval-gated order command lifecycle. Execution is disabled by default, and no live broker, KIS API, account ID, or MyMoneyGuard private code is connected.

Sprint 40 extends this into a safe paper-only trading foundation:

```powershell
py -3.11 -m gaon.runtime.cli trading-status --db runtime.sqlite
py -3.11 -m gaon.runtime.cli trading-account --db runtime.sqlite
py -3.11 -m gaon.runtime.cli trading-positions --db runtime.sqlite
py -3.11 -m gaon.runtime.cli trading-simulate-buy --db runtime.sqlite --symbol 005930 --quantity 1 --price 70000
py -3.11 -m gaon.runtime.cli trading-simulate-sell --db runtime.sqlite --symbol 005930 --quantity 1 --price 70000
py -3.11 -m gaon.runtime.cli trading-history --db runtime.sqlite
```

Live trading is not implemented. The public repository still has no KIS REST, KIS WebSocket, broker authentication, real account access, real balance query, real order execution, automatic trading, automatic approval, MyMoneyGuard integration, live market data, or Telegram trading command support. See `docs/architecture/trading-adapter-foundation.md` and `docs/operations/PaperTrading.md`.

## v1 Backtest Adapter

Sprint 41 adds a safe adapter boundary for future v1 backtest reuse. The real v1 backtest engine is not required for automated tests. Sprint 41 defines the safe adapter boundary and deterministic integration path.

```powershell
py -3.11 -m gaon.runtime.cli backtest-status --db runtime.sqlite
py -3.11 -m gaon.runtime.cli backtest-list-strategies --db runtime.sqlite
py -3.11 -m gaon.runtime.cli backtest-run --db runtime.sqlite --strategy turtle_v5 --dataset sample_krx --start 2024-01-01 --end 2026-01-01
py -3.11 -m gaon.runtime.cli backtest-history --db runtime.sqlite
```

This sprint does not implement Champion/Challenger ranking, strategy promotion, active strategy switching, paper trading promotion, live strategy deployment, KIS integration, MyMoneyGuard integration, automatic trading, automatic approval, arbitrary shell execution, network calls, or private repository dependency. See `docs/architecture/backtest-adapter-foundation.md` and `docs/operations/BacktestAdapter.md`.

## Strategy Validation Engine

Sprint 42 validates normalized Sprint 41 `BacktestResult` records with a deterministic, versioned policy.

```powershell
py -3.11 -m gaon.runtime.cli validation-policy-show
py -3.11 -m gaon.runtime.cli validation-run --db runtime.sqlite --backtest-id backtest-result:<fingerprint>
py -3.11 -m gaon.runtime.cli validation-show --db runtime.sqlite validation:backtest-result:<fingerprint>
py -3.11 -m gaon.runtime.cli validation-history --db runtime.sqlite
```

Validation outputs `PASS`, `FAIL`, or `REVIEW`. `validation_policy_v1` requires reproducibility metadata, a sufficient sample period, a minimum trade count, bounded MDD, and available optional metrics according to policy. MDD is normalized internally as a positive fraction, so `-0.20`, `0.20`, and `20.0` all mean 20%.

Validation PASS does not automatically promote or deploy a strategy. Sprint 42 does not implement Champion ranking, Challenger ranking, active strategy switching, automatic paper trading promotion, live KIS, broker orders, automatic trading, automatic approval, MyMoneyGuard integration, network access, or paid-provider fallback. See `docs/architecture/StrategyValidationEngine.md` and `docs/operations/ValidationPolicy.md`.

## Champion / Challenger Evaluation

Sprint 43 compares a current Champion backtest result with a Challenger backtest result and the Challenger's persisted Sprint 42 validation report.

```powershell
py -3.11 -m gaon.runtime.cli champion-policy-show
py -3.11 -m gaon.runtime.cli champion-evaluate --db runtime.sqlite --champion-backtest-id <id> --challenger-backtest-id <id> --validation-id <id>
py -3.11 -m gaon.runtime.cli champion-evaluation-show --db runtime.sqlite <evaluation_id>
py -3.11 -m gaon.runtime.cli champion-evaluation-history --db runtime.sqlite
```

Possible decisions are `KEEP_CHAMPION`, `PROMOTION_CANDIDATE`, and `REVIEW`. `PROMOTION_CANDIDATE` is not `PROMOTED`; Sprint 43 does not switch active strategies, promote automatically, trade, approve, connect to live KIS, place broker orders, or access MyMoneyGuard. See `docs/architecture/champion-challenger-evaluation.md` and `docs/operations/ChampionChallengerEvaluation.md`.

## Champion Registry

Sprint 44 records the active Champion only after explicit approval. The required sequence is `PROMOTION_CANDIDATE -> Promotion Request -> Explicit Approval -> Champion Registry`.

```bash
python -m gaon.runtime.cli champion-bootstrap --db runtime.sqlite --strategy turtle_v5 --fingerprint <fingerprint> --backtest-id <backtest_id>
python -m gaon.runtime.cli champion-promotion-request --db runtime.sqlite --evaluation-id <evaluation_id>
python -m gaon.runtime.cli champion-promotion-approve --db runtime.sqlite <promotion_id>
python -m gaon.runtime.cli champion-registry-show --db runtime.sqlite
python -m gaon.runtime.cli champion-history --db runtime.sqlite
python -m gaon.runtime.cli champion-rollback --db runtime.sqlite
```

Rejected promotion requests never change the active Champion. Rollback creates a new auditable history version and never deletes prior records. Sprint 44 does not connect to live KIS, broker orders, active trading, automatic approval, or MyMoneyGuard. See `docs/architecture/champion-registry.md` and `docs/operations/ChampionRegistry.md`.

## Paper Forward Test

Sprint 45 connects the approved active Champion to paper-only forward-test sessions.

```bash
python -m gaon.runtime.cli paper-session-create --db runtime.sqlite --session-id paper1
python -m gaon.runtime.cli paper-session-start --db runtime.sqlite paper1
python -m gaon.runtime.cli paper-session-simulate-order --db runtime.sqlite --session-id paper1 --symbol 005930 --quantity 1 --price 70000 --side buy
python -m gaon.runtime.cli paper-session-summary --db runtime.sqlite paper1
python -m gaon.runtime.cli paper-session-complete --db runtime.sqlite paper1
```

Only the currently active Champion version can create or run a paper session. Stale former Champions, unapproved Promotion Candidates, and fingerprint mismatches are rejected. Sprint 45 does not implement live KIS, real broker orders, paper-to-live promotion, automatic Champion modification from paper results, or MyMoneyGuard access. See `docs/architecture/paper-forward-test.md` and `docs/operations/PaperForwardTest.md`.

## Paper Revalidation

Sprint 46 evaluates paper forward-test summaries with `paper_revalidation_policy_v1`.

```bash
python -m gaon.runtime.cli paper-revalidation-policy-show
python -m gaon.runtime.cli paper-revalidate --db runtime.sqlite --session-id paper1
python -m gaon.runtime.cli paper-revalidation-show --db runtime.sqlite <revalidation_id>
python -m gaon.runtime.cli paper-revalidation-history --db runtime.sqlite
```

`LIVE_ELIGIBLE` is a technical future-live consideration signal only. `KILL` and `ROLLBACK_RECOMMENDED` do not automatically trade, rollback, change the Champion Registry, or approve anything. See `docs/architecture/paper-revalidation.md` and `docs/operations/PaperRevalidation.md`.

## Strategy Execution Runtime

Sprint 47 adds explicit execution mode planning and runs.

```bash
python -m gaon.runtime.cli execution-policy-show
python -m gaon.runtime.cli execution-plan --db runtime.sqlite --mode paper
python -m gaon.runtime.cli execution-run --db runtime.sqlite --plan-id <plan_id>
python -m gaon.runtime.cli execution-plan --db runtime.sqlite --mode live --revalidation-id <revalidation_id>
python -m gaon.runtime.cli execution-history --db runtime.sqlite
```

Default execution mode is `DISABLED`. PAPER execution reuses the existing paper adapter stack. LIVE execution remains `BLOCKED` in Sprint 47 because the live broker adapter is unavailable. See `docs/architecture/strategy-execution-runtime.md` and `docs/operations/StrategyExecutionRuntime.md`.

## Module Structure

- `gaon.learning`: Learning Memory, Evidence, Knowledge, Experience, Policy, and Confidence contracts
- `gaon.learning.repository`: deterministic in-memory Learning Memory repository contract for tests
- `gaon.learning.detection`: duplicate and conflict candidate detection without automatic merge or resolution
- `gaon.learning.retrieval`: deterministic related-memory ranking with score breakdown
- `gaon.learning.integration`: Research Brain to Learning Memory candidate preparation without automatic save
- `gaon.runtime`: configuration, event bus, deterministic Korean conversation runtime, assistant provider boundary, notifications, reports, scheduler, safe CLI
- `gaon.runtime.memory_context`: read-only Learning Memory context builder for conversation
- `gaon.runtime.providers`: deterministic and OpenAI-compatible guarded assistant providers
- `gaon.research.orchestrator`: guarded research proposal, approval, run, and queue contracts
- `gaon.runtime.storage`: SQLite runtime state for offsets, processed messages, scheduler state, research state, audit events, and notification attempts
- `gaon.runtime.service`: production runtime service boundary and health checks
- `gaon.runtime.provider_registry`: explicit assistant provider registration and deterministic fallback
- `gaon.runtime.plugins`: explicit allowlist plugin lifecycle
- `gaon.runtime.metrics`: internal metrics collector and snapshot export
- `gaon.runtime.event_store`: durable append-only event store and safe replay
- `gaon.runtime.executive_planner`: Executive Planner request, plan, routing, provider-backed planning, event, and metrics contracts
- `gaon.runtime.agents`: bounded agent contracts, explicit registry, dispatcher, deterministic initial agents, event, and metrics contracts
- `gaon.runtime.scheduled_automation`: durable scheduled jobs, scheduled runs, safe due execution, events, and metrics contracts
- `gaon.learning.long_term_memory`: namespace/lifecycle long-term memory foundation
- `gaon.adapters`: broker-free TradingAdapter protocol, safe v1 BacktestAdapter protocol, deterministic Strategy Validation Engine, Champion/Challenger Evaluation Engine, Champion Registry, Paper Forward Test, Paper Revalidation, Strategy Execution Runtime, fake/paper adapters, and deterministic adapter tests
- `gaon.integrations.telegram`: Telegram Bot API smoke client, dry-run contracts, update parsing, and conversation bridge
- `gaon.integrations.notion`: Notion dry-run mapper and sync contracts
- `gaon.research`: Research Goal, Plan, Session, Interview, Journal, validated planning, evidence search, evidence context, knowledge proposals, approval workflow, and Research Brain v3 orchestration contracts
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

The v1 rollout path is read-only -> paper -> shadow -> approval-gated execution, and it requires a future private-repository implementation plus explicit review before any production connection.

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
- `docs/architecture/GaonDevelopmentContract.md`: Sprint 11 to Sprint 20 execution contract
- `docs/architecture/MasterBlueprint.md`: StrategyLab v2 master blueprint
- `docs/architecture/SprintRoadmap.md`: sprint operating roadmap
- `docs/adr/ADR-0001-learning-memory-core.md`: Learning Memory architecture decision
- `docs/rfc/RFC-0001-sprint11-learning-engine.md`: Sprint 11 Learning Engine RFC
- `docs/rfc/RFC-0002-sprint11-research-brain.md`: Sprint 11 Research Brain RFC
- `docs/rfc/RFC-0004-gaon-runtime-collaboration.md`: Gaon Runtime collaboration RFC
- `docs/architecture/GaonRuntimeArchitecture.md`: Runtime architecture
- `docs/architecture/ConversationRuntime.md`: Conversation Runtime contract
- `docs/architecture/CollaborationIntegrations.md`: Telegram and Notion dry-run integration contracts
- `docs/architecture/executive-planner.md`: Sprint 36 Executive Planner architecture
- `docs/architecture/multi-agent-framework.md`: Sprint 37 Multi-Agent Execution Framework architecture
- `docs/architecture/scheduler-automation.md`: Sprint 38 Scheduler Automation architecture
- `docs/architecture/research-brain.md`: Phase B Research Brain v3 architecture
- `docs/operations/research-runtime.md`: Research runtime smoke commands
- `docs/operations/free-only-mode.md`: free-only mode and paid-provider guardrails
- `docs/releases/gaon-phase-b-v3.0-rc.md`: Phase B v3.0 release candidate notes
- `docs/research/ResearchBrain.md`: Research Brain guide
