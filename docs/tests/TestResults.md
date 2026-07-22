# StrategyLab v2 Test Results

Status: Passed

## Sprint 56-60 LLM Agent

- Provider tests: fake OpenAI-compatible content and tool-call responses.
- Tool calling tests: single tool, multi-tool, unknown tool, malformed/denied tool, tool limit.
- Multi-turn tests: Champion, Runtime, v5 pipeline follow-ups and stale result refresh.
- Planner tests: safe multi-step, overflow, approval boundary, repository round-trip.
- Security tests: shell, SQL, secret, approval, deployment, broker-order prompt injection.

## Sprint 51-55 LLM Brain

- Unit: LLM conversation, contextual memory orchestration, safe tools, CLI hardening.
- Integration: Telegram conversational agent, persistent offset reuse, duplicate protection, restart replay prevention.
- Release verification: `python scripts/verify_release.py`

## Sprint 47 Strategy Execution Runtime

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 308 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.unit.test_strategy_execution tests.unit.test_runtime_service`
  - Result: `Ran 11 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 57 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.integration.test_strategy_execution_flow`
  - Result: `Ran 2 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `paper_revalidation_policy_v1`
  - `strategy_execution_policy_v1`
- CLI smoke: Passed
  - `db-check --db <temp>`
  - `paper-revalidation-policy-show`
  - `paper-revalidate`
  - `execution-policy-show`
  - `execution-plan --mode paper`
  - `execution-run`
  - `execution-plan --mode live`
- `git diff --check`: Passed
- Coverage:
  - default mode `DISABLED`
  - missing Champion blocked
  - stale Champion blocked
  - PAPER plan allowed for active Champion
  - PAPER execution reuses existing adapter stack
  - HOLD blocks LIVE
  - KILL blocks execution
  - ROLLBACK_RECOMMENDED blocks LIVE
  - LIVE_ELIGIBLE still blocked because broker adapter is unavailable
  - persistence and restart recovery
  - v17-to-v18 migration
  - events, metrics, and CLI smoke
- Safety:
  - no live KIS
  - no broker credentials
  - no real orders
  - live disabled by default
  - no automatic Champion promotion
  - no automatic rollback
  - no automatic approval
  - no MyMoneyGuard dependency

## Sprint 46 Paper Revalidation and Kill/Rollback Gates

- Unit tests: Passed
  - Targeted command: `PYTHONPATH=src python -m unittest tests.unit.test_paper_revalidation tests.unit.test_runtime_service`
  - Result: `Ran 12 tests`
  - Status: `OK`
- Integration tests: Passed
  - Targeted command: `PYTHONPATH=src python -m unittest tests.integration.test_paper_revalidation_flow`
  - Result: `Ran 2 tests`
  - Status: `OK`
- Coverage:
  - completed healthy paper session -> `LIVE_ELIGIBLE`
  - incomplete session -> `HOLD`
  - insufficient trades -> `HOLD`
  - excessive drawdown -> `KILL`
  - critical execution error -> `KILL`
  - fingerprint mismatch -> `KILL`
  - moderate drawdown deterioration -> `ROLLBACK_RECOMMENDED`
  - missing optional metrics -> `REVIEW`
  - deterministic repeated report
  - events and metrics
  - persistence and v16-to-v17 migration
  - CLI smoke for policy, revalidate, show, and history
- Safety:
  - no live KIS
  - no broker credentials
  - no real orders
  - no automatic rollback
  - no automatic approval
  - no Champion Registry mutation
  - no MyMoneyGuard dependency

## Sprint 45 Paper Trading Forward Test

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 297 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.unit.test_paper_forward tests.unit.test_champion_registry tests.unit.test_runtime_service`
  - Result: `Ran 17 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 53 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.integration.test_paper_forward_flow tests.integration.test_champion_registry_flow`
  - Result: `Ran 4 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `import gaon.adapters.champion_registry`
  - `import gaon.adapters.paper_forward`
- CLI smoke: Passed
  - `db-check --db <temp>`
  - `champion-bootstrap`
  - `paper-session-create`
  - `paper-session-start`
  - `paper-session-simulate-order`
  - `paper-session-summary`
  - `paper-session-complete`
- `git diff --check`: Passed
- Coverage:
  - only active Champion can create a paper session
  - stale Champion rejected
  - fingerprint mismatch rejected
  - lifecycle transitions
  - duplicate start handling
  - pause and resume
  - cancel and complete
  - PaperTradingAdapter stack reused
  - deterministic performance summary
  - events and metrics
  - persistence round trip
  - v15-to-v16 migration
  - CLI smoke
  - live intent remains approval-blocked
