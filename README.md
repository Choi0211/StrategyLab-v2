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
- `gaon.learning.long_term_memory`: namespace/lifecycle long-term memory foundation
- `gaon.adapters`: broker-free TradingAdapter protocol, risk-gate contracts, and fake adapter tests
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
- `docs/architecture/research-brain.md`: Phase B Research Brain v3 architecture
- `docs/operations/research-runtime.md`: Research runtime smoke commands
- `docs/operations/free-only-mode.md`: free-only mode and paid-provider guardrails
- `docs/releases/gaon-phase-b-v3.0-rc.md`: Phase B v3.0 release candidate notes
- `docs/research/ResearchBrain.md`: Research Brain guide