- Safety:
  - no live KIS
  - no broker credentials
  - no real orders
  - no automatic trading
  - no automatic approval
  - no Paper-to-Live automatic promotion
  - no MyMoneyGuard dependency

## Sprint 44 Champion Registry and Approval Promotion

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 292 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.unit.test_champion_registry tests.unit.test_champion_challenger tests.unit.test_runtime_service`
  - Result: `Ran 17 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 51 tests`
  - Targeted command: `PYTHONPATH=src python -m unittest tests.integration.test_champion_registry_flow tests.integration.test_champion_challenger_flow`
  - Result: `Ran 5 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Coverage:
  - explicit first Champion bootstrap
  - duplicate bootstrap rejection
  - valid promotion request from `promotion_candidate`
  - `keep_champion`, `review`, and missing evaluations rejected
  - approval updates active Champion
  - rejection leaves Champion unchanged
  - duplicate approval idempotency
  - history preservation
  - rollback to previous Champion
  - rollback without previous Champion rejected
  - persistence round trip
  - v14-to-v15 migration
  - events, metrics, and CLI smoke
- Safety:
  - no automatic Champion promotion
  - no direct `PROMOTION_CANDIDATE` activation
  - no active strategy switching
  - no live KIS
  - no broker orders
  - no automatic trading
  - no automatic approval
  - no MyMoneyGuard dependency

## Sprint 43 Champion / Challenger Evaluation Engine

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 286 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.unit.test_champion_challenger`
  - Result: `Ran 5 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 49 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.integration.test_champion_challenger_flow`
  - Result: `Ran 3 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `import gaon.adapters.champion`
- CLI smoke: Passed
  - `champion-policy-show`
  - `db-check --db :memory:`
  - backtest persistence -> validation persistence -> champion-evaluate -> champion-evaluation-show -> champion-evaluation-history
- Coverage:
  - Validation PASS Challenger evaluation
  - Validation FAIL -> KEEP_CHAMPION
  - Validation REVIEW -> REVIEW
  - identical fingerprint blocking
  - return improvement threshold
  - MDD degradation threshold
  - profit factor comparison
  - missing optional metric handling
  - score cannot override hard gates
  - deterministic repeated evaluation
  - persistence, event emission, metrics, CLI smoke, planner route, and v13-to-v14 migration
- Safety:
  - no automatic Champion promotion
  - no active strategy switching
  - no live KIS
  - no broker credentials
  - no real orders
  - no automatic trading
  - no automatic approval
  - no MyMoneyGuard dependency
  - no arbitrary shell execution
  - no paid-provider fallback

## Sprint 42 Strategy Validation Engine

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 281 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.unit.test_strategy_validation_engine`
  - Result: `Ran 8 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 46 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.integration.test_strategy_validation_flow`
  - Result: `Ran 4 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `import gaon.adapters.validation`
- CLI smoke: Passed
  - `validation-policy-show`
  - `db-check --db :memory:`
  - backtest-run -> validation-run -> validation-show -> validation-history
- Coverage:
  - strong result PASS
  - excessive MDD FAIL
  - insufficient trade count FAIL
  - missing optional metric REVIEW
  - missing fingerprint FAIL
  - short sample period REVIEW
  - deterministic score
  - hard-fail overrides high score
  - overfitting heuristic warning
  - invalid drawdown range rejection
  - multi-run aggregation and catastrophic window detection
  - event emission, metrics, persistence round trip, CLI smoke, Research Agent route, and v12-to-v13 migration
- Safety:
  - no Champion promotion
  - no active strategy switching
  - no live KIS
  - no broker orders
  - no automatic trading
  - no automatic approval
  - no MyMoneyGuard dependency
  - no paid-provider fallback

## Hotfix Telegram Runtime Worker and systemd Service

- Unit tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Full result: `Ran 273 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.unit.test_runtime_service`
  - Result: `Ran 6 tests`
  - Status: `OK`
- Integration tests: Passed
  - Full command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Full result: `Ran 42 tests`
  - Targeted command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest tests.integration.test_runtime_service_flow`
  - Result: `Ran 3 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `gaon.runtime.cli run --once --db :memory:`
- systemd validation: Passed
  - `ExecStart` points to persistent `gaon.runtime.cli run --db /var/lib/strategylab/gaon-runtime.sqlite`
- Scope:
  - `GaonRuntimeService` can run a bounded Telegram polling tick
  - persisted Telegram offset is reused
  - duplicate updates do not resend
  - disabled and dry-run runtime does not call the live Telegram network
  - transient Telegram failures are recorded without terminating the runtime
  - `run --once` performs one bounded tick
  - systemd runs persistent `gaon.runtime.cli run --db /var/lib/strategylab/gaon-runtime.sqlite`
  - no live KIS, real trading, automatic approval, MyMoneyGuard dependency, or paid provider fallback

## Hotfix Telegram Poll Offset Persistence

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 270 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 40 tests`
  - Status: `OK`
- Targeted Telegram tests: Passed
  - Unit: `Ran 14 tests`
  - Integration: `Ran 8 tests`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `telegram-poll-once --dry-run --db runtime.sqlite`
- Scope:
  - existing SQLiteTelegramStateRepository reused
  - saved offset used when explicit `--offset` is omitted
  - explicit `--offset` has precedence
  - processed message duplicate protection prevents repeated replies
  - sent, duplicate, unauthorized, and ignored updates advance offset safely
  - no MyMoneyGuard, private repository, live trading, or security gate changes

## Sprint 41 v1 Backtest Adapter Foundation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 265 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 39 tests`
  - Status: `OK`
- Targeted Sprint 41 tests: Passed
  - Unit: `Ran 6 tests`
  - Integration: `Ran 3 tests`
- Scope:
  - schema v12 migration from v11
  - safe BacktestAdapter contract
  - deterministic fake adapter
  - local process boundary tests for timeout, non-zero exit, invalid JSON, and bounded output
  - normalized result contract, optional metric handling, fingerprint reproducibility, persistence, duplicate request protection, lifecycle events, metrics, Executive Planner to Research Agent flow, and CLI smoke
  - no Champion promotion, active strategy switching, live KIS, broker credentials, real orders, MyMoneyGuard dependency, arbitrary shell execution, network access, paid AI APIs, or private repository dependency

## Sprint 40 Trading Adapter Foundation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 259 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 36 tests`
  - Status: `OK`
- Targeted Sprint 40 tests: Passed
  - Unit: `Ran 7 tests`
  - Integration: `Ran 4 tests`
- Scope:
  - schema v11 migration from v10
  - structured trading request/result contracts
  - fake and paper adapter behavior
  - risk guardrails
  - Executive Planner to Trading Agent to PaperTradingAdapter flow
  - durable events, metrics, persistence, duplicate request protection, CLI smoke, live intent blocking, approval-required blocking, and adapter failure isolation
  - no live KIS, broker credentials, real account access, real orders, automatic trading, automatic approval, MyMoneyGuard dependency, live market data, Telegram trading commands, paid-provider fallback, or unrestricted shell execution

## Sprint 39 Daily Research Pipeline

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 252 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 32 tests`
  - Status: `OK`
- Targeted Sprint 39 tests: Passed
  - Unit: `Ran 6 tests`
  - Integration: `Ran 2 tests`
- Scope:
  - schema v10 migration from v9
  - durable profile/run storage
  - Sprint 38 scheduler integration without a second scheduler
  - deterministic bounded evidence, context, report, pending-review proposal, events, metrics, CLI smoke, duplicate run protection, disabled skip, and failure isolation
  - no Telegram delivery, email, Notion sync, GitHub polling, live market data, Trading Adapter execution, broker/KIS/MyMoneyGuard access, external AI calls, vector DB, automatic approval, shell execution, or plugin execution

## Sprint 38 Scheduler Automation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 246 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 30 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `from gaon.runtime import ScheduledAutomationRunner, ScheduledJobRepository, ScheduledRunStatus`
- CLI smoke: Passed
  - `schedule-create`
  - `schedule-list`
  - `schedule-show`
  - `schedule-run-due`
- Migration tests: Passed
  - schema v8 to v9
- Scope:
  - durable scheduled job management, due execution through Executive Planner and Agent Dispatcher, approval blocking, bounded retry, duplicate run protection, lifecycle events, and metrics
  - no Daily Research business logic, Telegram delivery, live Trading/KIS, automatic approval, paid-provider fallback, or private repository dependency

## Sprint 37 Multi-Agent Execution Framework

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 239 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 27 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Import smoke: Passed
  - `from gaon.runtime import AgentDispatcher, AgentRegistry, AgentRequest, AgentStatus, default_agent_registry`
- CLI smoke: Passed
  - `agent-run --agent research --request`
  - `agent-run --agent coding --request --json`
  - `agent-run --agent memory --request`
- Scope:
  - Agent contracts, registry, dispatcher, deterministic initial agents, capability validation, approval blocking, event emission, and metrics
  - no scheduler execution, daily research automation, Telegram-triggered execution, broker/KIS execution, automatic approval, arbitrary shell execution, or dynamic plugin loading

## Sprint 36 Executive Planner

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 231 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 22 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `executive-plan --request`
  - `executive-plan --request --json`
- Scope:
  - ExecutiveRequest, ExecutivePlan, RoutingDecision, AgentSelection, ToolSelection, and ExecutivePlanner contracts
  - deterministic and provider-backed planning through the existing Provider Registry
  - free-only enforcement and approval-required flag support
  - durable event helper and runtime metrics integration
  - no multi-agent execution, scheduler execution, trading adapter execution, or Telegram integration

## Gaon Phase B v3.0 Research Brain Release Candidate

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 224 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 21 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `config-check`
  - `health`
  - `db-check`
  - `status`
  - `metrics`
  - `event-replay-dry-run`
  - `research-plan`
  - `research-run --dry-run`
  - `research-proposals-list`
- Scope:
  - validated research planning
  - safe evidence providers
  - evidence ranking and context building
  - evidence-backed knowledge proposals
  - auditable approval workflow
  - Research Brain v3 orchestration, schema v8, checkpoints, reports, and free-only defaults
  - no live Telegram/OpenAI/Notion/GitHub/Broker/KIS/MyMoneyGuard validation

## Gaon Phase A v2.1 Release Candidate

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 207 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 17 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `config-check`
  - `health`
  - `db-check`
  - `status`
  - `metrics`
  - `event-replay-dry-run`
- Scope:
  - provider registry and routing
  - explicit plugin lifecycle
  - internal metrics and observability
  - durable event store and replay
  - long-term memory foundation
  - runtime integration
  - no live Telegram/OpenAI/Notion/Broker/VPS validation

## Sprint 18-23 v2 Completion Release Candidate

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 183 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 15 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - approval replay/tamper/cross-scope guards
  - SQLite repository and migration coverage
  - durable queue, scheduler, and recovery coverage
  - controlled runtime loop and CLI smoke coverage
  - security and chaos coverage
  - TradingAdapter contract and fake adapter tests
  - no live Telegram/OpenAI/Notion/Broker verification

## Sprint 17 Production Runtime Service

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 165 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 15 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- CLI smoke: Passed
  - `config-check`
  - `health`
  - `db-check`
- Scope:
  - SQLite schema migration and runtime state store
  - restart offset recovery
  - duplicate processed message guard
  - bounded retry policy
  - health/readiness/db checks
  - backup helper
  - systemd/VPS deployment documentation
  - no real deployment or network smoke

## Sprint 16 Guarded Research Assistant Orchestration

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 162 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 14 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - deterministic research proposal creation
  - approval actor/chat/token/expiry checks
  - approval-gated run state machine
  - queue deduplication and retry limits
  - audit event recording
  - no autonomous execution or Learning Memory mutation

## Sprint 15 Guarded Assistant Provider Integration

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 158 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 13 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - provider contracts and metadata
  - deterministic fallback provider
  - OpenAI-compatible fake HTTP provider
  - prompt injection separation
  - provider timeout/malformed response fallback
  - provider safety validation
  - no real network calls

## Sprint 14 Memory-Aware Conversation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 152 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 12 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - read-only Learning Memory context builder
  - STRICT/BROAD/GLOBAL retrieval fallback
  - conflict and revalidation warnings
  - confidence used only as ranking signal
  - Telegram memory query fake flow
  - no repository mutation

## Sprint 13 Conversational Assistant Foundation

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 148 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 11 tests`
  - Status: `OK`
- Scope:
  - Korean natural-language intent routing
  - Gaon persona responses that address the user as `영하님`
  - deterministic `rule_based` assistant route without LLM dependencies
  - Assistant Provider Protocol boundary for future providers
  - safety warnings for approval, order, and execution-like requests
  - Telegram ordinary text to Conversation Runtime to Telegram response flow
  - no external AI SDK, API key, market data, calendar, stock analysis, or backtest executor connection

## Telegram Production Connection

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 139 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 10 tests`
  - Status: `OK`
- Scope:
  - Telegram Bot API standard-library client
  - fake HTTP success paths for `getMe`, `getUpdates`, and `sendMessage`
  - HTTP 401/429/500, malformed JSON, `ok=false`, timeout, and token masking
  - chat discovery deduplication and preview limiting
  - private text update parsing and ignored update handling
  - allowed chat enforcement, unauthorized no-send behavior, and offset reporting
  - smoke-send fixed message and arbitrary text exclusion
  - production CLI execution gates with dry-run default
  - no real Telegram network call, no shell execution, no GitHub mutation, no broker/trading import

## Gaon Runtime Collaboration

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 130 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 6 tests`
  - Status: `OK`
- Scope:
  - runtime configuration and secret masking
  - Windows-safe timezone validation for `UTC` and `Asia/Seoul`
  - invalid boolean/mode/time/weekday rejection
  - explicit CLI dry-run/execute flag behavior
  - event bus duplicate/failure isolation
  - conversation intents and approval safety
  - Telegram dry-run authorization and formatting
  - Notion dry-run mapping and idempotency
  - notification, daily/weekly reports, scheduler, CLI
  - Learning Memory claims snapshot and retrieval modes

## Sprint 12-B

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 119 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 2 tests`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - `InMemoryLearningRepository`
  - duplicate and conflict candidate detection
  - chronological lookup and AND filters
  - append-only audit workflow
  - UTC timestamp validation
  - golden JSON and migration fixtures
  - approval scope mismatch guards
  - related-memory retrieval score breakdown
  - repository JSON export/import and v0 migration
  - Research Brain conversion and no-auto-save preparation workflow

## Sprint 12-A

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 94 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 1 test`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - Learning Memory domain contracts added.
  - EvidenceRecord is reused from the existing `gaon.learning.evidence` contract.
  - KnowledgeApproval and PolicyApproval are separate contracts.
  - ConfidenceScore is a review and retrieval signal only and cannot approve knowledge, policy, or preference changes.
  - UserPreference automatic delete and overwrite are blocked.
  - Versioned JSON round-trip and fail-closed schema checks are covered.

## Sprint 11

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/unit`
  - Result: `Ran 85 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 1 test`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
- Scope:
  - Gaon Development Contract added.
  - Learning Memory replaces Research Memory terminology for Sprint 11 planning.
  - `gaon.learning` package boundary added.
  - Learning Memory, Evidence, Knowledge, Experience, Policy, and Confidence contracts added.
  - ADR and RFC added for Learning Memory core.
  - Research Brain package added with Goal, Plan, Session, Interview, and Journal contracts.
  - Research Brain hardening added session transition guards, terminal completed sessions, pending interview answers, and versioned JSON round-trip.
  - ADR-0003, RFC-0002, and Research Brain guide added.

## Sprint 1

- Unit tests: Passed
  - Command: `PYTHONPATH=src python -m unittest discover -s tests/unit`
  - Result: `Ran 7 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 10

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 69 tests`
  - Status: `OK`
- Integration tests: Passed
  - Command: `PYTHONPATH=src;tests/unit;tests/integration python -m unittest discover -s tests/integration`
  - Result: `Ran 1 test`
  - Status: `OK`
- Release verification: Passed
  - Command: `python scripts/verify_release.py`
  - Result: `Unit tests: PASS`, `Integration tests: PASS`, `Required files: PASS`
  - Required documentation now includes `docs/architecture/GaonPlatformMasterSpecification.md`
- Gaon Platform specification check: Passed
  - Scope: top-level Gaon Platform master development specification added and linked from README, Master Blueprint, Sprint Roadmap, and release verification.
- Research validation: N/A
- Secret check: Passed

## Sprint 9

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 68 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 8

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 65 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 7

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 64 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 6

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 60 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed
  - Checked tracked and staged candidate files for forbidden secret patterns.
  - No `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, secret files, or log files were detected.

## Sprint 2

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 25 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed
  - Checked tracked and staged candidate files for forbidden secret patterns.
  - No `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, secret files, log files, or private data dumps were detected.

## Sprint 5

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 54 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed

## Sprint 4

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 48 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: Passed
  - Scope: known-scenario deterministic fixture only.
- Secret check: Passed
  - Checked tracked and staged candidate files for forbidden secret patterns.
  - No `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, secret files, log files, or private data dumps were detected.

## Sprint 3

- Unit tests: Passed
  - Command: `PYTHONPATH=src;tests/unit python -m unittest discover -s tests/unit`
  - Result: `Ran 40 tests`
  - Status: `OK`
- Integration tests: N/A
- Research validation: N/A
- Secret check: Passed
  - Checked tracked and staged candidate files for forbidden secret patterns.
  - No `.env`, `.env.*` except `.env.example`, `kis_token.json`, token JSON, account JSON, trade state JSON, secret files, log files, or private data dumps were detected.
# Sprint 48

Local targeted verification:

- unit tests
- integration tests
- `scripts/verify_release.py`

# Sprint 49

Final local verification:

- full unit tests: PASS, 320 tests
- full integration tests: PASS, 60 tests
- `scripts/verify_release.py`: PASS
- import smoke: PASS
- CLI smoke: PASS, `deployment-status --db :memory:`

# Sprint 50

Final local verification:

- full unit tests: PASS, 320 tests
- full integration tests: PASS, 65 tests
- Sprint 50 E2E tests: PASS
- `scripts/verify_release.py`: PASS
- import smoke: PASS
- CLI smoke: PASS, `v5-release-check`, `v5-status`, and `v5-demo --dry-run`
- migration tests: PASS, v20 to v21 and fresh DB schema v21
- git diff --check: PASS
- security audit: PASS, no `shell=True`, private MyMoneyGuard path hardcoding, subprocess use, or secret markers in new v5 files

# Sprint 50 Hotfix

Final local verification:

- repeated `v5-demo --dry-run` on the same persistent DB: PASS, 3 consecutive runs after `v5-release-check`
- full unit tests: PASS, 320 tests
- full integration tests: PASS, 67 tests
- Sprint 50 E2E tests: PASS, 7 tests
- `scripts/verify_release.py`: PASS
- CLI smoke: PASS, `v5-release-check`, 3 repeated `v5-demo --dry-run`, and `v5-pipeline-history`
- migration tests: PASS via Sprint 50 E2E v20 to v21 and fresh DB schema checks
- git diff --check: PASS

# Sprint 61-70

Final local verification:

- full unit tests: PASS, 398 tests
- full integration tests: PASS, 75 tests
- `scripts/verify_release.py`: PASS
- `conversation-release-check`: PASS, schema v28, 9 safe tools
- `llm-agent-release-check`: PASS, plan status completed
- `external-research-release-check`: PASS, SSRF guard and strategy research advisory flow
- `strategy-research-demo`: PASS, recommendation generated without automatic promotion
- `git diff --check`: PASS

# Sprint 71-80

Final local verification:

- full unit tests: PASS, 407 tests
- full integration tests: PASS, 76 tests
- `scripts/verify_release.py`: PASS
- `conversation-release-check`: PASS, schema v29, 10 safe tools
- `llm-agent-release-check`: PASS
- `external-research-release-check`: PASS
- `strategy-research-demo`: PASS
- `quant-research-release-check`: PASS
- `quant-research-demo`: PASS
- deterministic/Telegram/LLM tool regression: PASS
- `git diff --check`: PASS

# Sprint 81-90

Final local verification:

- full unit tests: PASS, 413 tests
- full integration tests: PASS, 77 tests
- `scripts/verify_release.py`: PASS
- `conversation-release-check`: PASS, schema v30, 11 safe tools
- `llm-agent-release-check`: PASS
- `external-research-release-check`: PASS
- `strategy-research-demo`: PASS
- `quant-research-release-check`: PASS
- `quant-research-demo`: PASS
- `feature-discovery-release-check`: PASS
- `feature-discovery-demo`: PASS
- `ai-scientist-release-check`: PASS
- `ai-scientist-demo`: PASS
- `git diff --check`: PASS, with Windows LF-to-CRLF working-copy warnings only

# Hotfix 90.1

Final local verification:

- full unit tests: PASS, 422 tests
- full integration tests: PASS, 77 tests
- targeted Telegram/LLM regression: PASS, 29 tests
- `scripts/verify_release.py`: PASS
- `long-response-release-check`: PASS, schema v30, 3 chunks, 1 continuation
- `conversation-release-check`: PASS
- `llm-agent-release-check`: PASS
- `external-research-release-check`: PASS
- `quant-research-release-check`: PASS
- `feature-discovery-release-check`: PASS
- `ai-scientist-release-check`: PASS
- `git diff --check`: PASS
