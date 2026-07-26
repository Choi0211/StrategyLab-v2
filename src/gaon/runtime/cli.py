"""Safe runtime CLI."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
import sys
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from gaon.adapters.backtest import BacktestExecutionContext, BacktestExecutionService, FakeBacktestAdapter, SQLiteBacktestRepository, build_backtest_request
from gaon.adapters.champion import ChampionChallengerEvaluationEngine, ChampionChallengerPolicy, SQLiteChampionChallengerRepository, build_champion_challenger_request
from gaon.adapters.champion_registry import ChampionRegistryService, ChampionRollbackRequest, SQLiteChampionRegistryRepository
from gaon.adapters.paper_forward import PaperTradingForwardTestService, SQLitePaperTradingSessionRepository
from gaon.adapters.paper_revalidation import PaperRevalidationEngine, PaperRevalidationPolicy, SQLitePaperRevalidationRepository, build_paper_revalidation_request
from gaon.adapters.strategy_deployment import FakeStrategyDeploymentAdapter, LocalSafeStrategyDeploymentAdapter, SQLiteStrategyDeploymentRepository, StrategyDeploymentPolicy, StrategyDeploymentService, build_strategy_deployment_request
from gaon.adapters.strategy_handoff import SQLiteStrategyHandoffRepository, StrategyHandoffService, build_strategy_handoff_request, safe_handoff_export_path
from gaon.adapters.strategy_execution import SQLiteStrategyExecutionRepository, StrategyExecutionMode, StrategyExecutionPolicy, StrategyExecutionRuntime, build_strategy_execution_request
from gaon.adapters.trading import PaperTradingAdapter, SQLiteTradingRepository, TradingExecutionService, TradingIntent, TradingRiskPolicy, build_trading_request
from gaon.adapters.validation import SQLiteValidationRepository, StrategyValidationEngine, ValidationPolicy, build_validation_request
from gaon.integrations.telegram.client import TelegramBotApiClient
from gaon.integrations.telegram.contracts import TelegramClient, TelegramDiscoveredChat, TelegramPollResult
from gaon.integrations.telegram.formatter import split_message
from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import discover_private_chats, parse_update_result
from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantToolCall, ProviderCapabilities, ProviderHealth, ProviderTimeoutError
from gaon.runtime.agents import AgentDispatcher, AgentRequest, default_agent_registry
from gaon.runtime.agent_planner import AgentPlanExecutor, AgentPlanner, AgentPlanPolicy
from gaon.runtime.config import GaonRuntimeConfig, load_runtime_config
from gaon.runtime.conversation import ConversationRuntime
from gaon.runtime.daily_research import DailyResearchPipeline, DailyResearchProfile, DailyResearchRepository, record_daily_research_profile_metric, daily_research_event
from gaon.runtime.errors import ConfigurationError, GaonRuntimeError
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.executive_planner import AgentSelection, DeterministicExecutivePlanner, ExecutivePlan, ExecutiveRequest, RoutingDecision, ToolSelection, executive_plan_event
from gaon.runtime.external_research import ExternalResearchError, ExternalResearchTool, validate_external_url
from gaon.runtime.health import readiness
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, ToolDefinition, ToolRegistry, ToolResult, ToolRiskLevel, default_tool_registry
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.provider_registry import build_assistant_provider
from gaon.runtime.research_grounding import contains_fixture_leakage, contains_unverified_fixture_metrics, contains_wrapper_tags, format_grounded_tool_response, looks_like_english_final, strict_real_research_grounding_violations
from gaon.runtime.reports import build_daily_report, build_weekly_review
from gaon.runtime.repositories import TelegramStateRepository
from gaon.runtime.scheduled_automation import ScheduleDefinition, ScheduledAutomationRunner, ScheduledJob, ScheduledJobRepository, record_scheduled_job_metric, scheduled_event
from gaon.runtime.serialization import dumps_json
from gaon.runtime.service import GaonRuntimeService
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_agent import TelegramConversationAgent
from gaon.runtime.telegram_worker import TelegramPollingWorker
from gaon.runtime.v5_pipeline import GaonV5PipelineOrchestrator, GaonV5PipelineRequest, SQLiteGaonV5PipelineRepository
from gaon.research.orchestration_v3 import ResearchOrchestratorV3, SQLiteResearchRunRepository
from gaon.research.quant_scientist import AIScientistOrchestrator, SQLiteAIScientistRepository, feature_discovery_payload
from gaon.research.quant_research import QuantResearchOrchestrator, SQLiteQuantResearchRepository
from gaon.research.self_improving import (
    AutonomousResearchOrchestrator,
    AutonomousResearchRequest,
    ResearchCritic,
    ResearchIterationLoop,
    ResearchQualityScorer,
    ResearchTournamentRunner,
    SQLiteResearchMemoryRepository,
    StrategyImprovementPlanner,
    build_memory_entry,
    fixture_candidate,
    fixture_candidates,
)
from gaon.research.real_research import (
    BacktestDatasetReference,
    BacktestExecutionAssumptions,
    BacktestRequest,
    BacktestStrategySpec,
    DataQualityEngine,
    DeterministicExternalBacktestAdapter,
    FixtureMarketDataProvider,
    RealResearchGateway,
    RealResearchRequest,
    SQLiteDatasetRegistry,
    SQLiteRealResearchRepository,
    turtle_strategy_spec,
)
from gaon.research.krx_real_pipeline import (
    EvidenceBasedStrategyCritic,
    KRXDatasetBuilder,
    KRXFixtureMarketDataProvider,
    RealAutonomousResearchPipeline,
    RealMarketDataUnavailable,
    RuleBasedBacktestEngine,
    UserStrategyParser,
    WalkForwardValidator,
    build_market_data_provider_from_env,
    default_execution_assumptions,
    historical_krx_calendar_release_check,
    krx_trading_calendar_release_check,
    provider_gap_release_check,
    real_krx_data_release_check,
)
from gaon.research.autonomous_retest import (
    AutonomousRetestOrchestrator,
    SQLiteAutonomousRetestRepository,
    autonomous_retest_release_check,
    research_retest_history_payload,
    research_retest_status_payload,
)
from gaon.research.operations import (
    ApprovalStatus as ResearchConfigApprovalStatus,
    QualityStatus,
    RecommendationDecision,
    ResearchOperationsService,
    SQLiteResearchOperationRepository,
    fixture_evidence_pair,
    operation_report_markdown,
)
from gaon.research.strategy_research import StrategyResearchOrchestrator, SQLiteStrategyResearchRepository

TELEGRAM_SMOKE_TEXT = "Gaon Telegram 연결 테스트가 성공했습니다."
TELEGRAM_POLL_OFFSET_KEY = "__telegram_poll__"


def _configure_cli_text_streams() -> None:
    _configure_text_stream(sys.stdout)
    _configure_text_stream(sys.stderr)


def _configure_text_stream(stream: object) -> None:
    reconfigure = getattr(stream, "reconfigure", None)
    if not callable(reconfigure):
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (TypeError, ValueError, OSError):
        return


def main(argv: list[str] | None = None) -> int:
    _configure_cli_text_streams()
    parser = argparse.ArgumentParser(prog="gaon.runtime")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("config-check")
    db_check = sub.add_parser("db-check")
    db_check.add_argument("--db", default=":memory:")
    health = sub.add_parser("health")
    health.add_argument("--db", default=":memory:")
    ready = sub.add_parser("readiness")
    ready.add_argument("--db", default=":memory:")
    run = sub.add_parser("run")
    run.add_argument("--db", default=":memory:")
    run.add_argument("--once", action="store_true", default=False)
    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--db", default=":memory:")
    assistant_status = sub.add_parser("assistant-status")
    assistant_status.add_argument("--db", default=":memory:")
    assistant_provider_status = sub.add_parser("assistant-provider-status")
    assistant_provider_status.add_argument("--db", default=":memory:")
    conversation_status = sub.add_parser("conversation-status")
    conversation_status.add_argument("--db", default=":memory:")
    conversation_status.add_argument("--session-id", default=None)
    tool_registry = sub.add_parser("tool-registry-show")
    tool_registry.add_argument("--db", default=":memory:")
    tool_registry.add_argument("--json", action="store_true")
    tool_audit = sub.add_parser("tool-audit-history")
    tool_audit.add_argument("--db", default=":memory:")
    tool_audit.add_argument("--tool-name", default=None)
    tool_audit.add_argument("--json", action="store_true")
    conversation_release = sub.add_parser("conversation-release-check")
    conversation_release.add_argument("--db", default=":memory:")
    conversation_release.add_argument("--run-id", default=None)
    agent_status = sub.add_parser("agent-status")
    agent_status.add_argument("--db", default=":memory:")
    agent_plan_history = sub.add_parser("agent-plan-history")
    agent_plan_history.add_argument("--db", default=":memory:")
    tool_chain_history = sub.add_parser("tool-chain-history")
    tool_chain_history.add_argument("--db", default=":memory:")
    llm_agent_release = sub.add_parser("llm-agent-release-check")
    llm_agent_release.add_argument("--db", default=":memory:")
    long_response_release = sub.add_parser("long-response-release-check")
    long_response_release.add_argument("--db", default=":memory:")
    external_release = sub.add_parser("external-research-release-check")
    external_release.add_argument("--db", default=":memory:")
    strategy_research_demo = sub.add_parser("strategy-research-demo")
    strategy_research_demo.add_argument("--db", default=":memory:")
    strategy_research_demo.add_argument("--request", default="Research a safer Korean market breakout challenger")
    strategy_research_demo.add_argument("--run-id", default="strategy-research-demo")
    strategy_research_demo.add_argument("--timeframe", default="daily")
    strategy_research_demo.add_argument("--json", action="store_true")
    quant_research_release = sub.add_parser("quant-research-release-check")
    quant_research_release.add_argument("--db", default=":memory:")
    quant_research_demo = sub.add_parser("quant-research-demo")
    quant_research_demo.add_argument("--db", default=":memory:")
    quant_research_demo.add_argument("--symbol", default="KOSPI")
    quant_research_demo.add_argument("--report-id", default="quant-research-demo")
    quant_research_demo.add_argument("--json", action="store_true")
    feature_discovery_demo = sub.add_parser("feature-discovery-demo")
    feature_discovery_demo.add_argument("--db", default=":memory:")
    feature_discovery_demo.add_argument("--symbol", default="KOSPI")
    feature_discovery_demo.add_argument("--json", action="store_true")
    feature_discovery_release = sub.add_parser("feature-discovery-release-check")
    feature_discovery_release.add_argument("--db", default=":memory:")
    ai_scientist_demo = sub.add_parser("ai-scientist-demo")
    ai_scientist_demo.add_argument("--db", default=":memory:")
    ai_scientist_demo.add_argument("--symbol", default="KOSPI")
    ai_scientist_demo.add_argument("--report-id", default="ai-scientist-demo")
    ai_scientist_demo.add_argument("--json", action="store_true")
    ai_scientist_release = sub.add_parser("ai-scientist-release-check")
    ai_scientist_release.add_argument("--db", default=":memory:")
    research_critic_demo = sub.add_parser("research-critic-demo")
    research_critic_demo.add_argument("--db", default=":memory:")
    research_critic_demo.add_argument("--scenario", default="overfit")
    research_critic_demo.add_argument("--json", action="store_true")
    research_memory_demo = sub.add_parser("research-memory-demo")
    research_memory_demo.add_argument("--db", default=":memory:")
    research_memory_demo.add_argument("--json", action="store_true")
    research_iteration_demo = sub.add_parser("research-iteration-demo")
    research_iteration_demo.add_argument("--db", default=":memory:")
    research_iteration_demo.add_argument("--max-iterations", type=int, default=3)
    research_iteration_demo.add_argument("--json", action="store_true")
    research_tournament_demo = sub.add_parser("research-tournament-demo")
    research_tournament_demo.add_argument("--db", default=":memory:")
    research_tournament_demo.add_argument("--top-n", type=int, default=3)
    research_tournament_demo.add_argument("--json", action="store_true")
    autonomous_research_demo = sub.add_parser("autonomous-research-demo")
    autonomous_research_demo.add_argument("--db", default=":memory:")
    autonomous_research_demo.add_argument("--request", default="Research a safer volume breakout strategy")
    autonomous_research_demo.add_argument("--run-id", default=None)
    autonomous_research_demo.add_argument("--json", action="store_true")
    self_improving_release = sub.add_parser("self-improving-research-release-check")
    self_improving_release.add_argument("--db", default=":memory:")
    market_data_demo = sub.add_parser("market-data-demo")
    market_data_demo.add_argument("--db", default=":memory:")
    market_data_demo.add_argument("--symbol", default="005930")
    market_data_demo.add_argument("--start", default="2026-07-01")
    market_data_demo.add_argument("--end", default="2026-07-10")
    market_data_demo.add_argument("--json", action="store_true")
    data_quality_demo = sub.add_parser("data-quality-demo")
    data_quality_demo.add_argument("--db", default=":memory:")
    data_quality_demo.add_argument("--symbol", default="005930")
    data_quality_demo.add_argument("--json", action="store_true")
    backtest_contract_demo = sub.add_parser("backtest-contract-demo")
    backtest_contract_demo.add_argument("--db", default=":memory:")
    backtest_contract_demo.add_argument("--symbol", default="005930")
    backtest_contract_demo.add_argument("--json", action="store_true")
    external_backtest_demo = sub.add_parser("external-backtest-demo")
    external_backtest_demo.add_argument("--db", default=":memory:")
    external_backtest_demo.add_argument("--symbol", default="005930")
    external_backtest_demo.add_argument("--json", action="store_true")
    real_research_demo = sub.add_parser("real-research-demo")
    real_research_demo.add_argument("--db", default=":memory:")
    real_research_demo.add_argument("--symbol", default="005930")
    real_research_demo.add_argument("--request-id", default=None)
    real_research_demo.add_argument("--json", action="store_true")
    real_research_release = sub.add_parser("real-research-integration-release-check")
    real_research_release.add_argument("--db", default=":memory:")
    research_grounding_release = sub.add_parser("research-grounding-release-check")
    research_grounding_release.add_argument("--db", default=":memory:")
    research_grounding_release.add_argument("--run-id", default=None)
    research_context_release = sub.add_parser("research-context-isolation-release-check")
    research_context_release.add_argument("--db", default=":memory:")
    research_context_release.add_argument("--run-id", default=None)
    korean_response_release = sub.add_parser("korean-response-release-check")
    korean_response_release.add_argument("--db", default=":memory:")
    korean_response_release.add_argument("--run-id", default=None)
    strict_real_grounding_release = sub.add_parser("strict-real-research-grounding-release-check")
    strict_real_grounding_release.add_argument("--db", default=":memory:")
    strict_real_grounding_release.add_argument("--run-id", default=None)
    telegram_strict_real_release = sub.add_parser("telegram-strict-real-research-release-check")
    telegram_strict_real_release.add_argument("--db", default=":memory:")
    telegram_strict_real_release.add_argument("--run-id", default=None)
    authoritative_renderer_release = sub.add_parser("authoritative-renderer-grounding-release-check")
    authoritative_renderer_release.add_argument("--db", default=":memory:")
    authoritative_renderer_release.add_argument("--run-id", default=None)
    structural_authoritative_release = sub.add_parser("structural-authoritative-grounding-release-check")
    structural_authoritative_release.add_argument("--db", default=":memory:")
    structural_authoritative_release.add_argument("--run-id", default=None)
    telegram_failure_release = sub.add_parser("telegram-real-research-failure-routing-release-check")
    telegram_failure_release.add_argument("--db", default=":memory:")
    telegram_failure_release.add_argument("--run-id", default=None)
    strategy_parser_release = sub.add_parser("strategy-parser-release-check")
    strategy_parser_release.add_argument("--db", default=":memory:")
    real_backtest_release = sub.add_parser("real-backtest-release-check")
    real_backtest_release.add_argument("--db", default=":memory:")
    krx_real_research_demo = sub.add_parser("krx-real-research-demo")
    krx_real_research_demo.add_argument("--db", default=":memory:")
    krx_real_research_demo.add_argument("--request", default="20일 고가 돌파 + 종가 > MA20 > MA60 + 거래량 >= 20일 평균 이상, 손절 -5%, 10일 저점 이탈 청산")
    krx_real_research_demo.add_argument("--symbol", default="005930")
    krx_real_research_demo.add_argument("--json", action="store_true")
    krx_real_research_release = sub.add_parser("krx-real-research-release-check")
    krx_real_research_release.add_argument("--db", default=":memory:")
    real_krx_data_release = sub.add_parser("real-krx-data-release-check")
    real_krx_data_release.add_argument("--db", default=":memory:")
    real_krx_data_release.add_argument("--symbol", default="005930")
    real_krx_data_release.add_argument("--start", default="2025-01-01")
    real_krx_data_release.add_argument("--end", default="2026-07-24")
    krx_calendar_release = sub.add_parser("krx-trading-calendar-release-check")
    krx_calendar_release.add_argument("--db", default=":memory:")
    historical_krx_calendar_release = sub.add_parser("historical-krx-calendar-release-check")
    historical_krx_calendar_release.add_argument("--db", default=":memory:")
    provider_gap_release = sub.add_parser("provider-gap-release-check")
    provider_gap_release.add_argument("--db", default=":memory:")
    research_ops_demo = sub.add_parser("research-ops-demo")
    research_ops_demo.add_argument("--db", default=":memory:")
    research_ops_demo.add_argument("--insufficient-sample", action="store_true")
    research_ops_demo.add_argument("--persist", action="store_true", default=False)
    research_ops_demo.add_argument("--json", action="store_true")
    research_ops_release = sub.add_parser("research-ops-release-check")
    research_ops_release.add_argument("--db", default=":memory:")
    research_ops_approve = sub.add_parser("research-config-approve")
    research_ops_approve.add_argument("--db", default=":memory:")
    research_ops_approve.add_argument("--report-id", required=True)
    research_ops_approve.add_argument("--actor-ref", required=True)
    research_ops_rollback = sub.add_parser("research-config-rollback")
    research_ops_rollback.add_argument("--db", default=":memory:")
    research_ops_rollback.add_argument("--config-id", required=True)
    research_ops_rollback.add_argument("--actor-ref", required=True)
    research_ops_report = sub.add_parser("research-ops-report")
    research_ops_report.add_argument("--db", default=":memory:")
    research_ops_report.add_argument("--report-id", default=None)
    research_ops_report.add_argument("--include-artifacts", action="store_true", default=False)
    research_ops_report.add_argument("--json", action="store_true")
    research_ops_cleanup = sub.add_parser("research-ops-cleanup")
    research_ops_cleanup.add_argument("--db", default=":memory:")
    research_ops_cleanup.add_argument("--dry-run", action="store_true", default=False)
    research_ops_cleanup.add_argument("--apply", action="store_true", default=False)
    research_ops_cleanup.add_argument("--json", action="store_true")
    retest_demo = sub.add_parser("research-retest-demo")
    retest_demo.add_argument("--db", default=":memory:")
    retest_demo.add_argument("--request", default="20일 고가 돌파 종가 > MA20 > MA60 거래량 20일 평균 이상 손절 -5% 10일 저점 이탈 청산")
    retest_demo.add_argument("--symbol", default="005930")
    retest_demo.add_argument("--persist", action="store_true", default=False)
    retest_demo.add_argument("--json", action="store_true")
    retest_release = sub.add_parser("autonomous-retest-release-check")
    retest_release.add_argument("--db", default=":memory:")
    telegram_retest_release = sub.add_parser("telegram-retest-persistence-release-check")
    telegram_retest_release.add_argument("--db", default=":memory:")
    retest_status = sub.add_parser("research-retest-status")
    retest_status.add_argument("--db", default=":memory:")
    retest_status.add_argument("--limit", type=int, default=5)
    retest_status.add_argument("--json", action="store_true")
    retest_history = sub.add_parser("research-retest-history")
    retest_history.add_argument("--db", default=":memory:")
    retest_history.add_argument("--run-id", default=None)
    retest_history.add_argument("--limit", type=int, default=20)
    retest_history.add_argument("--json", action="store_true")
    backup = sub.add_parser("backup")
    backup.add_argument("--db", default="runtime.sqlite")
    backup.add_argument("--destination", required=True)
    sub.add_parser("metrics")
    replay = sub.add_parser("event-replay-dry-run")
    replay.add_argument("--db", default=":memory:")
    executive_plan = sub.add_parser("executive-plan")
    executive_plan.add_argument("--request", required=True)
    executive_plan.add_argument("--db", default=":memory:")
    executive_plan.add_argument("--json", action="store_true")
    agent_run = sub.add_parser("agent-run")
    agent_run.add_argument("--agent", choices=("research", "coding", "memory", "trading"), required=True)
    agent_run.add_argument("--request", required=True)
    agent_run.add_argument("--db", default=":memory:")
    agent_run.add_argument("--json", action="store_true")
    schedule_create = sub.add_parser("schedule-create")
    schedule_create.add_argument("--db", default="runtime.sqlite")
    schedule_create.add_argument("--job-id", required=True)
    schedule_create.add_argument("--name", required=True)
    schedule_create.add_argument("--request", required=True)
    schedule_create.add_argument("--next-run-at", required=True)
    schedule_create.add_argument("--agent", choices=("research", "memory", "coding", "trading"), required=False)
    schedule_create.add_argument("--approval-required", action="store_true")
    schedule_list = sub.add_parser("schedule-list")
    schedule_list.add_argument("--db", default="runtime.sqlite")
    schedule_show = sub.add_parser("schedule-show")
    schedule_show.add_argument("--db", default="runtime.sqlite")
    schedule_show.add_argument("job_id")
    schedule_enable = sub.add_parser("schedule-enable")
    schedule_enable.add_argument("--db", default="runtime.sqlite")
    schedule_enable.add_argument("job_id")
    schedule_disable = sub.add_parser("schedule-disable")
    schedule_disable.add_argument("--db", default="runtime.sqlite")
    schedule_disable.add_argument("job_id")
    schedule_run_due = sub.add_parser("schedule-run-due")
    schedule_run_due.add_argument("--db", default="runtime.sqlite")
    schedule_run_due.add_argument("--now", required=False)
    daily_research_create = sub.add_parser("daily-research-create")
    daily_research_create.add_argument("--db", default="runtime.sqlite")
    daily_research_create.add_argument("--profile-id", required=True)
    daily_research_create.add_argument("--topic", required=True)
    daily_research_create.add_argument("--query", required=True)
    daily_research_create.add_argument("--next-run-at", required=True)
    daily_research_create.add_argument("--priority", type=int, default=50)
    daily_research_create.add_argument("--source", action="append", default=None)
    daily_research_create.add_argument("--time-range", default="daily")
    daily_research_create.add_argument("--language", default="ko-KR")
    daily_research_list = sub.add_parser("daily-research-list")
    daily_research_list.add_argument("--db", default="runtime.sqlite")
    daily_research_show = sub.add_parser("daily-research-show")
    daily_research_show.add_argument("--db", default="runtime.sqlite")
    daily_research_show.add_argument("profile_id")
    daily_research_enable = sub.add_parser("daily-research-enable")
    daily_research_enable.add_argument("--db", default="runtime.sqlite")
    daily_research_enable.add_argument("profile_id")
    daily_research_disable = sub.add_parser("daily-research-disable")
    daily_research_disable.add_argument("--db", default="runtime.sqlite")
    daily_research_disable.add_argument("profile_id")
    daily_research_run = sub.add_parser("daily-research-run")
    daily_research_run.add_argument("--db", default="runtime.sqlite")
    daily_research_run.add_argument("--profile-id", required=False)
    daily_research_run.add_argument("--due", action="store_true")
    daily_research_run.add_argument("--now", required=False)
    daily_research_report = sub.add_parser("daily-research-report")
    daily_research_report.add_argument("--db", default="runtime.sqlite")
    daily_research_report.add_argument("profile_id")
    daily_research_report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    trading_status = sub.add_parser("trading-status")
    trading_status.add_argument("--db", default="runtime.sqlite")
    trading_account = sub.add_parser("trading-account")
    trading_account.add_argument("--db", default="runtime.sqlite")
    trading_positions = sub.add_parser("trading-positions")
    trading_positions.add_argument("--db", default="runtime.sqlite")
    trading_buy = sub.add_parser("trading-simulate-buy")
    trading_buy.add_argument("--db", default="runtime.sqlite")
    trading_buy.add_argument("--symbol", required=True)
    trading_buy.add_argument("--quantity", type=float, required=True)
    trading_buy.add_argument("--price", type=float, required=True)
    trading_sell = sub.add_parser("trading-simulate-sell")
    trading_sell.add_argument("--db", default="runtime.sqlite")
    trading_sell.add_argument("--symbol", required=True)
    trading_sell.add_argument("--quantity", type=float, required=True)
    trading_sell.add_argument("--price", type=float, required=True)
    trading_cancel = sub.add_parser("trading-cancel-simulated-order")
    trading_cancel.add_argument("--db", default="runtime.sqlite")
    trading_cancel.add_argument("--request-id", required=True)
    trading_history = sub.add_parser("trading-history")
    trading_history.add_argument("--db", default="runtime.sqlite")
    backtest_status = sub.add_parser("backtest-status")
    backtest_status.add_argument("--db", default="runtime.sqlite")
    backtest_strategies = sub.add_parser("backtest-list-strategies")
    backtest_strategies.add_argument("--db", default="runtime.sqlite")
    backtest_run = sub.add_parser("backtest-run")
    backtest_run.add_argument("--db", default="runtime.sqlite")
    backtest_run.add_argument("--strategy", required=True)
    backtest_run.add_argument("--dataset", required=True)
    backtest_run.add_argument("--start", required=True)
    backtest_run.add_argument("--end", required=True)
    backtest_show = sub.add_parser("backtest-show")
    backtest_show.add_argument("--db", default="runtime.sqlite")
    backtest_show.add_argument("result_id")
    backtest_history = sub.add_parser("backtest-history")
    backtest_history.add_argument("--db", default="runtime.sqlite")
    validation_run = sub.add_parser("validation-run")
    validation_run.add_argument("--db", default="runtime.sqlite")
    validation_source = validation_run.add_mutually_exclusive_group(required=True)
    validation_source.add_argument("--backtest-id")
    validation_source.add_argument("--fingerprint")
    validation_show = sub.add_parser("validation-show")
    validation_show.add_argument("--db", default="runtime.sqlite")
    validation_show.add_argument("validation_id")
    validation_history = sub.add_parser("validation-history")
    validation_history.add_argument("--db", default="runtime.sqlite")
    validation_policy = sub.add_parser("validation-policy-show")
    validation_policy.add_argument("--json", action="store_true")
    champion_policy = sub.add_parser("champion-policy-show")
    champion_policy.add_argument("--json", action="store_true")
    champion_evaluate = sub.add_parser("champion-evaluate")
    champion_evaluate.add_argument("--db", default="runtime.sqlite")
    champion_evaluate.add_argument("--champion-backtest-id", required=True)
    champion_evaluate.add_argument("--challenger-backtest-id", required=True)
    champion_evaluate.add_argument("--validation-id", required=True)
    champion_show = sub.add_parser("champion-evaluation-show")
    champion_show.add_argument("--db", default="runtime.sqlite")
    champion_show.add_argument("evaluation_id")
    champion_history = sub.add_parser("champion-evaluation-history")
    champion_history.add_argument("--db", default="runtime.sqlite")
    registry_show = sub.add_parser("champion-registry-show")
    registry_show.add_argument("--db", default="runtime.sqlite")
    registry_show.add_argument("--slot", default="default")
    registry_history = sub.add_parser("champion-history")
    registry_history.add_argument("--db", default="runtime.sqlite")
    registry_history.add_argument("--slot", default="default")
    bootstrap = sub.add_parser("champion-bootstrap")
    bootstrap.add_argument("--db", default="runtime.sqlite")
    bootstrap.add_argument("--strategy", required=True)
    bootstrap.add_argument("--fingerprint", required=True)
    bootstrap.add_argument("--backtest-id", required=True)
    bootstrap.add_argument("--slot", default="default")
    promotion_request = sub.add_parser("champion-promotion-request")
    promotion_request.add_argument("--db", default="runtime.sqlite")
    promotion_request.add_argument("--evaluation-id", required=True)
    promotion_request.add_argument("--promotion-id", required=False)
    promotion_request.add_argument("--slot", default="default")
    promotion_approve = sub.add_parser("champion-promotion-approve")
    promotion_approve.add_argument("--db", default="runtime.sqlite")
    promotion_approve.add_argument("promotion_id")
    promotion_reject = sub.add_parser("champion-promotion-reject")
    promotion_reject.add_argument("--db", default="runtime.sqlite")
    promotion_reject.add_argument("promotion_id")
    rollback = sub.add_parser("champion-rollback")
    rollback.add_argument("--db", default="runtime.sqlite")
    rollback.add_argument("--slot", default="default")
    rollback.add_argument("--rollback-id", required=False)
    paper_create = sub.add_parser("paper-session-create")
    paper_create.add_argument("--db", default="runtime.sqlite")
    paper_create.add_argument("--session-id", required=True)
    paper_create.add_argument("--slot", default="default")
    paper_create.add_argument("--champion-version-id", required=False)
    paper_create.add_argument("--fingerprint", required=False)
    paper_start = sub.add_parser("paper-session-start")
    paper_start.add_argument("--db", default="runtime.sqlite")
    paper_start.add_argument("session_id")
    paper_show = sub.add_parser("paper-session-show")
    paper_show.add_argument("--db", default="runtime.sqlite")
    paper_show.add_argument("session_id")
    paper_list = sub.add_parser("paper-session-list")
    paper_list.add_argument("--db", default="runtime.sqlite")
    paper_pause = sub.add_parser("paper-session-pause")
    paper_pause.add_argument("--db", default="runtime.sqlite")
    paper_pause.add_argument("session_id")
    paper_resume = sub.add_parser("paper-session-resume")
    paper_resume.add_argument("--db", default="runtime.sqlite")
    paper_resume.add_argument("session_id")
    paper_complete = sub.add_parser("paper-session-complete")
    paper_complete.add_argument("--db", default="runtime.sqlite")
    paper_complete.add_argument("session_id")
    paper_cancel = sub.add_parser("paper-session-cancel")
    paper_cancel.add_argument("--db", default="runtime.sqlite")
    paper_cancel.add_argument("session_id")
    paper_order = sub.add_parser("paper-session-simulate-order")
    paper_order.add_argument("--db", default="runtime.sqlite")
    paper_order.add_argument("--session-id", required=True)
    paper_order.add_argument("--symbol", required=True)
    paper_order.add_argument("--quantity", type=float, required=True)
    paper_order.add_argument("--price", type=float, required=True)
    paper_order.add_argument("--side", choices=("buy", "sell"), default="buy")
    paper_summary = sub.add_parser("paper-session-summary")
    paper_summary.add_argument("--db", default="runtime.sqlite")
    paper_summary.add_argument("session_id")
    paper_revalidation_policy = sub.add_parser("paper-revalidation-policy-show")
    paper_revalidation_policy.add_argument("--json", action="store_true")
    paper_revalidate = sub.add_parser("paper-revalidate")
    paper_revalidate.add_argument("--db", default="runtime.sqlite")
    paper_revalidate.add_argument("--session-id", required=True)
    paper_revalidate.add_argument("--revalidation-id", required=False)
    paper_revalidation_show = sub.add_parser("paper-revalidation-show")
    paper_revalidation_show.add_argument("--db", default="runtime.sqlite")
    paper_revalidation_show.add_argument("revalidation_id")
    paper_revalidation_history = sub.add_parser("paper-revalidation-history")
    paper_revalidation_history.add_argument("--db", default="runtime.sqlite")
    execution_policy = sub.add_parser("execution-policy-show")
    execution_policy.add_argument("--json", action="store_true")
    execution_status = sub.add_parser("execution-status")
    execution_status.add_argument("--db", default="runtime.sqlite")
    execution_plan = sub.add_parser("execution-plan")
    execution_plan.add_argument("--db", default="runtime.sqlite")
    execution_plan.add_argument("--mode", choices=("disabled", "paper", "live"), required=True)
    execution_plan.add_argument("--plan-id", required=False)
    execution_plan.add_argument("--revalidation-id", required=False)
    execution_run = sub.add_parser("execution-run")
    execution_run.add_argument("--db", default="runtime.sqlite")
    execution_run.add_argument("--plan-id", required=True)
    execution_show = sub.add_parser("execution-show")
    execution_show.add_argument("--db", default="runtime.sqlite")
    execution_show.add_argument("run_id")
    execution_history = sub.add_parser("execution-history")
    execution_history.add_argument("--db", default="runtime.sqlite")
    handoff_create = sub.add_parser("handoff-create")
    handoff_create.add_argument("--db", default="runtime.sqlite")
    handoff_create.add_argument("--champion-slot", default="default")
    handoff_create.add_argument("--revalidation-id", required=True)
    handoff_create.add_argument("--request-id", required=False)
    handoff_show = sub.add_parser("handoff-show")
    handoff_show.add_argument("--db", default="runtime.sqlite")
    handoff_show.add_argument("package_id")
    handoff_history = sub.add_parser("handoff-history")
    handoff_history.add_argument("--db", default="runtime.sqlite")
    handoff_export = sub.add_parser("handoff-export")
    handoff_export.add_argument("--db", default="runtime.sqlite")
    handoff_export.add_argument("--package-id", required=True)
    handoff_export.add_argument("--output", required=True)
    handoff_approve = sub.add_parser("handoff-approve")
    handoff_approve.add_argument("--db", default="runtime.sqlite")
    handoff_approve.add_argument("package_id")
    handoff_reject = sub.add_parser("handoff-reject")
    handoff_reject.add_argument("--db", default="runtime.sqlite")
    handoff_reject.add_argument("package_id")
    handoff_reject.add_argument("--reason", default="rejected by explicit human review")
    deployment_status = sub.add_parser("deployment-status")
    deployment_status.add_argument("--db", default="runtime.sqlite")
    deployment_plan = sub.add_parser("deployment-plan")
    deployment_plan.add_argument("--db", default="runtime.sqlite")
    deployment_plan.add_argument("--package-id", required=True)
    deployment_plan.add_argument("--request-id", required=False)
    deployment_plan.add_argument("--target-id", default="generic-runtime")
    deployment_run = sub.add_parser("deployment-run")
    deployment_run.add_argument("--db", default="runtime.sqlite")
    deployment_run.add_argument("--plan-id", required=True)
    deployment_run.add_argument("--target-dir", required=False)
    deployment_show = sub.add_parser("deployment-show")
    deployment_show.add_argument("--db", default="runtime.sqlite")
    deployment_show.add_argument("run_id")
    deployment_history = sub.add_parser("deployment-history")
    deployment_history.add_argument("--db", default="runtime.sqlite")
    deployment_backups = sub.add_parser("deployment-backups")
    deployment_backups.add_argument("--db", default="runtime.sqlite")
    v5_status = sub.add_parser("v5-status")
    v5_status.add_argument("--db", default="runtime.sqlite")
    v5_show = sub.add_parser("v5-pipeline-show")
    v5_show.add_argument("--db", default="runtime.sqlite")
    v5_show.add_argument("run_id")
    v5_history = sub.add_parser("v5-pipeline-history")
    v5_history.add_argument("--db", default="runtime.sqlite")
    v5_check = sub.add_parser("v5-release-check")
    v5_check.add_argument("--db", default=":memory:")
    v5_demo = sub.add_parser("v5-demo")
    v5_demo.add_argument("--db", default=":memory:")
    v5_demo.add_argument("--approve-promotion", action="store_true")
    v5_demo.add_argument("--approve-deployment", action="store_true")
    v5_demo.add_argument("--run-id", required=False)
    v5_demo.add_argument("--scenario", choices=("success", "validation_fail", "keep_champion", "promotion_rejected", "paper_hold", "paper_kill"), default="success")
    _add_dry_run_flags(v5_demo)
    sub.add_parser("research-proposals-list")
    show = sub.add_parser("research-proposals-show")
    show.add_argument("proposal_id")
    approve = sub.add_parser("research-proposals-approve")
    approve.add_argument("proposal_id")
    reject = sub.add_parser("research-proposals-reject")
    reject.add_argument("proposal_id")
    revise = sub.add_parser("research-proposals-revise")
    revise.add_argument("proposal_id")
    research_plan = sub.add_parser("research-plan")
    research_plan.add_argument("--query", required=True)
    research_run = sub.add_parser("research-run")
    research_run.add_argument("--query", required=True)
    research_run.add_argument("--dry-run", action="store_true", default=True)
    research_status = sub.add_parser("research-status")
    research_status.add_argument("run_id")
    research_report = sub.add_parser("research-report")
    research_report.add_argument("run_id")
    research_report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    research_resume = sub.add_parser("research-resume")
    research_resume.add_argument("run_id")
    sub.add_parser("telegram-check")
    sub.add_parser("assistant-check")
    sub.add_parser("notion-check")
    _add_dry_run_flags(sub.add_parser("telegram-get-me"))
    _add_dry_run_flags(sub.add_parser("telegram-discover-chat"))
    poll = sub.add_parser("telegram-poll-once")
    poll.add_argument("--db", default="runtime.sqlite")
    poll.add_argument("--offset", type=int, required=False)
    _add_dry_run_flags(poll)
    smoke = sub.add_parser("telegram-send-smoke")
    smoke.add_argument("--chat-id", required=True)
    _add_dry_run_flags(smoke)
    _add_dry_run_flags(sub.add_parser("notion-sync"))
    daily = sub.add_parser("daily-report")
    daily.add_argument("--date", required=False, default="2026-07-17")
    _add_dry_run_flags(daily)
    weekly = sub.add_parser("weekly-review")
    weekly.add_argument("--week-start", required=False, default="2026-07-13")
    _add_dry_run_flags(weekly)
    revalidation = sub.add_parser("revalidation-scan")
    revalidation.add_argument("--at", required=False, default="2026-07-17T00:00:00Z")
    _add_dry_run_flags(revalidation)
    args = parser.parse_args(argv)

    try:
        return _run(args)
    except GaonRuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _run(args: argparse.Namespace) -> int:
    if args.command == "config-check":
        print(load_runtime_config(os.environ).__repr__())
    elif args.command in {"health", "readiness", "db-check"}:
        store = RuntimeStateStore(args.db)
        try:
            for check in readiness(load_runtime_config(os.environ), store):
                print(f"{check.name}: {'ready' if check.ready else 'not-ready'} {check.message}")
        finally:
            store.close()
    elif args.command in {"run", "status"}:
        store = RuntimeStateStore(args.db)
        try:
            config = load_runtime_config(os.environ)
            metrics = MetricsCollector()
            tick = _runtime_tick(config, store, metrics)
            service = GaonRuntimeService(config, store, tick=tick, metrics=metrics)
            if args.command == "run":
                status = service.run_once() if args.once else service.run_forever()
            else:
                status = service.status()
            print(f"running={status.running} ticks={status.ticks} active_workers={status.active_workers}")
        except KeyboardInterrupt:
            print("runtime service stopped")
        finally:
            store.close()
    elif args.command == "assistant-status":
        config = load_runtime_config(os.environ)
        store = RuntimeStateStore(args.db)
        try:
            print(
                "assistant "
                f"enabled={config.assistant_enabled} provider={config.assistant_provider} "
                f"free_only={config.free_only_mode} schema_version={store.status().schema_version}"
            )
        finally:
            store.close()
    elif args.command == "assistant-provider-status":
        config = load_runtime_config(os.environ)
        provider = build_assistant_provider(config)
        health = provider.health()
        print(
            "assistant-provider "
            f"configured={config.assistant_provider} enabled={config.assistant_enabled} "
            f"model={config.assistant_model or 'unset'} base_url={_sanitized_base_url(config.assistant_base_url)} "
            f"health={'ready' if health.available else 'not-ready'} error={health.error or ''}"
        )
    elif args.command == "conversation-status":
        store = RuntimeStateStore(args.db)
        try:
            rows = _conversation_status_rows(store, args.session_id)
            if not rows:
                print("conversation-status: none")
            for row in rows:
                print(f"session_id={row['session_id']} status={row['status']} messages={row['messages']} updated_at={row['updated_at']}")
        finally:
            store.close()
    elif args.command == "tool-registry-show":
        store = RuntimeStateStore(args.db)
        try:
            payload = {
                "tools": [
                    {"name": tool.name, "risk_level": tool.risk_level.value, "required_args": list(tool.required_args), "allowed_args": list(tool.allowed_args)}
                    for tool in default_tool_registry(store._connection).list()
                ]
            }
            if args.json:
                print(_dumps_json(payload))
            else:
                for tool in payload["tools"]:
                    print(f"{tool['name']} risk={tool['risk_level']}")
        finally:
            store.close()
    elif args.command == "tool-audit-history":
        store = RuntimeStateStore(args.db)
        try:
            records = SQLiteToolAuditRepository(store._connection).list(tool_name=args.tool_name)
            payload = {"audit": [{"audit_id": record.audit_id, "tool_name": record.tool_name, "status": record.status, "risk_level": record.risk_level, "created_at": record.created_at} for record in records]}
            if args.json:
                print(_dumps_json(payload))
            elif not records:
                print("tool-audit-history: none")
            else:
                for record in records:
                    print(f"{record.audit_id} tool={record.tool_name} status={record.status} risk={record.risk_level}")
        finally:
            store.close()
    elif args.command == "conversation-release-check":
        config = load_runtime_config(os.environ)
        store = RuntimeStateStore(args.db)
        try:
            tools = default_tool_registry(store._connection).list()
            from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest

            check_config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic")
            brain = LLMConversationBrain(check_config, store.conversations, tool_executor=SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit))
            run_id = args.run_id or f"conversation-release-check:{uuid4().hex}"
            checks = (
                brain.respond(LLMConversationRequest(f"{run_id}:runtime", "cli", "cli", "가온 상태 알려줘", _utc_now(), f"{run_id}:message:runtime")),
                brain.respond(LLMConversationRequest(f"{run_id}:champion", "cli", "cli", "현재 챔피언 상태 알려줘", _utc_now(), f"{run_id}:message:champion")),
                brain.respond(LLMConversationRequest(f"{run_id}:v5", "cli", "cli", "v5 파이프라인 실행 이력 알려줘", _utc_now(), f"{run_id}:message:v5")),
            )
            if {call for response in checks for call in response.tool_calls} != {"runtime_status", "champion_status", "v5_pipeline_history"}:
                raise ConfigurationError("conversation release check failed to route deterministic read-only tools")
            print(
                "conversation-release-check: PASS "
                f"schema_version={store.status().schema_version} provider={config.assistant_provider} "
                f"free_only={config.free_only_mode} tools={len(tools)} run_id={run_id}"
            )
        finally:
            store.close()
    elif args.command == "agent-status":
        config = load_runtime_config(os.environ)
        store = RuntimeStateStore(args.db)
        try:
            print(
                "agent "
                f"schema_version={store.status().schema_version} max_steps={config.assistant_max_planner_steps} "
                f"max_tool_calls={config.assistant_max_tool_calls_per_turn} max_rpm={config.assistant_max_requests_per_minute}"
            )
        finally:
            store.close()
    elif args.command == "agent-plan-history":
        store = RuntimeStateStore(args.db)
        try:
            plans = store.agent_plans.list()
            if not plans:
                print("agent-plan-history: none")
            for plan in plans:
                print(f"{plan.plan_id} status={plan.status.value} steps={len(plan.steps)}")
        finally:
            store.close()
    elif args.command == "tool-chain-history":
        store = RuntimeStateStore(args.db)
        try:
            records = store.tool_audit.list()
            if not records:
                print("tool-chain-history: none")
            for record in records:
                print(f"{record.audit_id} tool={record.tool_name} status={record.status} risk={record.risk_level}")
        finally:
            store.close()
    elif args.command == "llm-agent-release-check":
        config = load_runtime_config(os.environ)
        store = RuntimeStateStore(args.db)
        try:
            planner = AgentPlanner()
            plan = planner.plan("현재 챔피언과 최근 v5 결과를 비교해서 알려줘", created_at=_utc_now())
            status = AgentPlanPolicy(max_steps=config.assistant_max_planner_steps).validate(plan)
            if status.value not in {"created", "requires_human_approval"}:
                raise ConfigurationError("agent planner release check failed")
            result = AgentPlanExecutor(SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit), AgentPlanPolicy(max_steps=config.assistant_max_planner_steps)).execute(plan, actor_ref="cli", now=_utc_now())
            store.agent_plans.put(plan.with_status(result.status), updated_at=_utc_now())
            if result.status.value not in {"completed", "requires_human_approval"}:
                raise ConfigurationError("agent executor release check failed")
            print(f"llm-agent-release-check: PASS schema_version={store.status().schema_version} plan_status={result.status.value}")
        finally:
            store.close()
    elif args.command == "long-response-release-check":
        store = RuntimeStateStore(args.db)
        try:
            from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest

            long_text = "\n\n".join(f"문단 {index}: " + ("한국어 긴 응답 검증 " * 50) for index in range(1, 18))
            chunks = split_message(long_text)
            if len(long_text) < 10000 or len(chunks) < 3:
                raise ConfigurationError("long response fixture did not exceed Telegram chunk threshold")
            if any(len(chunk) > 3900 for chunk in chunks):
                raise ConfigurationError("Telegram chunk exceeded safe limit")
            provider = _LongResponseReleaseProvider()
            brain = LLMConversationBrain(
                GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible", assistant_max_output_tokens=128, assistant_max_continuations=2),
                store.conversations,
                assistant_provider=provider,
            )
            run_id = f"long-response-release-check:{uuid4().hex}"
            response = brain.respond(LLMConversationRequest(run_id, "cli", "cli", "긴 한국어 보고서를 작성해줘", _utc_now(), f"{run_id}:message"))
            if provider.calls != 2 or "마무리 문단" not in response.text:
                raise ConfigurationError("continuation did not complete long response")
            if "hidden reasoning" in response.text or "chain-of-thought" in response.text:
                raise ConfigurationError("reasoning leaked into long response")
            print(f"long-response-release-check: PASS schema_version={store.status().schema_version} chunks={len(chunks)} continuations={provider.calls - 1}")
        finally:
            store.close()
    elif args.command == "external-research-release-check":
        store = RuntimeStateStore(args.db)
        try:
            blocked = False
            try:
                validate_external_url("http://127.0.0.1/latest")
            except ExternalResearchError:
                blocked = True
            if not blocked:
                raise ConfigurationError("external research SSRF guard did not block loopback")
            payload = ExternalResearchTool().search("Korea market breakout", max_results=2, retrieved_at=_utc_now())
            tool_names = {tool.name for tool in default_tool_registry(store._connection).list()}
            required = {"web_search", "news_search", "weather_current", "weather_forecast", "exchange_rate", "market_data"}
            if not required.issubset(tool_names):
                raise ConfigurationError("external research tools are not registered")
            report = StrategyResearchOrchestrator(store._connection).run(
                "Research a safer breakout challenger",
                run_id="external-research-release-check",
                actor_ref="cli",
                requested_at=_utc_now(),
            )
            if report.champion_comparison.get("automatic_promotion") is not False:
                raise ConfigurationError("strategy research attempted automatic promotion")
            print(f"external-research-release-check: PASS schema_version={store.status().schema_version} results={len(payload['results'])} recommendation={report.recommendation.value}")
        finally:
            store.close()
    elif args.command == "strategy-research-demo":
        store = RuntimeStateStore(args.db)
        try:
            report = StrategyResearchOrchestrator(store._connection, repository=SQLiteStrategyResearchRepository(store._connection)).run(
                args.request,
                run_id=args.run_id,
                actor_ref="cli",
                requested_at=_utc_now(),
                timeframe=args.timeframe,
            )
            if args.json:
                print(_dumps_json(report.to_json()))
            else:
                print(
                    "strategy-research-demo: "
                    f"recommendation={report.recommendation.value} "
                    f"backtest={report.backtest_result_id or 'none'} "
                    f"validation={report.validation_id or 'none'}"
                )
        finally:
            store.close()
    elif args.command == "quant-research-release-check":
        store = RuntimeStateStore(args.db)
        try:
            tool_names = {tool.name for tool in default_tool_registry(store._connection).list()}
            if "krx_market_data" not in tool_names:
                raise ConfigurationError("KRX market data tool is not registered")
            report = QuantResearchOrchestrator().run(report_id="quant-research-release-check", generated_at=_utc_now())
            SQLiteQuantResearchRepository(store._connection).put_report(report)
            if any(comparison.automatic_promotion for comparison in report.comparisons):
                raise ConfigurationError("quant research attempted automatic Champion promotion")
            saved = store._connection.execute("SELECT COUNT(*) FROM quant_research_reports WHERE report_id = ?", (report.report_id,)).fetchone()
            if int(saved[0]) != 1:
                raise ConfigurationError("quant research report was not persisted")
            print(f"quant-research-release-check: PASS schema_version={store.status().schema_version} candidates={len(report.candidates)} winners={len(report.evolution_winners)}")
        finally:
            store.close()
    elif args.command == "quant-research-demo":
        store = RuntimeStateStore(args.db)
        try:
            report = QuantResearchOrchestrator().run(symbol=args.symbol, report_id=args.report_id, generated_at=_utc_now())
            SQLiteQuantResearchRepository(store._connection).put_report(report)
            if args.json:
                print(_dumps_json(report.to_json()))
            else:
                print(f"quant-research-demo: candidates={len(report.candidates)} comparisons={len(report.comparisons)} winners={len(report.evolution_winners)}")
        finally:
            store.close()
    elif args.command == "feature-discovery-release-check":
        store = RuntimeStateStore(args.db)
        try:
            tool_names = {tool.name for tool in default_tool_registry(store._connection).list()}
            if "feature_discovery" not in tool_names:
                raise ConfigurationError("feature discovery tool is not registered")
            payload = feature_discovery_payload(symbol="KOSPI", days=60, retrieved_at=_utc_now())
            names = {str(item["name"]) for item in payload["features"]}  # type: ignore[index]
            required = {"volume_change", "volatility_5d", "vwap", "gap", "relative_strength"}
            if names != required:
                raise ConfigurationError("feature discovery did not produce the required feature set")
            print(f"feature-discovery-release-check: PASS schema_version={store.status().schema_version} features={len(names)}")
        finally:
            store.close()
    elif args.command == "feature-discovery-demo":
        store = RuntimeStateStore(args.db)
        try:
            payload = feature_discovery_payload(symbol=args.symbol, days=60, retrieved_at=_utc_now())
            if args.json:
                print(_dumps_json(payload))
            else:
                features = ", ".join(str(item["name"]) for item in payload["features"])  # type: ignore[index]
                print(f"feature-discovery-demo: symbol={args.symbol} features={features}")
        finally:
            store.close()
    elif args.command == "ai-scientist-release-check":
        store = RuntimeStateStore(args.db)
        try:
            report = AIScientistOrchestrator().run(report_id="ai-scientist-release-check", generated_at=_utc_now())
            SQLiteAIScientistRepository(store._connection).put_report(report)
            if bool(report.champion_comparison["automatic_promotion"]):
                raise ConfigurationError("AI Scientist attempted automatic Champion promotion")
            saved = store._connection.execute("SELECT COUNT(*) FROM ai_scientist_reports WHERE report_id = ?", (report.report_id,)).fetchone()
            if int(saved[0]) != 1:
                raise ConfigurationError("AI Scientist report was not persisted")
            print(
                "ai-scientist-release-check: PASS "
                f"schema_version={store.status().schema_version} "
                f"selected_features={len(report.selected_features)} "
                f"walk_forward={len(report.walk_forward)} "
                f"robustness={report.monte_carlo.robustness_score:.3f}"
            )
        finally:
            store.close()
    elif args.command == "ai-scientist-demo":
        store = RuntimeStateStore(args.db)
        try:
            report = AIScientistOrchestrator().run(symbol=args.symbol, report_id=args.report_id, generated_at=_utc_now())
            SQLiteAIScientistRepository(store._connection).put_report(report)
            if args.json:
                print(_dumps_json(report.to_json()))
            else:
                print(
                    "ai-scientist-demo: "
                    f"regime={report.regime.regime.value} "
                    f"strategy={report.meta_strategy.strategy_id} "
                    f"signal={report.ensemble.signal.value} "
                    f"robustness={report.monte_carlo.robustness_score:.3f}"
                )
        finally:
            store.close()
    elif args.command == "research-critic-demo":
        store = RuntimeStateStore(args.db)
        try:
            candidate = fixture_candidate(args.scenario)
            critique = ResearchCritic().evaluate(candidate, created_at=_utc_now())
            plan = StrategyImprovementPlanner().plan(candidate, critique, created_at=_utc_now())
            payload = {"candidate": candidate.to_json(), "critique": critique.to_json(), "improvement_plan": plan.to_json(), "automatic_promotion": False}
            if args.json:
                print(_dumps_json(payload))
            else:
                print(f"research-critic-demo: scenario={args.scenario} decision={critique.decision.value} findings={len(critique.findings)}")
        finally:
            store.close()
    elif args.command == "research-memory-demo":
        store = RuntimeStateStore(args.db)
        try:
            repository = SQLiteResearchMemoryRepository(store._connection)
            candidate = fixture_candidate("balanced", strategy_id=f"memory-demo:{uuid4().hex}")
            critique = ResearchCritic().evaluate(candidate, created_at=_utc_now())
            plan = StrategyImprovementPlanner().plan(candidate, critique, created_at=_utc_now())
            quality = ResearchQualityScorer().score(candidate, critique, created_at=_utc_now())
            entry = build_memory_entry(candidate, critique, plan, quality, run_id=f"research-memory-demo:{uuid4().hex}", created_at=_utc_now())
            repository.add_memory(entry)
            results = repository.search(strategy_family=candidate.family, market=candidate.market, timeframe=candidate.timeframe)
            payload = {"saved": entry.to_json(), "results": [item.to_json() for item in results], "automatic_promotion": False}
            if args.json:
                print(_dumps_json(payload))
            else:
                print(f"research-memory-demo: saved={entry.memory_id} results={len(results)}")
        finally:
            store.close()
    elif args.command == "research-iteration-demo":
        store = RuntimeStateStore(args.db)
        try:
            run_id = f"research-iteration-demo:{uuid4().hex}"
            candidate = fixture_candidate("overfit", strategy_id=f"{run_id}:candidate")
            final, critique, plan, quality, iterations = ResearchIterationLoop().run(candidate, run_id=run_id, max_iterations=args.max_iterations, created_at=_utc_now())
            payload = {"run_id": run_id, "final_candidate": final.to_json(), "critique": critique.to_json(), "improvement_plan": plan.to_json(), "quality": quality.to_json(), "iterations": [item.to_json() for item in iterations], "automatic_promotion": False}
            if args.json:
                print(_dumps_json(payload))
            else:
                print(f"research-iteration-demo: iterations={len(iterations)} final={final.strategy_id} quality={quality.total:.1f}")
        finally:
            store.close()
    elif args.command == "research-tournament-demo":
        store = RuntimeStateStore(args.db)
        try:
            tournament = ResearchTournamentRunner().run(fixture_candidates(6), top_n=args.top_n, created_at=_utc_now())
            payload = {"tournament": tournament.to_json(), "automatic_promotion": False}
            if args.json:
                print(_dumps_json(payload))
            else:
                print(f"research-tournament-demo: top={','.join(tournament.top_n)} rankings={len(tournament.rankings)}")
        finally:
            store.close()
    elif args.command == "autonomous-research-demo":
        store = RuntimeStateStore(args.db)
        try:
            request = AutonomousResearchRequest(
                request_id=f"autonomous-research-request:{uuid4().hex}",
                market="KRX",
                timeframe="daily",
                strategy_family="breakout",
                hypothesis=args.request,
            )
            result = AutonomousResearchOrchestrator(SQLiteResearchMemoryRepository(store._connection)).run(request, run_id=args.run_id, created_at=_utc_now())
            if args.json:
                print(_dumps_json(result.to_json()))
            else:
                print(f"autonomous-research-demo: run_id={result.run_id} quality={result.quality.total:.1f} novelty={result.novelty.value} memory={result.memory_id or 'preserved'}")
        finally:
            store.close()
    elif args.command == "self-improving-research-release-check":
        store = RuntimeStateStore(args.db)
        try:
            tool_names = {tool.name for tool in default_tool_registry(store._connection).list()}
            required_tools = {"research_memory_search", "strategy_critique", "strategy_quality_score", "research_candidate_compare", "research_lineage"}
            if not required_tools.issubset(tool_names):
                raise ConfigurationError("self-improving research tools are not registered")
            run_id = f"self-improving-release-check:{uuid4().hex}"
            request = AutonomousResearchRequest(run_id, "KRX", "daily", "breakout", "Release-check volume breakout improvement")
            result = AutonomousResearchOrchestrator(SQLiteResearchMemoryRepository(store._connection)).run(request, run_id=run_id, created_at=_utc_now())
            if result.quality.total < 0 or result.quality.total > 100:
                raise ConfigurationError("research quality score out of range")
            if "automatic promotion" not in " ".join(result.warnings).casefold():
                raise ConfigurationError("self-improving release check lost safety warning")
            if store.status().schema_version < 31:
                raise ConfigurationError("self-improving research schema was not migrated")
            print(
                "self-improving-research-release-check: PASS "
                f"schema_version={store.status().schema_version} iterations={len(result.iterations)} "
                f"quality={result.quality.total:.1f} tools={len(required_tools)}"
            )
        finally:
            store.close()
    elif args.command == "market-data-demo":
        store = RuntimeStateStore(args.db)
        try:
            provider = FixtureMarketDataProvider()
            dataset = provider.fetch_bars(args.symbol, start_date=args.start, end_date=args.end)
            quality = provider.validate_dataset(dataset)
            SQLiteDatasetRegistry(store._connection).put_dataset(dataset, quality)
            if args.json:
                print(_dumps_json(dataset.to_json()))
            else:
                print(f"market-data-demo: dataset={dataset.dataset_id} bars={len(dataset.bars)} fixture_backed={dataset.metadata.fixture_backed} quality={quality.status.value}")
        finally:
            store.close()
    elif args.command == "data-quality-demo":
        store = RuntimeStateStore(args.db)
        try:
            dataset = FixtureMarketDataProvider().fetch_bars(args.symbol, start_date="2026-07-01", end_date="2026-07-10")
            report = DataQualityEngine().validate(dataset)
            if args.json:
                print(_dumps_json(report.to_json()))
            else:
                print(f"data-quality-demo: dataset={dataset.dataset_id} status={report.status.value} findings={len(report.findings)}")
        finally:
            store.close()
    elif args.command == "backtest-contract-demo":
        store = RuntimeStateStore(args.db)
        try:
            dataset = FixtureMarketDataProvider().fetch_bars(args.symbol, start_date="2026-07-01", end_date="2026-07-10")
            spec = turtle_strategy_spec(args.symbol)
            request = BacktestRequest(
                f"backtest-contract-demo:{uuid4().hex}",
                BacktestStrategySpec(spec),
                BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint),
                BacktestExecutionAssumptions(0.00015, 0.0018, 0.0005),
                _utc_now(),
                "cli",
            )
            payload = {"strategy_spec": spec.to_json(), "request": request.to_json(), "fingerprint": request.fingerprint, "generated_python": False}
            if args.json:
                print(_dumps_json(payload))
            else:
                print(f"backtest-contract-demo: strategy={spec.spec_id} request_fingerprint={request.fingerprint[:16]}")
        finally:
            store.close()
    elif args.command == "external-backtest-demo":
        store = RuntimeStateStore(args.db)
        try:
            provider = FixtureMarketDataProvider()
            dataset = provider.fetch_bars(args.symbol, start_date="2026-07-01", end_date="2026-07-10")
            quality = provider.validate_dataset(dataset)
            SQLiteDatasetRegistry(store._connection).put_dataset(dataset, quality)
            spec = turtle_strategy_spec(args.symbol)
            request = BacktestRequest(
                f"external-backtest-demo:{uuid4().hex}",
                BacktestStrategySpec(spec),
                BacktestDatasetReference(dataset.dataset_id, dataset.fingerprint),
                BacktestExecutionAssumptions(0.00015, 0.0018, 0.0005),
                _utc_now(),
                "cli",
            )
            result = DeterministicExternalBacktestAdapter().run(request, dataset)
            SQLiteRealResearchRepository(store._connection).put_strategy_spec(spec, _utc_now())
            SQLiteRealResearchRepository(store._connection).put_backtest(request, result)
            if args.json:
                print(_dumps_json(result.to_json()))
            else:
                print(f"external-backtest-demo: result={result.result_id} status={result.status.value} source={result.source.value} fixture_backed={result.provenance.get('fixture_backed')}")
        finally:
            store.close()
    elif args.command == "real-research-demo":
        store = RuntimeStateStore(args.db)
        try:
            request_id = args.request_id or f"real-research-demo:{uuid4().hex}"
            report = RealResearchGateway(connection=store._connection).run(RealResearchRequest(request_id, args.symbol, "2026-07-01", "2026-07-10"), generated_at=_utc_now())
            if args.json:
                print(_dumps_json(report.to_json()))
            else:
                print(f"real-research-demo: report={report.report_id} dataset={report.dataset.dataset_id} result={report.backtest_result.status.value} quality={report.data_quality.status.value}")
        finally:
            store.close()
    elif args.command == "real-research-integration-release-check":
        store = RuntimeStateStore(args.db)
        try:
            required_tools = {"market_data_status", "dataset_lookup", "data_quality_check", "backtest_strategy", "backtest_result", "compare_backtests"}
            tool_names = {tool.name for tool in default_tool_registry(store._connection).list()}
            if not required_tools.issubset(tool_names):
                raise ConfigurationError("real research safe tools are not registered")
            report = RealResearchGateway(connection=store._connection).run(RealResearchRequest(f"real-research-release-check:{uuid4().hex}", "005930", "2026-07-01", "2026-07-10"), generated_at=_utc_now())
            if store.status().schema_version < 32:
                raise ConfigurationError("real research schema was not migrated")
            if report.backtest_result.status.value != "completed":
                raise ConfigurationError("real research backtest did not complete")
            if report.backtest_result.provenance.get("fixture_backed") is not True:
                raise ConfigurationError("release check must clearly mark fixture-backed data")
            if report.quality.get("total", -1) < 0 or report.quality.get("total", 101) > 100:
                raise ConfigurationError("quality score out of range")
            if report.comparison.changed_conditions != ("cost_assumptions",):
                raise ConfigurationError("reproducibility comparison did not identify changed cost assumptions")
            print(
                "real-research-integration-release-check: PASS "
                f"schema_version={store.status().schema_version} dataset={report.dataset.dataset_id} "
                f"quality={report.data_quality.status.value} source={report.backtest_result.source.value} tools={len(required_tools)}"
            )
        finally:
            store.close()
    elif args.command == "research-grounding-release-check":
        store = RuntimeStateStore(args.db)
        try:
            from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest

            run_id = args.run_id or f"research-grounding-release-check:{uuid4().hex}"
            brain = LLMConversationBrain(
                GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"),
                store.conversations,
                tool_executor=SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit),
                tool_result_repository=store.conversation_tool_results,
            )
            checks = (
                brain.respond(LLMConversationRequest(f"{run_id}:weakness", "cli", "cli", "이 전략 약점과 리스크 분석해줘", _utc_now(), f"{run_id}:message:weakness")),
                brain.respond(LLMConversationRequest(f"{run_id}:memory", "cli", "cli", "비슷한 전략 연구했어?", _utc_now(), f"{run_id}:message:memory")),
                brain.respond(LLMConversationRequest(f"{run_id}:improve", "cli", "cli", "이 전략 개선해줘", _utc_now(), f"{run_id}:message:improve")),
                brain.respond(LLMConversationRequest(f"{run_id}:quality", "cli", "cli", "전략 품질 점수 설명해줘", _utc_now(), f"{run_id}:message:quality")),
                brain.respond(LLMConversationRequest(f"{run_id}:backtest", "cli", "cli", "백테스트 결과 보여줘", _utc_now(), f"{run_id}:message:backtest")),
            )
            routes = {call for response in checks for call in response.tool_calls}
            if not {"strategy_critique", "research_memory_search", "strategy_quality_score", "backtest_strategy"}.issubset(routes):
                raise ConfigurationError("research grounding release check failed to route required safe tools")
            weakness, memory, improve, quality, backtest = checks
            if contains_unverified_fixture_metrics(weakness.text):
                raise ConfigurationError("weakness response fabricated fixture metrics")
            if "찾지 못했습니다" not in memory.text or "접근 권한" in memory.text or "access" in memory.text.casefold():
                raise ConfigurationError("empty memory response did not report no stored match safely")
            if "가설/개선 제안" not in improve.text:
                raise ConfigurationError("improvement request was blocked by empty memory")
            if contains_unverified_fixture_metrics(quality.text) or "Sharpe" in quality.text or "MDD" in quality.text:
                raise ConfigurationError("quality response used non-quality fields")
            if "fixture_backed=true" not in backtest.text or "validation_backend=fixture" not in backtest.text:
                raise ConfigurationError("backtest provenance was not disclosed")
            if store.status().schema_version < 32:
                raise ConfigurationError("research grounding release check requires schema v32")
            print(f"research-grounding-release-check: PASS schema_version={store.status().schema_version} run_id={run_id} tools={len(routes)}")
        finally:
            store.close()
    elif args.command == "research-context-isolation-release-check":
        store = RuntimeStateStore(args.db)
        try:
            from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest

            run_id = args.run_id or f"research-context-isolation-release-check:{uuid4().hex}"
            brain = LLMConversationBrain(
                GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"),
                store.conversations,
                tool_executor=SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit),
                tool_result_repository=store.conversation_tool_results,
            )
            strategy_text = (
                "사용자 전략: 20일 고가 돌파, 종가 > MA20 > MA60, 거래량 >= 20일 평균, "
                "손절 -5%, 10일 저점 이탈 청산. 이 전략 약점과 리스크 분석해줘"
            )
            critique = brain.respond(LLMConversationRequest(f"{run_id}:critique", "cli", "cli", strategy_text, _utc_now(), f"{run_id}:message:critique"))
            quality = brain.respond(LLMConversationRequest(f"{run_id}:quality", "cli", "cli", "이 전략 연구 품질 점수 알려줘", _utc_now(), f"{run_id}:message:quality"))
            memory = brain.respond(LLMConversationRequest(f"{run_id}:memory", "cli", "cli", "비슷한 전략 연구했어?", _utc_now(), f"{run_id}:message:memory"))
            combined = "\n".join((critique.text, quality.text, memory.text))
            if critique.tool_calls != ("strategy_critique",):
                raise ConfigurationError("research context isolation failed to route strategy critique")
            if contains_fixture_leakage(combined) or contains_unverified_fixture_metrics(critique.text):
                raise ConfigurationError("research context isolation leaked fixture candidate fields")
            for expected in ("20일 고가 돌파", "종가 > MA20 > MA60", "거래량 >= 20일 평균", "손절 -5%", "10일 저점 이탈 청산"):
                if expected not in critique.text:
                    raise ConfigurationError("research context isolation lost user-provided strategy condition")
            if "실제 백테스트를 기반으로 계산된 연구 품질 점수는 저장되어 있지 않습니다" not in quality.text:
                raise ConfigurationError("missing quality score fallback was not Korean and deterministic")
            if "찾지 못했습니다" not in memory.text or "접근 권한" in memory.text or "access" in memory.text.casefold():
                raise ConfigurationError("memory empty-state wording regressed")
            if store.status().schema_version < 32:
                raise ConfigurationError("research context isolation release check requires schema v32")
            print(f"research-context-isolation-release-check: PASS schema_version={store.status().schema_version} run_id={run_id}")
        finally:
            store.close()
    elif args.command == "korean-response-release-check":
        store = RuntimeStateStore(args.db)
        try:
            from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest

            run_id = args.run_id or f"korean-response-release-check:{uuid4().hex}"
            brain = LLMConversationBrain(
                GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"),
                store.conversations,
                tool_executor=SafeToolExecutor(default_tool_registry(store._connection), store.tool_audit),
                tool_result_repository=store.conversation_tool_results,
            )
            checks = (
                brain.respond(LLMConversationRequest(f"{run_id}:quality", "cli", "cli", "\uc774 \uc804\ub7b5\uc758 \uc5f0\uad6c \ud488\uc9c8 \uc810\uc218\ub97c \ubcf4\uc5ec\uc918.", _utc_now(), f"{run_id}:message:quality")),
                brain.respond(LLMConversationRequest(f"{run_id}:critique", "cli", "cli", "\uc774 \uc804\ub7b5\uc758 \uc57d\uc810\uc744 \ubd84\uc11d\ud574\uc918.", _utc_now(), f"{run_id}:message:critique")),
                brain.respond(LLMConversationRequest(f"{run_id}:memory", "cli", "cli", "\ube44\uc2b7\ud55c \uc804\ub7b5\uc744 \uc608\uc804\uc5d0 \uc5f0\uad6c\ud55c \uae30\ub85d\uc774 \uc788\ub294\uc9c0 \ucc3e\uc544\uc918.", _utc_now(), f"{run_id}:message:memory")),
            )
            combined = "\n".join(response.text for response in checks)
            if not all(_contains_hangul(response.text) for response in checks):
                raise ConfigurationError("Korean release check response did not contain Korean text")
            if contains_wrapper_tags(combined):
                raise ConfigurationError("Korean release check leaked output/response wrapper tags")
            if contains_fixture_leakage(combined) or contains_unverified_fixture_metrics(combined):
                raise ConfigurationError("Korean release check leaked fixture or fabricated metrics")
            if looks_like_english_final(combined):
                raise ConfigurationError("Korean release check returned English final text")
            for phrase in ("In-sample performance", "Parameter sensitivity", "Feature complexity", "access unavailable"):
                if phrase in combined:
                    raise ConfigurationError("Korean release check leaked English internal advisory text")
            if "\uc2e4\uc81c \ubc31\ud14c\uc2a4\ud2b8\ub97c \uae30\ubc18\uc73c\ub85c \uacc4\uc0b0\ub41c \uc5f0\uad6c \ud488\uc9c8 \uc810\uc218\ub294 \uc800\uc7a5\ub418\uc5b4 \uc788\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4" not in checks[0].text:
                raise ConfigurationError("Korean missing quality score response regressed")
            if "\uc800\uc7a5\ub41c \uc720\uc0ac \uc5f0\uad6c \uae30\ub85d\uc744 \ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4" not in checks[2].text:
                raise ConfigurationError("Korean memory empty-state response regressed")
            print(f"korean-response-release-check: PASS schema_version={store.status().schema_version} run_id={run_id}")
        finally:
            store.close()
    elif args.command == "strict-real-research-grounding-release-check":
        store = RuntimeStateStore(args.db)
        try:
            from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest

            run_id = args.run_id or f"strict-real-research-grounding-release-check:{uuid4().hex}"
            payload = _strict_real_research_payload()
            provider = _StrictGroundingFakeProvider()
            brain = LLMConversationBrain(
                GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
                store.conversations,
                tool_executor=_StrictGroundingFakeExecutor(payload),
                tool_result_repository=store.conversation_tool_results,
                assistant_provider=provider,
            )
            text = "provider tool-result roundtrip strict grounding regression check"
            response = brain.respond(LLMConversationRequest(f"{run_id}:session", "cli", "cli", text, _utc_now(), f"{run_id}:message"))
            final = response.text
            if provider.tool_result_roundtrip_count != 1:
                raise ConfigurationError("strict grounding release check did not exercise provider tool-result roundtrip")
            if "trade_count=3" not in final:
                raise ConfigurationError("strict grounding final response did not preserve BacktestResult trade_count=3")
            forbidden = ("trade_count=4", "4회", "win=2", "loss=2", "1.33", "MDD=8", "MDD 8", "fixed risk", "daily rebalance", "0.5%", "MDD 4", "take profit 3", "RSI 20", "volume 1.5", "volume_multiplier", "10일 기간")
            if any(token in final for token in forbidden):
                raise ConfigurationError("strict grounding final response leaked fabricated provider metrics")
            required = ("provider=real:yahoo-chart", "fixture_backed=false", "2025-09-19", "TESTED", "HYPOTHESIS", "commission=", "손절 -5")
            if any(token not in final for token in required):
                raise ConfigurationError("strict grounding final response lost required structured evidence")
            if not _contains_hangul(final):
                raise ConfigurationError("strict grounding final response was not Korean")
            if contains_wrapper_tags(final):
                raise ConfigurationError("strict grounding final response leaked wrapper tags")
            if response.tool_calls != ("krx_real_research",):
                raise ConfigurationError("strict grounding release check did not execute krx_real_research")
            if "provider strict real research grounding fallback" not in response.warnings:
                raise ConfigurationError("strict grounding fallback warning was not recorded")
            if store.status().schema_version < 33:
                raise ConfigurationError("strict grounding release check requires schema v33 or later")
            print(f"strict-real-research-grounding-release-check: PASS schema_version={store.status().schema_version} run_id={run_id} trades=3 provider_mock_trades=4")
        finally:
            store.close()
    elif args.command == "telegram-strict-real-research-release-check":
        store = RuntimeStateStore(args.db)
        try:
            run_id = args.run_id or f"telegram-strict-real-research-release-check:{uuid4().hex}"
            payload = _strict_real_research_payload()
            audit_before = len(store.tool_audit.list(tool_name="krx_real_research"))
            provider = _StrictTelegramHallucinatingProvider()
            client = _ReleaseCheckTelegramClient()
            tool_executor = _strict_real_safe_tool_executor(store, payload)
            config = GaonRuntimeConfig(
                mode="execute",
                dry_run=False,
                telegram_enabled=True,
                telegram_bot_token="synthetic-token",
                telegram_allowed_chat_ids=("100",),
                approval_signing_secret="synthetic-approval-secret",
                assistant_enabled=True,
                assistant_provider="openai-compatible",
                assistant_api_key="ollama-dummy-key",
                assistant_base_url="http://ollama.invalid/v1",
                assistant_model="qwen3:8b",
            )
            update = parse_update_result(_telegram_strict_real_update(run_id), received_at=_utc_now())
            runtime = TelegramRuntime(
                TelegramConversationAgent(config, store._connection, assistant_provider=provider, tool_executor=tool_executor),
                allowed_chat_ids=("100",),
            )
            result = process_update(update, runtime, client)
            if result.status != "sent":
                raise ConfigurationError(f"telegram strict grounding release check did not send response: {result.status}")
            if len(client.sent) != 1:
                raise ConfigurationError("telegram strict grounding release check sent unexpected number of responses")
            final = client.sent[0][1]
            violations = strict_real_research_grounding_violations(final, payload)
            if violations:
                raise ConfigurationError("telegram strict grounding final response violated authoritative metrics: " + ",".join(violations))
            forbidden = ("5.32%", "1.77%", "MDD 8", "거래 횟수 4", "4회", "RSI(14) 30", "RSI 30", "MA15", "MA90", "1.5x", "-3%", "5% 익절", "10일 기간")
            if any(token in final for token in forbidden):
                raise ConfigurationError("telegram strict grounding leaked provider-fabricated values")
            required = ("trade_count=3", "provider=real:yahoo-chart", "fixture_backed=false", "TESTED", "HYPOTHESIS")
            if any(token not in final for token in required):
                raise ConfigurationError("telegram strict grounding lost authoritative structured report fields")
            if provider.calls != 0:
                raise ConfigurationError("telegram strict real research should not ask provider to invent the final report")
            audit_after = len(store.tool_audit.list(tool_name="krx_real_research"))
            if audit_after <= audit_before:
                raise ConfigurationError("telegram strict grounding did not audit krx_real_research safe tool")
            messages = store.conversations.list_messages("telegram:100")
            assistant = [message for message in messages if message.role == "assistant"]
            if not assistant or assistant[-1].route != "tool_read_only_authoritative":
                raise ConfigurationError("telegram strict grounding did not use authoritative tool route")
            print(f"telegram-strict-real-research-release-check: PASS schema_version={store.status().schema_version} run_id={run_id} route=tool_read_only_authoritative trades=3 provider_calls=0")
        finally:
            store.close()
    elif args.command == "authoritative-renderer-grounding-release-check":
        store = RuntimeStateStore(args.db)
        try:
            run_id = args.run_id or f"authoritative-renderer-grounding-release-check:{uuid4().hex}"
            payload = _strict_real_research_payload()
            rendered = format_grounded_tool_response("krx_real_research", payload, payload["request_text"])
            if not rendered:
                raise ConfigurationError("authoritative renderer produced no final response")
            violations = strict_real_research_grounding_violations(rendered, payload)
            if violations:
                raise ConfigurationError("authoritative renderer self-validation failed: " + ",".join(violations))
            legitimate = "win=2 loss=1 trade_count=3 MDD 5.2% PF 1.42"
            legitimate_violations = strict_real_research_grounding_violations(legitimate, payload)
            if legitimate_violations:
                raise ConfigurationError("authoritative metric aliases were rejected: " + ",".join(legitimate_violations))
            fabricated = "win=3 trade_count=4 MDD 8% RSI(14) 30 MA15/MA90 volume 1.5x"
            fabricated_violations = strict_real_research_grounding_violations(fabricated, payload)
            if not fabricated_violations:
                raise ConfigurationError("fabricated metrics were not blocked")
            if not any("trade_count_mismatch:4!=" in item for item in fabricated_violations):
                raise ConfigurationError("fabricated trade count mismatch was not detected")
            if "2025-09-19" not in rendered:
                raise ConfigurationError("provider gap evidence was not preserved")
            if store.status().schema_version < 33:
                raise ConfigurationError("authoritative renderer check requires schema v33 or later")
            print(f"authoritative-renderer-grounding-release-check: PASS schema_version={store.status().schema_version} run_id={run_id} aliases=pass fabricated=blocked")
        finally:
            store.close()
    elif args.command == "structural-authoritative-grounding-release-check":
        store = RuntimeStateStore(args.db)
        try:
            run_id = args.run_id or f"structural-authoritative-grounding-release-check:{uuid4().hex}"
            payload = _strict_real_research_payload()
            rendered = format_grounded_tool_response("krx_real_research", payload, payload["request_text"])
            if not rendered:
                raise ConfigurationError("structural authoritative grounding renderer produced no report")
            if strict_real_research_grounding_violations(rendered, payload):
                raise ConfigurationError("structural authoritative grounding rejected deterministic renderer output")
            valid_alias_text = "wins=2 win=2 승리 2회 loss=1 losses=1 trades=3 MDD 5.2% return 4.7% PF 1.42"
            if strict_real_research_grounding_violations(valid_alias_text, payload):
                raise ConfigurationError("structural authoritative grounding rejected valid metric aliases")
            fabricated_metric_text = "win=4 trade_count=4 MDD=8% 평균 거래 수익률 1.77% 총 수익률 5.32%"
            fabricated_metric_violations = strict_real_research_grounding_violations(fabricated_metric_text, payload)
            if not fabricated_metric_violations:
                raise ConfigurationError("structural authoritative grounding allowed fabricated metrics")
            missing_pf_payload = _strict_real_research_payload()
            backtest = missing_pf_payload.get("backtest")
            if isinstance(backtest, dict) and isinstance(backtest.get("metrics"), dict):
                backtest["metrics"].pop("profit_factor", None)
            for candidate in missing_pf_payload.get("candidates", ()):
                if not isinstance(candidate, dict):
                    continue
                result = candidate.get("backtest_result")
                if isinstance(result, dict) and isinstance(result.get("metrics"), dict):
                    result["metrics"].pop("profit_factor", None)
            missing_pf_violations = strict_real_research_grounding_violations("PF 1.42", missing_pf_payload)
            if not any(item.startswith("profit_factor_missing_authoritative_evidence") for item in missing_pf_violations):
                raise ConfigurationError("structural authoritative grounding did not block unsupported PF")
            strategy_violations = strict_real_research_grounding_violations("RSI(14) 30 MA15 MA90 volume 1.5x -3% stop 5% 익절", payload)
            if not strategy_violations:
                raise ConfigurationError("structural authoritative grounding allowed fabricated strategy conditions")
            if store.status().schema_version < 33:
                raise ConfigurationError("structural authoritative grounding release check requires schema v33 or later")
            print(f"structural-authoritative-grounding-release-check: PASS schema_version={store.status().schema_version} run_id={run_id} valid_aliases=pass fabricated=blocked")
        finally:
            store.close()
    elif args.command == "telegram-real-research-failure-routing-release-check":
        store = RuntimeStateStore(args.db)
        try:
            run_id = args.run_id or f"telegram-real-research-failure-routing-release-check:{uuid4().hex}"
            market_provider = _StrictTelegramHallucinatingProvider()
            market_text = _run_telegram_failure_case(store, run_id, "market", _failure_tool_executor(store, RealMarketDataUnavailable("real_data_unavailable: provider returned no usable bars")), market_provider, _production_real_research_text())
            if "실제 시장 데이터를 가져오지 못해" not in market_text or "로컬 LLM" in market_text or market_provider.calls != 0:
                raise ConfigurationError("market data failure was not transparent or fail-closed")
            backtest_provider = _StrictTelegramHallucinatingProvider()
            backtest_text = _run_telegram_failure_case(store, run_id, "backtest", _failure_tool_executor(store, RuntimeError("backtest execution failed")), backtest_provider, _production_real_research_text())
            if "백테스트 실행 중 오류" not in backtest_text or "5.32%" in backtest_text or backtest_provider.calls != 0:
                raise ConfigurationError("backtest failure was not transparent or fail-closed")
            timeout_provider = _TimeoutAssistantProvider()
            timeout_text = _run_telegram_failure_case(store, run_id, "timeout", SafeToolExecutor(ToolRegistry(), None), timeout_provider, "안녕하세요 가온")
            if "로컬 LLM 응답이 지연" not in timeout_text:
                raise ConfigurationError("actual provider timeout was not classified as LLM delay")
            internal_text = _run_telegram_failure_case(store, run_id, "internal", _RaisingToolExecutor(RuntimeError("synthetic internal failure")), _StrictTelegramHallucinatingProvider(), _production_real_research_text())
            if "내부 오류" not in internal_text or "synthetic internal failure" in internal_text:
                raise ConfigurationError("unexpected internal error was not safely summarized")
            if any(token in (market_text + backtest_text + internal_text) for token in ("5.32%", "1.77%", "MDD 8", "거래 횟수 4", "RSI(14) 30", "1.5x")):
                raise ConfigurationError("failure routing leaked fabricated provider research results")
            print(f"telegram-real-research-failure-routing-release-check: PASS schema_version={store.status().schema_version} run_id={run_id} market=classified backtest=classified timeout=classified internal=classified provider_fail_closed=true")
        finally:
            store.close()
    elif args.command == "strategy-parser-release-check":
        store = RuntimeStateStore(args.db)
        try:
            text = "20일 고가 돌파 + 종가 > MA20 > MA60 + 거래량 >= 20일 평균 이상, 손절 -5%, 10일 저점 이탈 청산"
            spec = UserStrategyParser().parse(text, symbol="005930", created_at=_utc_now())
            if spec.entry["breakout_lookback"].value != 20:
                raise ConfigurationError("strategy parser did not extract breakout lookback")
            if spec.entry["breakout_lookback"].provenance.value != "user_provided":
                raise ConfigurationError("strategy parser lost user provenance")
            payload = _dumps_json(spec.to_json())
            for forbidden in ("volume_multiplier", "max_risk_pct", "regime_tags"):
                if forbidden in payload:
                    raise ConfigurationError("strategy parser leaked fixture/default candidate metadata")
            print(f"strategy-parser-release-check: PASS schema_version={store.status().schema_version} fingerprint={spec.fingerprint[:12]}")
        finally:
            store.close()
    elif args.command == "real-backtest-release-check":
        store = RuntimeStateStore(args.db)
        try:
            run_id = f"real-backtest-release-check:{uuid4().hex}"
            dataset, quality, _inserted = KRXDatasetBuilder(store._connection, KRXFixtureMarketDataProvider()).build("005930", start_date="2026-01-01", end_date="2026-07-10")
            spec = UserStrategyParser().parse("20일 고가 돌파 종가 > MA20 > MA60 거래량 >= 20일 평균 손절 -5% 10일 저점 이탈 청산", symbol="005930", created_at=_utc_now())
            assumptions = default_execution_assumptions()
            result = RuleBasedBacktestEngine().run(run_id, spec, dataset, assumptions, generated_at=_utc_now())
            validation = WalkForwardValidator().validate(spec, dataset, assumptions, run_id=run_id, generated_at=_utc_now())
            findings = EvidenceBasedStrategyCritic().critique(spec, result, validation)
            if quality.status.value == "fail":
                raise ConfigurationError("fixture KRX dataset quality failed")
            if result.status != "completed":
                raise ConfigurationError("rule-based real backtest did not complete")
            if result.source.value != "fixture":
                raise ConfigurationError("fixture backtest source was not disclosed")
            if result.metrics.trade_count < 1:
                raise ConfigurationError("rule-based backtest did not produce a deterministic trade")
            if not findings:
                raise ConfigurationError("evidence critic produced no findings")
            print(f"real-backtest-release-check: PASS schema_version={store.status().schema_version} source={result.source.value} trades={result.metrics.trade_count} validation={validation.passed}")
        finally:
            store.close()
    elif args.command == "krx-real-research-demo":
        store = RuntimeStateStore(args.db)
        try:
            report = RealAutonomousResearchPipeline(store._connection, build_market_data_provider_from_env(os.environ)).run(args.request, symbol=args.symbol)
            if args.json:
                print(_dumps_json(report.to_json()))
            else:
                print(f"krx-real-research-demo: report={report.report_id} source={report.backtest.source.value} trades={report.backtest.metrics.trade_count} memory={report.memory_id}")
        finally:
            store.close()
    elif args.command == "krx-real-research-release-check":
        store = RuntimeStateStore(args.db)
        try:
            required_tools = {"krx_real_research", "krx_market_data", "data_quality_check", "research_memory_search"}
            tool_names = {tool.name for tool in default_tool_registry(store._connection).list()}
            if not required_tools.issubset(tool_names):
                raise ConfigurationError("KRX real research safe tools are not registered")
            text = "20일 고가 돌파 + 종가 > MA20 > MA60 + 거래량 >= 20일 평균 이상, 손절 -5%, 10일 저점 이탈 청산 전략의 약점을 분석하고 개선해줘"
            provider = build_market_data_provider_from_env(os.environ)
            first = RealAutonomousResearchPipeline(store._connection, provider).run(text, run_id=f"krx-real-research-release-check:{uuid4().hex}", symbol="005930")
            second = RealAutonomousResearchPipeline(store._connection, provider).run(text, run_id=f"krx-real-research-release-check:{uuid4().hex}", symbol="005930")
            combined = _dumps_json(first.to_json()) + _dumps_json(second.to_json())
            for forbidden in ("volume_multiplier", "max_risk_pct", "regime_tags", "<output>", "<response>"):
                if forbidden in combined:
                    raise ConfigurationError("KRX real research leaked fixture metadata or wrapper tags")
            if first.backtest.source.value not in {"fixture", "real"}:
                raise ConfigurationError("release check must explicitly disclose data source")
            if first.backtest.metrics.trade_count < 1 or second.backtest.metrics.trade_count < 1:
                raise ConfigurationError("repeatable KRX research did not produce deterministic backtests")
            if f"source={first.backtest.source.value}" not in first.korean_report:
                raise ConfigurationError("Korean report did not disclose fixture source")
            if store.status().schema_version < 33:
                raise ConfigurationError("KRX real research schema was not migrated to v33")
            print(
                "krx-real-research-release-check: PASS "
                f"schema_version={store.status().schema_version} source={first.backtest.source.value} "
                f"trades={first.backtest.metrics.trade_count} candidates={len(first.candidates)} tools={len(required_tools)}"
            )
        finally:
            store.close()
    elif args.command == "real-krx-data-release-check":
        config = load_runtime_config(os.environ)
        store = RuntimeStateStore(args.db)
        try:
            if not config.real_market_data_enabled:
                raise ConfigurationError("real KRX data release check requires GAON_REAL_MARKET_DATA_ENABLED=true")
            provider = build_market_data_provider_from_env(os.environ)
            result = real_krx_data_release_check(store._connection, symbol=args.symbol, start_date=args.start, end_date=args.end, provider=provider)
            if result["source"] != "real" or result["fixture_backed"] is not False:
                raise ConfigurationError("real KRX data release check did not use real source")
            print(
                "real-krx-data-release-check: PASS "
                f"schema_version={store.status().schema_version} source={result['source']} "
                f"fixture_backed={str(result['fixture_backed']).lower()} provider={result['provider']} "
                f"symbol={result['symbol']} rows={result['rows']} quality={result['quality']} "
                f"provider_gaps={result['provider_gaps']} blocking_findings={result['blocking_findings']} "
                f"trades={result['trades']} validation={result['validation']}"
            )
        except RealMarketDataUnavailable as exc:
            raise ConfigurationError(str(exc)) from exc
        finally:
            store.close()
    elif args.command == "krx-trading-calendar-release-check":
        store = RuntimeStateStore(args.db)
        try:
            result = krx_trading_calendar_release_check(store._connection)
            if store.status().schema_version < 33:
                raise ConfigurationError("KRX trading calendar release check requires schema v33 or later")
            print(
                "krx-trading-calendar-release-check: PASS "
                f"schema_version={store.status().schema_version} "
                f"weekend_excluded={str(result['weekend_excluded']).lower()} "
                f"holiday_excluded={str(result['holiday_excluded']).lower()} "
                f"missing_trading_day_detected={str(result['missing_trading_day_detected']).lower()} "
                f"malformed_detected={str(result['malformed_detected']).lower()} "
                f"duplicate_detected={str(result['duplicate_detected']).lower()} "
                f"source={result['source']} fixture_backed={str(result['fixture_backed']).lower()}"
            )
        except RealMarketDataUnavailable as exc:
            raise ConfigurationError(str(exc)) from exc
        finally:
            store.close()
    elif args.command == "historical-krx-calendar-release-check":
        store = RuntimeStateStore(args.db)
        try:
            result = historical_krx_calendar_release_check(store._connection)
            if store.status().schema_version < 33:
                raise ConfigurationError("historical KRX calendar release check requires schema v33 or later")
            print(
                "historical-krx-calendar-release-check: PASS "
                f"schema_version={store.status().schema_version} provider={result['provider']} "
                f"fixture_backed={str(result['fixture_backed']).lower()} "
                f"provider_gap_dates={','.join(result['provider_gap_dates'])} "
                f"blocking_findings={result['blocking_findings']} "
                f"expected_3y={result['expected_3y']} "
                f"actual_3y_without_provider_gap={result['actual_3y_without_provider_gap']} "
                f"expected_5y={result['expected_5y']}"
            )
        except RealMarketDataUnavailable as exc:
            raise ConfigurationError(str(exc)) from exc
        finally:
            store.close()
    elif args.command == "provider-gap-release-check":
        store = RuntimeStateStore(args.db)
        try:
            result = provider_gap_release_check(store._connection)
            if store.status().schema_version < 33:
                raise ConfigurationError("provider gap release check requires schema v33 or later")
            print(
                "provider-gap-release-check: PASS "
                f"schema_version={store.status().schema_version} provider={result['provider']} "
                f"fixture_backed={str(result['fixture_backed']).lower()} quality={result['quality']} "
                f"provider_gaps={result['provider_gaps']} provider_gap_dates={','.join(result['provider_gap_dates'])} "
                f"blocking_findings={result['blocking_findings']} other_provider_isolated={str(result['other_provider_isolated']).lower()}"
            )
        except RealMarketDataUnavailable as exc:
            raise ConfigurationError(str(exc)) from exc
        finally:
            store.close()
    elif args.command == "research-ops-demo":
        store = RuntimeStateStore(args.db if args.persist else ":memory:")
        try:
            champion, challenger = fixture_evidence_pair(sufficient=not args.insufficient_sample)
            report = ResearchOperationsService(SQLiteResearchOperationRepository(store._connection)).analyze(
                f"research-ops-demo:{uuid4().hex}",
                champion,
                challenger,
                generated_at=_utc_now(),
            )
            if args.json:
                print(_dumps_json(report.to_json()))
            else:
                print(operation_report_markdown(report))
        finally:
            store.close()
    elif args.command == "research-ops-release-check":
        target_store = RuntimeStateStore(args.db)
        try:
            target_counts_before = _research_ops_table_counts(target_store._connection)
            target_schema = target_store.status().schema_version
        finally:
            target_store.close()
        store = RuntimeStateStore(":memory:")
        try:
            service = ResearchOperationsService(SQLiteResearchOperationRepository(store._connection))
            insufficient_champion, insufficient_challenger = fixture_evidence_pair(sufficient=False)
            insufficient = service.analyze(f"research-ops-release-check:insufficient:{uuid4().hex}", insufficient_champion, insufficient_challenger, generated_at=_utc_now())
            if insufficient.quality_gate.status is not QualityStatus.INSUFFICIENT_SAMPLE or not insufficient.period_plan.expansion_required:
                raise ConfigurationError("research ops did not detect insufficient sample and period expansion")
            champion, challenger = fixture_evidence_pair(sufficient=True)
            report_id = f"research-ops-release-check:{uuid4().hex}"
            config_count_before = store._connection.execute("SELECT COUNT(*) FROM strategy_config_versions").fetchone()[0]
            report = service.analyze(report_id, champion, challenger, generated_at=_utc_now())
            if report.recommendation.decision is not RecommendationDecision.RECOMMEND_CHALLENGER:
                raise ConfigurationError("research ops did not recommend dominant challenger")
            config_count_after_analysis = store._connection.execute("SELECT COUNT(*) FROM strategy_config_versions").fetchone()[0]
            if config_count_after_analysis != config_count_before:
                raise ConfigurationError("research ops changed strategy config before approval")
            config = service.approve_and_apply(report_id, actor_ref="release-check-human", approved_at=_utc_now())
            if config.status is not ResearchConfigApprovalStatus.APPLIED or config.strategy_ref != challenger.strategy_ref:
                raise ConfigurationError("approved strategy configuration was not applied")
            second_report = service.analyze(f"research-ops-release-check:second:{uuid4().hex}", champion, challenger, generated_at=_utc_now())
            second_config = service.approve_and_apply(second_report.report_id, actor_ref="release-check-human", approved_at=_utc_now())
            rolled_back = service.rollback(second_config.config_id, actor_ref="release-check-human", rolled_back_at=_utc_now())
            if rolled_back.strategy_ref != config.strategy_ref:
                raise ConfigurationError("strategy config rollback did not restore previous config")
            audit = SQLiteResearchOperationRepository(store._connection).audit_history()
            if len(audit) < 5:
                raise ConfigurationError("research ops audit history was not recorded")
            target_store = RuntimeStateStore(args.db)
            try:
                target_counts_after = _research_ops_table_counts(target_store._connection)
            finally:
                target_store.close()
            if target_counts_after != target_counts_before:
                raise ConfigurationError("research ops release check modified target research state")
            print(
                "research-ops-release-check: PASS "
                f"schema_version={target_schema} isolated=true insufficient_sample=detected "
                f"dominance={report.dominance.decision.value} recommendation={report.recommendation.decision.value} "
                f"applied={config.config_id} rollback={rolled_back.config_id} audit={len(audit)}"
            )
        finally:
            store.close()
    elif args.command == "research-config-approve":
        store = RuntimeStateStore(args.db)
        try:
            config = ResearchOperationsService(SQLiteResearchOperationRepository(store._connection)).approve_and_apply(args.report_id, actor_ref=args.actor_ref, approved_at=_utc_now())
            print(f"research-config-approve: applied config_id={config.config_id} revision={config.revision} rollback_ref={config.rollback_ref}")
        finally:
            store.close()
    elif args.command == "research-config-rollback":
        store = RuntimeStateStore(args.db)
        try:
            config = ResearchOperationsService(SQLiteResearchOperationRepository(store._connection)).rollback(args.config_id, actor_ref=args.actor_ref, rolled_back_at=_utc_now())
            print(f"research-config-rollback: restored config_id={config.config_id} revision={config.revision} previous={config.previous_config_id}")
        finally:
            store.close()
    elif args.command == "research-ops-report":
        store = RuntimeStateStore(args.db)
        try:
            repository = SQLiteResearchOperationRepository(store._connection)
            if args.report_id:
                report = repository.get_report(args.report_id)
                if report is None:
                    raise ConfigurationError("research operation report not found")
                print(_dumps_json(report.to_json()) if args.json else operation_report_markdown(report))
            else:
                reports = repository.list_reports(include_artifacts=args.include_artifacts)
                print(_dumps_json({"reports": list(reports)}) if args.json else "\n".join(str(item) for item in reports))
        finally:
            store.close()
    elif args.command == "research-ops-cleanup":
        if args.apply and args.dry_run:
            raise ConfigurationError("choose either --dry-run or --apply")
        apply_cleanup = bool(args.apply)
        store = RuntimeStateStore(args.db)
        try:
            repository = SQLiteResearchOperationRepository(store._connection)
            plan = repository.cleanup_artifacts(apply=apply_cleanup, actor_ref="cli", created_at=_utc_now())
            output = {"mode": "apply" if apply_cleanup else "dry-run", "deleted" if apply_cleanup else "matched": plan.to_json(), "schema_version": store.status().schema_version}
            if args.json:
                print(_dumps_json(output))
            else:
                action = "APPLIED" if apply_cleanup else "DRY-RUN"
                print(
                    f"research-ops-cleanup: {action} reports={len(plan.report_ids)} approvals={len(plan.approval_ids)} "
                    f"configs={len(plan.config_ids)} audit={len(plan.audit_ids)} total={plan.total}"
                )
        finally:
            store.close()
    elif args.command == "research-retest-demo":
        store = RuntimeStateStore(args.db if args.persist else ":memory:")
        try:
            run = AutonomousRetestOrchestrator(store._connection).run(f"{args.request}", run_id=f"research-retest-demo:{uuid4().hex}", symbol=args.symbol, generated_at=_utc_now())
            print(_dumps_json(run.to_json()) if args.json else run.korean_report)
        finally:
            store.close()
    elif args.command == "autonomous-retest-release-check":
        target_store = RuntimeStateStore(args.db)
        try:
            target_schema = target_store.status().schema_version
            target_counts_before = _retest_table_counts(target_store._connection)
        finally:
            target_store.close()
        store = RuntimeStateStore(":memory:")
        try:
            run = autonomous_retest_release_check(store._connection)
            evidence = run["evidence"]
            final = evidence[-1]
            target_store = RuntimeStateStore(args.db)
            try:
                target_counts_after = _retest_table_counts(target_store._connection)
            finally:
                target_store.close()
            if target_counts_after != target_counts_before:
                raise ConfigurationError("autonomous retest release check modified target retest state")
            print(
                "autonomous-retest-release-check: PASS "
                f"schema_version={target_schema} isolated=true run_id={run['run_id']} "
                f"periods={len(evidence)} final_trade_count={final['trade_count']} "
                f"stop_reason={run['stop_reason']} recommendation={run['final_recommendation']} "
                f"strategy_fingerprint=stable assumptions_fingerprint=stable source=real fixture_backed=false"
            )
        finally:
            store.close()
    elif args.command == "telegram-retest-persistence-release-check":
        target_store = RuntimeStateStore(args.db)
        try:
            target_schema = target_store.status().schema_version
            target_counts_before = _retest_table_counts(target_store._connection)
        finally:
            target_store.close()
        store = RuntimeStateStore(":memory:")
        try:
            run_id = f"telegram-retest-persistence-release-check:{uuid4().hex}"
            update = _telegram_update_with_text(
                run_id,
                "retest",
                "retest until enough samples and expand period for Samsung Electronics real data backtest",
            )
            client = _ReleaseCheckTelegramClient((update,))
            config = GaonRuntimeConfig(
                mode="execute",
                dry_run=False,
                telegram_enabled=True,
                telegram_bot_token="synthetic-token",
                telegram_allowed_chat_ids=("100",),
                approval_signing_secret="synthetic-approval-secret",
                assistant_enabled=True,
                assistant_provider="deterministic",
            )
            results = poll_once(client, config, offset=None, received_at=_utc_now(), state=store.telegram, runtime_store=store)
            if tuple(result.status for result in results) != ("sent",):
                raise ConfigurationError("telegram retest persistence release check did not send exactly one response")
            runs = research_retest_status_payload(store._connection, limit=5)["runs"]
            history = research_retest_history_payload(store._connection, limit=20)["evidence"]
            if len(runs) != 1 or len(history) < 1:
                raise ConfigurationError("telegram retest route did not persist status/history")
            duplicate = poll_once(client, config, offset=None, received_at=_utc_now(), state=store.telegram, runtime_store=store)
            if tuple(result.status for result in duplicate) != ("duplicate",):
                raise ConfigurationError("telegram retest duplicate update was not idempotent")
            if len(research_retest_status_payload(store._connection, limit=5)["runs"]) != 1:
                raise ConfigurationError("telegram retest duplicate update stored another run")
            target_store = RuntimeStateStore(args.db)
            try:
                target_counts_after = _retest_table_counts(target_store._connection)
            finally:
                target_store.close()
            if target_counts_after != target_counts_before:
                raise ConfigurationError("telegram retest release check modified target retest state")
            print(
                "telegram-retest-persistence-release-check: PASS "
                f"schema_version={target_schema} isolated=true persisted_runs=1 evidence={len(history)} duplicate=idempotent"
            )
        finally:
            store.close()
    elif args.command == "research-retest-status":
        store = RuntimeStateStore(args.db)
        try:
            payload = research_retest_status_payload(store._connection, limit=args.limit)
            print(_dumps_json(payload) if args.json else "\n".join(str(item) for item in payload["runs"]) or "현재 저장된 자동 재검증 결과가 없습니다.")
        finally:
            store.close()
    elif args.command == "research-retest-history":
        store = RuntimeStateStore(args.db)
        try:
            payload = research_retest_history_payload(store._connection, run_id=args.run_id, limit=args.limit)
            print(_dumps_json(payload) if args.json else "\n".join(str(item) for item in payload["evidence"]) or "현재 저장된 자동 재검증 이력이 없습니다.")
        finally:
            store.close()
    elif args.command == "backup":
        store = RuntimeStateStore(args.db)
        try:
            print(store.backup(args.destination))
        finally:
            store.close()
    elif args.command == "metrics":
        collector = MetricsCollector()
        collector.increment("runtime_loops", component="cli")
        collector.gauge("queue_depth", 0, component="runtime")
        print(collector.snapshot().to_text())
    elif args.command == "event-replay-dry-run":
        store = RuntimeStateStore(args.db)
        try:
            result = SQLiteEventStore(store._connection).replay(_NoopProjection(), dry_run=True)
            print(f"event-replay-dry-run: processed={result.processed} failed={result.failed} checkpoint={result.last_event_id or ''}")
        finally:
            store.close()
    elif args.command == "executive-plan":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            request = ExecutiveRequest("cli-executive-request", args.request, "actor:redacted", now)
            plan = DeterministicExecutivePlanner().plan(request)
            SQLiteEventStore(store._connection).append(executive_plan_event(plan, actor_ref=request.actor_ref, appended_at=now))
            if args.json:
                print(plan.to_json())
            else:
                print(
                    "executive-plan: "
                    f"route={plan.routing_decision.value} "
                    f"agents={','.join(agent.value for agent in plan.agents)} "
                    f"tools={','.join(tool.value for tool in plan.tools)} "
                    f"approval_required={plan.approval_required}"
                )
        finally:
            store.close()
    elif args.command == "agent-run":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            plan = _agent_run_plan(args.agent, now)
            request = AgentRequest("cli-agent-request", args.request, "actor:redacted", now)
            result = AgentDispatcher(default_agent_registry(), load_runtime_config(os.environ), event_store=SQLiteEventStore(store._connection)).dispatch(plan, request)
            if args.json:
                print(
                    "{"
                    f"\"agent_name\":\"{result.agent_name}\","
                    f"\"status\":\"{result.status.value}\","
                    f"\"output\":\"{result.output}\""
                    "}"
                )
            else:
                print(f"agent-run: agent={result.agent_name} status={result.status.value} output={result.output}")
        finally:
            store.close()
    elif args.command == "schedule-create":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            repo = ScheduledJobRepository(store._connection)
            agent_selection, tools = _schedule_agent_constraints(args.agent)
            job = ScheduledJob(
                args.job_id,
                args.name,
                args.request,
                ScheduleDefinition("UTC", args.next_run_at),
                True,
                now,
                now,
                approval_required=args.approval_required,
                agent_selection=agent_selection,
                tool_constraints=tools,
            )
            repo.create(job)
            SQLiteEventStore(store._connection).append(scheduled_event("ScheduledJobCreated", job, None, now))
            metrics = MetricsCollector()
            record_scheduled_job_metric(metrics, repo)
            print(f"schedule-create: job_id={job.job_id} enabled={job.enabled}")
        finally:
            store.close()
    elif args.command == "schedule-list":
        store = RuntimeStateStore(args.db)
        try:
            jobs = ScheduledJobRepository(store._connection).list()
            for job in jobs:
                print(f"{job.job_id} enabled={job.enabled} next_run_at={job.schedule.next_run_at} name={job.name}")
            if not jobs:
                print("schedule-list: none")
        finally:
            store.close()
    elif args.command == "schedule-show":
        store = RuntimeStateStore(args.db)
        try:
            job = ScheduledJobRepository(store._connection).get(args.job_id)
            print(f"schedule-show: job_id={job.job_id} enabled={job.enabled} approval_required={job.approval_required} request={job.request_text}")
        finally:
            store.close()
    elif args.command in {"schedule-enable", "schedule-disable"}:
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            repo = ScheduledJobRepository(store._connection)
            enabled = args.command == "schedule-enable"
            job = repo.set_enabled(args.job_id, enabled, updated_at=now)
            SQLiteEventStore(store._connection).append(scheduled_event("ScheduledJobEnabled" if enabled else "ScheduledJobDisabled", job, None, now))
            print(f"{args.command}: job_id={job.job_id} enabled={job.enabled}")
        finally:
            store.close()
    elif args.command == "schedule-run-due":
        store = RuntimeStateStore(args.db)
        try:
            now = args.now or _utc_now()
            runner = ScheduledAutomationRunner(ScheduledJobRepository(store._connection), load_runtime_config(os.environ), event_store=SQLiteEventStore(store._connection))
            runs = runner.run_due(now=now)
            for run in runs:
                print(f"schedule-run-due: run_id={run.run_id} job_id={run.job_id} status={run.status.value}")
            if not runs:
                print("schedule-run-due: none")
        finally:
            store.close()
    elif args.command == "daily-research-create":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            daily_repo = DailyResearchRepository(store._connection)
            scheduled_repo = ScheduledJobRepository(store._connection)
            profile = DailyResearchProfile(
                args.profile_id,
                args.topic,
                args.query,
                True,
                args.priority,
                tuple(args.source or ("fake",)),
                args.time_range,
                args.language,
                now,
                now,
                {"created_by": "cli"},
            )
            daily_repo.create_profile(profile)
            DailyResearchPipeline(daily_repo, scheduled_repo, load_runtime_config(os.environ), event_store=SQLiteEventStore(store._connection)).schedule_profile(profile, next_run_at=args.next_run_at)
            SQLiteEventStore(store._connection).append(daily_research_event("DailyResearchProfileCreated", profile, None, now))
            metrics = MetricsCollector()
            record_daily_research_profile_metric(metrics, daily_repo)
            print(f"daily-research-create: profile_id={profile.profile_id} enabled={profile.enabled} scheduled=daily-research:{profile.profile_id}")
        finally:
            store.close()
    elif args.command == "daily-research-list":
        store = RuntimeStateStore(args.db)
        try:
            profiles = DailyResearchRepository(store._connection).list_profiles()
            for profile in profiles:
                print(f"{profile.profile_id} enabled={profile.enabled} priority={profile.priority} topic={profile.topic}")
            if not profiles:
                print("daily-research-list: none")
        finally:
            store.close()
    elif args.command == "daily-research-show":
        store = RuntimeStateStore(args.db)
        try:
            profile = DailyResearchRepository(store._connection).get_profile(args.profile_id)
            print(f"daily-research-show: profile_id={profile.profile_id} enabled={profile.enabled} priority={profile.priority} topic={profile.topic} query={profile.query}")
        finally:
            store.close()
    elif args.command in {"daily-research-enable", "daily-research-disable"}:
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            repo = DailyResearchRepository(store._connection)
            enabled = args.command == "daily-research-enable"
            profile = repo.set_enabled(args.profile_id, enabled, updated_at=now)
            SQLiteEventStore(store._connection).append(daily_research_event("DailyResearchProfileEnabled" if enabled else "DailyResearchProfileDisabled", profile, None, now))
            print(f"{args.command}: profile_id={profile.profile_id} enabled={profile.enabled}")
        finally:
            store.close()
    elif args.command == "daily-research-run":
        if not args.due and not args.profile_id:
            raise ConfigurationError("daily-research-run requires --due or --profile-id")
        store = RuntimeStateStore(args.db)
        try:
            now = args.now or _utc_now()
            pipeline = DailyResearchPipeline(
                DailyResearchRepository(store._connection),
                ScheduledJobRepository(store._connection),
                load_runtime_config(os.environ),
                event_store=SQLiteEventStore(store._connection),
            )
            runs = pipeline.run_due(now=now) if args.due else (pipeline.run_profile(args.profile_id, now=now),)
            for run in runs:
                print(f"daily-research-run: run_id={run.run_id} profile_id={run.profile_id} status={run.status.value}")
            if not runs:
                print("daily-research-run: none")
        finally:
            store.close()
    elif args.command == "daily-research-report":
        store = RuntimeStateStore(args.db)
        try:
            runs = tuple(run for run in DailyResearchRepository(store._connection).list_runs(args.profile_id) if run.result is not None)
            if not runs:
                raise ConfigurationError("daily-research-report requires a completed run with a report")
            result = runs[-1].result
            assert result is not None
            print(result.to_json() if args.format == "json" else result.to_markdown())
        finally:
            store.close()
    elif args.command in {"trading-status", "trading-account", "trading-positions"}:
        store = RuntimeStateStore(args.db)
        try:
            adapter = PaperTradingAdapter()
            ok, message = adapter.health_check()
            if args.command == "trading-status":
                print(f"trading-status: ready={ok} message={message}")
            elif args.command == "trading-account":
                account = adapter.get_account_snapshot()
                print(f"trading-account: account_ref={account.account_ref} cash={account.cash:.2f} equity={account.equity:.2f} currency={account.currency}")
            else:
                positions = adapter.get_positions()
                for position in positions:
                    print(f"{position.symbol} quantity={position.quantity} average_price={position.average_price} market_value={position.market_value}")
                if not positions:
                    print("trading-positions: none")
        finally:
            store.close()
    elif args.command in {"trading-simulate-buy", "trading-simulate-sell"}:
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            intent = TradingIntent.SIMULATE_BUY if args.command == "trading-simulate-buy" else TradingIntent.SIMULATE_SELL
            request = build_trading_request(
                f"cli:{args.command}:{args.symbol}:{now}",
                intent,
                symbol=args.symbol,
                quantity=args.quantity,
                price=args.price,
                actor_ref="actor:redacted",
                created_at=now,
                idempotency_key=f"{args.command}:{args.symbol}:{now}",
            )
            result = TradingExecutionService(
                PaperTradingAdapter(),
                TradingRiskPolicy(),
                repository=SQLiteTradingRepository(store._connection),
                event_store=SQLiteEventStore(store._connection),
            ).execute(request)
            print(f"{args.command}: status={result.status.value} result_id={result.result_id} message={result.message}")
        finally:
            store.close()
    elif args.command == "trading-cancel-simulated-order":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            request = build_trading_request(f"cli:cancel:{args.request_id}:{now}", TradingIntent.CANCEL_SIMULATED_ORDER, symbol="PAPER", actor_ref="actor:redacted", created_at=now, idempotency_key=f"cancel:{args.request_id}:{now}")
            result = TradingExecutionService(PaperTradingAdapter(), TradingRiskPolicy(), repository=SQLiteTradingRepository(store._connection), event_store=SQLiteEventStore(store._connection)).execute(request)
            print(f"trading-cancel-simulated-order: status={result.status.value} result_id={result.result_id}")
        finally:
            store.close()
    elif args.command == "trading-history":
        store = RuntimeStateStore(args.db)
        try:
            results = SQLiteTradingRepository(store._connection).list_results()
            for result in results:
                print(f"{result.result_id} request_id={result.request_id} status={result.status.value} notional={result.notional:.2f}")
            if not results:
                print("trading-history: none")
        finally:
            store.close()
    elif args.command in {"backtest-status", "backtest-list-strategies"}:
        store = RuntimeStateStore(args.db)
        try:
            adapter = FakeBacktestAdapter()
            ok, message = adapter.health_check()
            if args.command == "backtest-status":
                print(f"backtest-status: ready={ok} message={message}")
            else:
                for strategy in adapter.get_supported_strategies():
                    print(strategy)
        finally:
            store.close()
    elif args.command == "backtest-run":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            request = build_backtest_request(f"cli-backtest:{args.strategy}:{args.dataset}:{args.start}:{args.end}", args.strategy, args.dataset, args.start, args.end, actor_ref="actor:redacted", created_at=now)
            result = BacktestExecutionService(FakeBacktestAdapter(), repository=SQLiteBacktestRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector()).run(request, BacktestExecutionContext(30, 64_000, now))
            print(f"backtest-run: status={result.status.value} result_id={result.result_id} fingerprint={result.fingerprint}")
        finally:
            store.close()
    elif args.command == "backtest-show":
        store = RuntimeStateStore(args.db)
        try:
            result = SQLiteBacktestRepository(store._connection).get_result(args.result_id)
            print(result.to_json())
        finally:
            store.close()
    elif args.command == "backtest-history":
        store = RuntimeStateStore(args.db)
        try:
            results = SQLiteBacktestRepository(store._connection).list_results()
            for result in results:
                print(f"{result.result_id} request_id={result.request_id} status={result.status.value} fingerprint={result.fingerprint}")
            if not results:
                print("backtest-history: none")
        finally:
            store.close()
    elif args.command == "validation-run":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            backtest_repo = SQLiteBacktestRepository(store._connection)
            result = backtest_repo.get_result(args.backtest_id) if args.backtest_id else _find_backtest_by_fingerprint(backtest_repo, args.fingerprint)
            request = build_validation_request(f"validation:{result.result_id}", (result,), actor_ref="actor:redacted", requested_at=now)
            report = StrategyValidationEngine(repository=SQLiteValidationRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector()).validate(request, (result,), generated_at=now)
            print(f"validation-run: validation_id={report.validation_id} status={report.overall_status.value} score={report.score} fingerprint={report.fingerprint}")
        finally:
            store.close()
    elif args.command == "validation-show":
        store = RuntimeStateStore(args.db)
        try:
            print(SQLiteValidationRepository(store._connection).get_report(args.validation_id).to_json())
        finally:
            store.close()
    elif args.command == "validation-history":
        store = RuntimeStateStore(args.db)
        try:
            reports = SQLiteValidationRepository(store._connection).list_reports()
            for report in reports:
                print(f"{report.validation_id} status={report.overall_status.value} score={report.score} fingerprint={report.fingerprint}")
            if not reports:
                print("validation-history: none")
        finally:
            store.close()
    elif args.command == "validation-policy-show":
        policy = ValidationPolicy()
        if args.json:
            import json

            print(json.dumps(policy.__dict__, sort_keys=True, separators=(",", ":"), default=lambda value: value.value if hasattr(value, "value") else str(value)))
        else:
            print(f"validation-policy-show: policy_version={policy.policy_version} min_trade_count={policy.min_trade_count} max_drawdown={policy.max_drawdown:.2f} min_sample_days={policy.min_sample_days}")
    elif args.command == "champion-policy-show":
        policy = ChampionChallengerPolicy()
        if args.json:
            import json

            print(json.dumps(policy.__dict__, sort_keys=True, separators=(",", ":")))
        else:
            print(f"champion-policy-show: policy_version={policy.policy_version} minimum_return_improvement={policy.minimum_return_improvement:.2f} maximum_mdd_degradation={policy.maximum_mdd_degradation:.2f}")
    elif args.command == "champion-evaluate":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            backtest_repo = SQLiteBacktestRepository(store._connection)
            validation_repo = SQLiteValidationRepository(store._connection)
            champion = backtest_repo.get_result(args.champion_backtest_id)
            challenger = backtest_repo.get_result(args.challenger_backtest_id)
            validation = validation_repo.get_report(args.validation_id)
            request = build_champion_challenger_request(f"champion-evaluation:{champion.result_id}:{challenger.result_id}:{validation.validation_id}", champion=champion, challenger=challenger, validation=validation, actor_ref="actor:redacted", requested_at=now)
            report = ChampionChallengerEvaluationEngine(repository=SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector()).evaluate(request, champion=champion, challenger=challenger, validation=validation, generated_at=now)
            print(f"champion-evaluate: evaluation_id={report.evaluation_id} decision={report.decision.value} score={report.evaluation_score}")
        finally:
            store.close()
    elif args.command == "champion-evaluation-show":
        store = RuntimeStateStore(args.db)
        try:
            print(SQLiteChampionChallengerRepository(store._connection).get_report(args.evaluation_id).to_json())
        finally:
            store.close()
    elif args.command == "champion-evaluation-history":
        store = RuntimeStateStore(args.db)
        try:
            reports = SQLiteChampionChallengerRepository(store._connection).list_reports()
            for report in reports:
                print(f"{report.evaluation_id} decision={report.decision.value} score={report.evaluation_score}")
            if not reports:
                print("champion-evaluation-history: none")
        finally:
            store.close()
    elif args.command == "champion-registry-show":
        store = RuntimeStateStore(args.db)
        try:
            entry = SQLiteChampionRegistryRepository(store._connection).get_active(args.slot)
            if entry is None:
                print(f"champion-registry-show: slot={args.slot} none")
            else:
                print(f"champion-registry-show: slot={entry.slot} version={entry.active_version_id} strategy={entry.strategy_ref} fingerprint={entry.fingerprint} revision={entry.revision}")
        finally:
            store.close()
    elif args.command == "champion-history":
        store = RuntimeStateStore(args.db)
        try:
            versions = SQLiteChampionRegistryRepository(store._connection).list_history(args.slot)
            for version in versions:
                print(f"{version.version_id} slot={version.slot} revision={version.revision} strategy={version.strategy_ref} fingerprint={version.fingerprint} activation_type={version.activation_type}")
            if not versions:
                print("champion-history: none")
        finally:
            store.close()
    elif args.command == "champion-bootstrap":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            service = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
            entry = service.bootstrap(strategy_ref=args.strategy, fingerprint=args.fingerprint, backtest_id=args.backtest_id, actor_ref="actor:redacted", activated_at=now, slot=args.slot)
            print(f"champion-bootstrap: slot={entry.slot} version={entry.active_version_id} fingerprint={entry.fingerprint}")
        finally:
            store.close()
    elif args.command == "champion-promotion-request":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            promotion_id = args.promotion_id or f"promotion:{args.evaluation_id}"
            service = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
            request = service.request_promotion(promotion_id, args.evaluation_id, actor_ref="actor:redacted", requested_at=now, slot=args.slot)
            print(f"champion-promotion-request: promotion_id={request.promotion_id} status={request.status.value} evaluation_id={request.evaluation_id}")
        finally:
            store.close()
    elif args.command == "champion-promotion-approve":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            service = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
            entry = service.approve(args.promotion_id, actor_ref="actor:redacted", decided_at=now)
            print(f"champion-promotion-approve: promotion_id={args.promotion_id} active_version={entry.active_version_id} fingerprint={entry.fingerprint}")
        finally:
            store.close()
    elif args.command == "champion-promotion-reject":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            service = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
            request = service.reject(args.promotion_id, actor_ref="actor:redacted", decided_at=now)
            print(f"champion-promotion-reject: promotion_id={request.promotion_id} status={request.status.value}")
        finally:
            store.close()
    elif args.command == "champion-rollback":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            rollback_id = args.rollback_id or f"rollback:{args.slot}:{now}"
            service = ChampionRegistryService(SQLiteChampionRegistryRepository(store._connection), SQLiteChampionChallengerRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector())
            result = service.rollback(ChampionRollbackRequest(rollback_id, args.slot, "actor:redacted", now))
            print(f"champion-rollback: rollback_id={result.rollback_id} restored={result.restored_version_id} active={result.new_version_id}")
        finally:
            store.close()
    elif args.command == "paper-session-create":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            session = _paper_service(store).create_session(args.session_id, slot=args.slot, champion_version_id=args.champion_version_id, fingerprint=args.fingerprint, actor_ref="actor:redacted", created_at=now)
            print(f"paper-session-create: session_id={session.session_id} status={session.status.value} champion_version={session.champion_version_id}")
        finally:
            store.close()
    elif args.command in {"paper-session-start", "paper-session-pause", "paper-session-resume", "paper-session-complete", "paper-session-cancel"}:
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            service = _paper_service(store)
            if args.command == "paper-session-start":
                session = service.start(args.session_id, actor_ref="actor:redacted", at=now)
            elif args.command == "paper-session-pause":
                session = service.pause(args.session_id, actor_ref="actor:redacted", at=now)
            elif args.command == "paper-session-resume":
                session = service.resume(args.session_id, actor_ref="actor:redacted", at=now)
            elif args.command == "paper-session-complete":
                session = service.complete(args.session_id, actor_ref="actor:redacted", at=now)
            else:
                session = service.cancel(args.session_id, actor_ref="actor:redacted", at=now)
            print(f"{args.command}: session_id={session.session_id} status={session.status.value}")
        finally:
            store.close()
    elif args.command == "paper-session-show":
        store = RuntimeStateStore(args.db)
        try:
            session = SQLitePaperTradingSessionRepository(store._connection).get_session(args.session_id)
            print(session.to_json())
        finally:
            store.close()
    elif args.command == "paper-session-list":
        store = RuntimeStateStore(args.db)
        try:
            sessions = SQLitePaperTradingSessionRepository(store._connection).list_sessions()
            for session in sessions:
                print(f"{session.session_id} status={session.status.value} champion_version={session.champion_version_id} fingerprint={session.fingerprint}")
            if not sessions:
                print("paper-session-list: none")
        finally:
            store.close()
    elif args.command == "paper-session-simulate-order":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            result = _paper_service(store).simulate_order(args.session_id, symbol=args.symbol, quantity=args.quantity, price=args.price, side=args.side, actor_ref="actor:redacted", at=now)
            print(f"paper-session-simulate-order: session_id={args.session_id} status={result.status.value} result_id={result.result_id} notional={result.notional:.2f}")
        finally:
            store.close()
    elif args.command == "paper-session-summary":
        store = RuntimeStateStore(args.db)
        try:
            summary = _paper_service(store).summary(args.session_id, generated_at=_utc_now())
            print(f"paper-session-summary: session_id={summary.session_id} status={summary.status.value} simulated_orders={summary.simulated_orders} fills={summary.fills} rejected={summary.rejected_simulated_orders} failed={summary.failed_simulated_orders}")
        finally:
            store.close()
    elif args.command == "paper-revalidation-policy-show":
        policy = PaperRevalidationPolicy()
        if args.json:
            import json

            print(json.dumps(policy.__dict__, sort_keys=True, separators=(",", ":")))
        else:
            print(f"paper-revalidation-policy-show: policy_version={policy.policy_version} minimum_simulated_trades={policy.minimum_simulated_trades} maximum_paper_drawdown={policy.maximum_paper_drawdown:.2f} hard_kill_paper_drawdown={policy.hard_kill_paper_drawdown:.2f}")
    elif args.command == "paper-revalidate":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            sessions = SQLitePaperTradingSessionRepository(store._connection)
            session = sessions.get_session(args.session_id)
            summary = sessions.get_summary(args.session_id)
            active = SQLiteChampionRegistryRepository(store._connection).get_active(session.slot)
            if active is None:
                raise ValueError("active champion is required")
            revalidation_id = args.revalidation_id or f"paper-revalidation:{args.session_id}"
            request = build_paper_revalidation_request(revalidation_id, session=session, actor_ref="actor:redacted", requested_at=now)
            report = PaperRevalidationEngine(repository=SQLitePaperRevalidationRepository(store._connection), event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector()).revalidate(request, active=active, session=session, summary=summary, generated_at=now)
            print(f"paper-revalidate: revalidation_id={report.revalidation_id} status={report.status.value} session_id={report.session_id}")
        finally:
            store.close()
    elif args.command == "paper-revalidation-show":
        store = RuntimeStateStore(args.db)
        try:
            print(SQLitePaperRevalidationRepository(store._connection).get_report(args.revalidation_id).to_json())
        finally:
            store.close()
    elif args.command == "paper-revalidation-history":
        store = RuntimeStateStore(args.db)
        try:
            reports = SQLitePaperRevalidationRepository(store._connection).list_reports()
            for report in reports:
                print(f"{report.revalidation_id} status={report.status.value} session_id={report.session_id}")
            if not reports:
                print("paper-revalidation-history: none")
        finally:
            store.close()
    elif args.command == "execution-policy-show":
        policy = StrategyExecutionPolicy()
        if args.json:
            import json

            print(json.dumps({"policy_version": policy.policy_version, "default_mode": policy.default_mode.value, "live_trading_enabled": policy.live_trading_enabled, "broker_adapter_available": policy.broker_adapter_available}, sort_keys=True, separators=(",", ":")))
        else:
            print(f"execution-policy-show: policy_version={policy.policy_version} default_mode={policy.default_mode.value} live_trading_enabled={policy.live_trading_enabled} broker_adapter_available={policy.broker_adapter_available}")
    elif args.command == "execution-status":
        store = RuntimeStateStore(args.db)
        try:
            plans = SQLiteStrategyExecutionRepository(store._connection).list_plans()
            runs = SQLiteStrategyExecutionRepository(store._connection).list_runs()
            print(f"execution-status: plans={len(plans)} runs={len(runs)}")
        finally:
            store.close()
    elif args.command == "execution-plan":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            request_id = args.plan_id or f"execution:{args.mode}:{now}"
            request = build_strategy_execution_request(request_id, StrategyExecutionMode(args.mode), actor_ref="actor:redacted", requested_at=now, revalidation_id=args.revalidation_id)
            plan = _execution_runtime(store).plan(request)
            print(f"execution-plan: plan_id={plan.plan_id} mode={plan.mode.value} status={plan.status.value} reason={plan.decision.reason}")
        finally:
            store.close()
    elif args.command == "execution-run":
        store = RuntimeStateStore(args.db)
        try:
            run = _execution_runtime(store).run(args.plan_id, actor_ref="actor:redacted", at=_utc_now())
            print(f"execution-run: run_id={run.run_id} mode={run.mode.value} status={run.status.value} reason={run.block_reason or ''} result_ref={run.result_ref or ''}")
        finally:
            store.close()
    elif args.command == "execution-show":
        store = RuntimeStateStore(args.db)
        try:
            print(SQLiteStrategyExecutionRepository(store._connection).get_run(args.run_id).to_json())
        finally:
            store.close()
    elif args.command == "execution-history":
        store = RuntimeStateStore(args.db)
        try:
            runs = SQLiteStrategyExecutionRepository(store._connection).list_runs()
            for run in runs:
                print(f"{run.run_id} mode={run.mode.value} status={run.status.value} reason={run.block_reason or ''}")
            if not runs:
                print("execution-history: none")
        finally:
            store.close()
    elif args.command == "handoff-create":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            request_id = args.request_id or f"handoff:{args.revalidation_id}:{now}"
            request = build_strategy_handoff_request(request_id, revalidation_id=args.revalidation_id, actor_ref="actor:redacted", requested_at=now, champion_slot=args.champion_slot)
            package = _handoff_service(store).create(request)
            print(f"handoff-create: package_id={package.package_id} status={package.status.value} checksum={package.checksum}")
        finally:
            store.close()
    elif args.command == "handoff-show":
        store = RuntimeStateStore(args.db)
        try:
            print(SQLiteStrategyHandoffRepository(store._connection).get_package(args.package_id).to_json())
        finally:
            store.close()
    elif args.command == "handoff-history":
        store = RuntimeStateStore(args.db)
        try:
            packages = SQLiteStrategyHandoffRepository(store._connection).list_packages()
            for package in packages:
                print(f"{package.package_id} status={package.status.value} checksum={package.checksum} revalidation={package.manifest.paper_revalidation_id}")
            if not packages:
                print("handoff-history: none")
        finally:
            store.close()
    elif args.command == "handoff-export":
        store = RuntimeStateStore(args.db)
        try:
            package = SQLiteStrategyHandoffRepository(store._connection).get_package(args.package_id)
            output = safe_handoff_export_path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(package.to_json(), encoding="utf-8")
            print(f"handoff-export: package_id={package.package_id} output={output}")
        finally:
            store.close()
    elif args.command == "handoff-approve":
        store = RuntimeStateStore(args.db)
        try:
            package = _handoff_service(store).approve(args.package_id, approver_ref="actor:redacted", decided_at=_utc_now())
            print(f"handoff-approve: package_id={package.package_id} status={package.status.value} checksum={package.checksum}")
        finally:
            store.close()
    elif args.command == "handoff-reject":
        store = RuntimeStateStore(args.db)
        try:
            package = _handoff_service(store).reject(args.package_id, actor_ref="actor:redacted", decided_at=_utc_now(), reason=args.reason)
            print(f"handoff-reject: package_id={package.package_id} status={package.status.value}")
        finally:
            store.close()
    elif args.command == "deployment-status":
        store = RuntimeStateStore(args.db)
        try:
            repo = SQLiteStrategyDeploymentRepository(store._connection)
            print(f"deployment-status: plans={len(repo.list_plans())} runs={len(repo.list_runs())} backups={len(repo.list_backups())}")
        finally:
            store.close()
    elif args.command == "deployment-plan":
        store = RuntimeStateStore(args.db)
        try:
            now = _utc_now()
            request_id = args.request_id or f"deployment:{args.package_id}:{now}"
            request = build_strategy_deployment_request(request_id, package_id=args.package_id, actor_ref="actor:redacted", requested_at=now, target_id=args.target_id)
            plan = _deployment_service(store).plan(request)
            print(f"deployment-plan: plan_id={plan.plan_id} status={plan.status.value} reason={plan.reason}")
        finally:
            store.close()
    elif args.command == "deployment-run":
        store = RuntimeStateStore(args.db)
        try:
            service = _deployment_service(store, target_dir=args.target_dir)
            run = service.run(args.plan_id, actor_ref="actor:redacted", at=_utc_now())
            print(f"deployment-run: run_id={run.run_id} status={run.status.value} backup_id={run.backup_id or ''} message={run.message}")
        finally:
            store.close()
    elif args.command == "deployment-show":
        store = RuntimeStateStore(args.db)
        try:
            print(SQLiteStrategyDeploymentRepository(store._connection).get_run(args.run_id).to_json())
        finally:
            store.close()
    elif args.command == "deployment-history":
        store = RuntimeStateStore(args.db)
        try:
            runs = SQLiteStrategyDeploymentRepository(store._connection).list_runs()
            for run in runs:
                print(f"{run.run_id} package_id={run.package_id} status={run.status.value} backup_id={run.backup_id or ''}")
            if not runs:
                print("deployment-history: none")
        finally:
            store.close()
    elif args.command == "deployment-backups":
        store = RuntimeStateStore(args.db)
        try:
            backups = SQLiteStrategyDeploymentRepository(store._connection).list_backups()
            for backup in backups:
                print(f"{backup.backup_id} package_id={backup.package_id} restore_ref={backup.restore_ref}")
            if not backups:
                print("deployment-backups: none")
        finally:
            store.close()
    elif args.command == "v5-status":
        store = RuntimeStateStore(args.db)
        try:
            runs = SQLiteGaonV5PipelineRepository(store._connection).list_runs()
            print(f"v5-status: runs={len(runs)} schema_version={store.status().schema_version}")
        finally:
            store.close()
    elif args.command == "v5-pipeline-show":
        store = RuntimeStateStore(args.db)
        try:
            print(SQLiteGaonV5PipelineRepository(store._connection).get_run(args.run_id).to_json())
        finally:
            store.close()
    elif args.command == "v5-pipeline-history":
        store = RuntimeStateStore(args.db)
        try:
            runs = SQLiteGaonV5PipelineRepository(store._connection).list_runs()
            for run in runs:
                print(f"{run.run_id} status={run.status.value} stage={run.current_stage.value} message={run.message}")
            if not runs:
                print("v5-pipeline-history: none")
        finally:
            store.close()
    elif args.command == "v5-release-check":
        store = RuntimeStateStore(args.db)
        try:
            request = GaonV5PipelineRequest("v5-release-check", "v5-release-check", "actor:redacted", _utc_now(), approve_promotion=True, approve_deployment=True)
            report = GaonV5PipelineOrchestrator(store._connection, event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector()).run_demo(request)
            print(f"v5-release-check: status={report.status.value} stage={report.current_stage.value} message={report.message}")
            return 0 if report.status.value == "completed" else 1
        finally:
            store.close()
    elif args.command == "v5-demo":
        if args.dry_run:
            store = RuntimeStateStore(args.db)
            try:
                now = _utc_now()
                run_id = args.run_id or f"v5-demo:{now}"
                request = GaonV5PipelineRequest(run_id, run_id, "actor:redacted", now, approve_promotion=args.approve_promotion, approve_deployment=args.approve_deployment, scenario=args.scenario)
                report = GaonV5PipelineOrchestrator(store._connection, event_store=SQLiteEventStore(store._connection), metrics=MetricsCollector()).run_demo(request)
                print(report.to_json())
            finally:
                store.close()
        else:
            print("v5-demo: execute mode is intentionally unsupported; deterministic demo remains dry-run")
            return 1
    elif args.command == "research-proposals-list":
        print("research-proposals: none")
    elif args.command in {"research-proposals-show", "research-proposals-approve", "research-proposals-reject", "research-proposals-revise"}:
        print(f"{args.command}: dry-run proposal_id={args.proposal_id}")
    elif args.command == "research-plan":
        print(f"research-plan: dry-run query={args.query}")
    elif args.command == "research-run":
        store = RuntimeStateStore(":memory:")
        try:
            run, report = ResearchOrchestratorV3(SQLiteResearchRunRepository(store._connection)).run(args.query, run_id="cli-run", dry_run=args.dry_run)
            print(f"research-run: {run.status.value} report={report.title}")
        finally:
            store.close()
    elif args.command == "research-status":
        print(f"research-status: dry-run run_id={args.run_id}")
    elif args.command == "research-report":
        print(f"# Research Report\n\nrun_id={args.run_id}\nformat={args.format}")
    elif args.command == "research-resume":
        print(f"research-resume: dry-run run_id={args.run_id}")
    elif args.command in {"telegram-check", "assistant-check", "notion-check"}:
        print(f"{args.command}: dry-run readiness check")
    elif args.command == "daily-report":
        print(build_daily_report(args.date, f"{args.date}T00:00:00Z").to_text())
    elif args.command == "weekly-review":
        print(build_weekly_review(args.week_start, args.week_start, f"{args.week_start}T00:00:00Z").to_text())
    elif args.command == "telegram-get-me":
        if args.dry_run:
            print("telegram-get-me: dry-run")
        else:
            config = _load_execute_config(require_allowed_chat_ids=False)
            _print_bot_info(_telegram_client(config).get_me())
    elif args.command == "telegram-discover-chat":
        if args.dry_run:
            print("telegram-discover-chat: dry-run")
        else:
            config = _load_execute_config(require_allowed_chat_ids=False)
            chats = discover_chats(_telegram_client(config), received_at=_utc_now())
            _print_discovered_chats(chats)
    elif args.command == "telegram-send-smoke":
        if args.dry_run:
            print("telegram-send-smoke: dry-run")
        else:
            config = _load_execute_config(require_allowed_chat_ids=True)
            response = send_smoke(_telegram_client(config), config, args.chat_id)
            print(f"telegram-send-smoke: sent message_id={response.message_id or 'unknown'}")
    elif args.command == "telegram-poll-once":
        if args.dry_run:
            print("telegram-poll-once: dry-run")
        else:
            config = _load_execute_config(require_allowed_chat_ids=True)
            store = RuntimeStateStore(args.db)
            try:
                results = poll_once(_telegram_client(config), config, offset=args.offset, received_at=_utc_now(), state=store.telegram, runtime_store=store)
                _print_poll_results(results)
            finally:
                store.close()
    else:
        mode = "dry-run" if getattr(args, "dry_run", True) else "execute requested but not implemented"
        print(f"{args.command}: {mode}")
    return 0


def discover_chats(client: Any, *, received_at: str) -> tuple[TelegramDiscoveredChat, ...]:
    updates = client.get_updates(timeout=0, limit=100)
    return discover_private_chats(updates, received_at=received_at)


def poll_once(
    client: Any,
    config: GaonRuntimeConfig,
    *,
    offset: int | None,
    received_at: str,
    state: TelegramStateRepository | None = None,
    runtime_store: RuntimeStateStore | None = None,
    timeout: int = 0,
    limit: int = 100,
) -> tuple[TelegramPollResult, ...]:
    effective_offset = offset if offset is not None else state.get_offset(TELEGRAM_POLL_OFFSET_KEY) if state is not None else None
    updates = client.get_updates(offset=effective_offset, timeout=timeout, limit=limit)
    runtime = _telegram_runtime(config, runtime_store)
    results: list[TelegramPollResult] = []
    for payload in updates:
        update = parse_update_result(payload, received_at=received_at)
        if update.message is not None and state is not None:
            processed_key = f"telegram:{update.message.chat.chat_id}:{update.message.message_id}"
            if not state.mark_processed(processed_key, received_at):
                results.append(TelegramPollResult(update.update_id, update.next_offset, "duplicate", chat_id=update.message.chat.chat_id))
                _save_poll_offset(state, update.next_offset, received_at)
                continue
        result = process_update(update, runtime, client)
        results.append(result)
        if state is not None:
            _save_poll_offset(state, update.next_offset, received_at)
    return tuple(results)


def _telegram_runtime(config: GaonRuntimeConfig, runtime_store: RuntimeStateStore | None) -> TelegramRuntime:
    if runtime_store is None:
        return TelegramRuntime(ConversationRuntime(), allowed_chat_ids=config.telegram_allowed_chat_ids)
    from gaon.runtime.telegram_agent import TelegramConversationAgent

    return TelegramRuntime(TelegramConversationAgent(config, runtime_store._connection), allowed_chat_ids=config.telegram_allowed_chat_ids)


def send_smoke(client: TelegramClient, config: GaonRuntimeConfig, chat_id: str):
    if chat_id not in config.telegram_allowed_chat_ids:
        raise ConfigurationError("telegram-send-smoke chat-id must be in GAON_TELEGRAM_ALLOWED_CHAT_IDS")
    return client.send_message(chat_id, TELEGRAM_SMOKE_TEXT)


def _load_execute_config(*, require_allowed_chat_ids: bool) -> GaonRuntimeConfig:
    config = load_runtime_config(os.environ)
    if config.mode != "execute" or config.dry_run:
        raise ConfigurationError("execute requires GAON_RUNTIME_MODE=execute and GAON_DRY_RUN=false")
    if not config.telegram_enabled or not config.telegram_bot_token:
        raise ConfigurationError("execute requires GAON_TELEGRAM_ENABLED=true and GAON_TELEGRAM_BOT_TOKEN")
    if require_allowed_chat_ids and not config.telegram_allowed_chat_ids:
        raise ConfigurationError("message execution requires GAON_TELEGRAM_ALLOWED_CHAT_IDS")
    return config


def _telegram_client(config: GaonRuntimeConfig) -> TelegramBotApiClient:
    if not config.telegram_bot_token:
        raise ConfigurationError("telegram token is required")
    return TelegramBotApiClient(config.telegram_bot_token)


def _print_bot_info(info: dict) -> None:
    print(f"bot id: {info.get('id', 'unknown')}")
    print(f"username: {info.get('username', 'unknown')}")
    print(f"first name: {info.get('first_name', 'unknown')}")
    if "can_join_groups" in info:
        print(f"can_join_groups: {info['can_join_groups']}")


def _print_discovered_chats(chats: tuple[TelegramDiscoveredChat, ...]) -> None:
    if not chats:
        print("No private chat found. Send a message to the bot and run this command again.")
        return
    for chat in chats:
        print(f"chat_id={chat.chat_id} chat_type={chat.chat_type} username={chat.username or ''} first_name={chat.first_name or ''} preview={chat.message_preview}")


def _print_poll_results(results: tuple[TelegramPollResult, ...]) -> None:
    if not results:
        print("telegram-poll-once: no updates")
        return
    for result in results:
        print(f"update_id={result.update_id} next_offset={result.next_offset} status={result.status} chat_id={result.chat_id or ''}")


def _save_poll_offset(state: TelegramStateRepository, next_offset: int, updated_at: str) -> None:
    current = state.get_offset(TELEGRAM_POLL_OFFSET_KEY)
    if current is None or next_offset > current:
        state.save_offset(TELEGRAM_POLL_OFFSET_KEY, next_offset, updated_at)


def _find_backtest_by_fingerprint(repository: SQLiteBacktestRepository, fingerprint: str):
    matches = tuple(result for result in repository.list_results() if result.fingerprint == fingerprint)
    if not matches:
        raise KeyError(fingerprint)
    return matches[0]


def _runtime_tick(config: GaonRuntimeConfig, store: RuntimeStateStore, metrics: MetricsCollector):
    worker = TelegramPollingWorker(config, store, client_factory=_telegram_client, metrics=metrics)
    return worker.tick


def _paper_service(store: RuntimeStateStore) -> PaperTradingForwardTestService:
    return PaperTradingForwardTestService(
        SQLitePaperTradingSessionRepository(store._connection),
        SQLiteChampionRegistryRepository(store._connection),
        trading_repository=SQLiteTradingRepository(store._connection),
        event_store=SQLiteEventStore(store._connection),
        metrics=MetricsCollector(),
    )


def _execution_runtime(store: RuntimeStateStore) -> StrategyExecutionRuntime:
    return StrategyExecutionRuntime(
        SQLiteStrategyExecutionRepository(store._connection),
        SQLiteChampionRegistryRepository(store._connection),
        revalidations=SQLitePaperRevalidationRepository(store._connection),
        trading_repository=SQLiteTradingRepository(store._connection),
        event_store=SQLiteEventStore(store._connection),
        metrics=MetricsCollector(),
    )


def _handoff_service(store: RuntimeStateStore) -> StrategyHandoffService:
    return StrategyHandoffService(
        SQLiteStrategyHandoffRepository(store._connection),
        SQLiteChampionRegistryRepository(store._connection),
        SQLitePaperRevalidationRepository(store._connection),
        SQLiteBacktestRepository(store._connection),
        event_store=SQLiteEventStore(store._connection),
        metrics=MetricsCollector(),
    )


def _deployment_service(store: RuntimeStateStore, target_dir: str | None = None) -> StrategyDeploymentService:
    adapter = LocalSafeStrategyDeploymentAdapter(target_dir) if target_dir else FakeStrategyDeploymentAdapter()
    return StrategyDeploymentService(
        SQLiteStrategyDeploymentRepository(store._connection),
        SQLiteStrategyHandoffRepository(store._connection),
        SQLiteChampionRegistryRepository(store._connection),
        adapter,
        event_store=SQLiteEventStore(store._connection),
        metrics=MetricsCollector(),
        policy=StrategyDeploymentPolicy(target_id="generic-runtime"),
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _research_ops_table_counts(connection: Any) -> dict[str, int]:
    tables = (
        "research_operation_reports",
        "research_config_approvals",
        "strategy_config_versions",
        "strategy_config_audit",
    )
    return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


def _retest_table_counts(connection: Any) -> dict[str, int]:
    tables = (
        "research_retest_runs",
        "research_retest_evidence",
        "research_period_plans",
    )
    return {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}


def _contains_hangul(text: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in text)


def _strict_real_research_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "request_text": "20일 고가 돌파 종가 > MA20 > MA60 거래량 20일 평균 이상 손절 -5% 10일 저점 이탈 청산",
        "dataset": {
            "dataset_id": "dataset:real:yahoo:005930:2025-01-02:2026-07-24",
            "symbols": [{"schema_version": 1, "symbol": "005930", "name": "Samsung Electronics", "market": "KOSPI", "exchange": "KRX"}],
            "bars": [{"timestamp": f"2025-01-{index + 2:02d}", "symbol": "005930", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1000000, "trading_value": 100000000} for index in range(28)],
            "metadata": {"schema_version": 1, "source": "real:yahoo-chart", "market": "KOSPI", "timeframe": "daily", "start_date": "2025-01-02", "end_date": "2026-07-24", "adjusted": True, "retrieved_at": _utc_now(), "fixture_backed": False},
        },
        "quality": {"schema_version": 1, "status": "pass_with_warnings", "findings": [{"code": "provider_gap", "severity": "warning", "message": "real:yahoo-chart missing bar on open KRX date 2025-09-19"}]},
        "strategy": {
            "entry": {
                "breakout_lookback": {"value": 20, "provenance": "user_provided"},
                "close_gt_ma20": {"value": True, "provenance": "user_provided"},
                "ma20_gt_ma60": {"value": True, "provenance": "user_provided"},
            },
            "exit": {"protective_stop_pct": {"value": -5.0, "provenance": "user_provided"}, "channel_exit_lookback": {"value": 10, "provenance": "user_provided"}},
            "filters": {"volume_gte_ma20": {"value": True, "provenance": "user_provided"}},
        },
        "assumptions": {
            "commission": {"value": 0.00015, "provenance": "default"},
            "tax": {"value": 0.0018, "provenance": "default"},
            "slippage": {"value": 0.0005, "provenance": "default"},
            "position_sizing": {"value": "single_position_all_cash", "provenance": "default"},
            "initial_capital": {"value": 1000000.0, "provenance": "default"},
        },
        "backtest": {
            "result_id": "krx-real-backtest-result:strict-grounding",
            "run_id": "strict-grounding",
            "status": "completed",
            "source": "real",
            "metrics": {"total_return": 0.047, "cagr": 0.031, "mdd": 0.052, "sharpe": 0.74, "win_rate": 0.666667, "profit_factor": 1.42, "trade_count": 3, "wins": 2, "losses": 1, "average_trade": 15666.67, "expectancy": 15666.67, "exposure": 0.18, "ending_equity": 1047000.0},
            "warnings": ("real public data source; verify freshness before decisions",),
        },
        "validation": {"validation_id": "validation:strict-grounding", "passed": True, "findings": []},
        "critic_findings": [{"code": "provider_gap", "message_ko": "데이터 공급자 gap이 있으므로 결과 해석 시 해당 일자를 명시해야 합니다.", "severity": "warning"}],
        "candidates": [
            {"candidate_id": "candidate:breakout30", "backtest_result": {"metrics": {"trade_count": 2, "total_return": 0.038, "mdd": 0.044}}},
            {"candidate_id": "candidate:exit15", "backtest_result": {"metrics": {"trade_count": 3, "total_return": 0.041, "mdd": 0.049}}},
        ],
        "comparison": {"rows": [{"candidate_id": "original", "total_return": 0.047, "mdd": 0.052, "trade_count": 3}, {"candidate_id": "candidate:breakout30", "total_return": 0.038, "mdd": 0.044, "trade_count": 2}]},
        "automatic_order": False,
        "automatic_champion_promotion": False,
    }


class _StrictGroundingFakeExecutor:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def assistant_tool_definitions(self) -> tuple[object, ...]:
        return ()

    def execute(self, request: ToolRequest) -> ToolResult:
        if request.tool_name != "krx_real_research":
            return ToolResult(request.tool_name, "denied", {}, ("unexpected tool",))
        return ToolResult("krx_real_research", "success", self._payload)


class _StrictGroundingFakeProvider:
    def __init__(self) -> None:
        self.tool_result_roundtrip_count = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake-strict-grounding", "fixture", False, True, 2048)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake-strict-grounding", True)

    def respond(self, request) -> AssistantProviderResponse:
        if request.tool_results:
            self.tool_result_roundtrip_count += 1
            return AssistantProviderResponse(
                "검증 결과 trade_count=4, win=2, loss=2, average return=1.33%, MDD=8%, fixed risk=1.0%, daily rebalance, risk 0.5% -> MDD 4%, take profit 3%, RSI 20 filter, volume 1.5x, 10일 기간입니다.",
                provider_name="fake-strict-grounding",
                route="provider",
            )
        return AssistantProviderResponse(
            "",
            provider_name="fake-strict-grounding",
            route="provider",
            tool_calls=(AssistantToolCall("call-strict-krx", "krx_real_research", {"request_text": request.text, "symbol": "005930"}),),
        )


def _strict_real_safe_tool_executor(store: RuntimeStateStore, payload: dict[str, object]) -> SafeToolExecutor:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            "krx_real_research",
            "Run the read-only KRX real-research pipeline with explicit source provenance.",
            ToolRiskLevel.READ_ONLY,
            required_args=("request_text",),
            allowed_args=("symbol",),
        ),
        lambda _args: payload,
    )
    return SafeToolExecutor(registry, store.tool_audit)


def _telegram_strict_real_update(run_id: str) -> dict[str, object]:
    return {
        "update_id": 9100,
        "message": {
            "message_id": abs(hash(run_id)) % 100000000,
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 200, "username": "youngha"},
            "text": (
                "가온아 삼성전자 실제 데이터로 아래 전략을 백테스트하고 약점을 분석한 뒤 개선 후보까지 비교해줘.\n\n"
                "20일 고가 돌파\n"
                "종가 > MA20 > MA60\n"
                "거래량 20일 평균 이상\n"
                "손절 -5%\n"
                "10일 저점 이탈 청산"
            ),
        },
    }


def _production_real_research_text() -> str:
    return (
        "가온아 삼성전자 실제 데이터로 아래 전략을 백테스트하고 약점을 분석한 뒤 개선 후보까지 비교해줘.\n\n"
        "20일 고가 돌파\n"
        "종가 > MA20 > MA60\n"
        "거래량 20일 평균 이상\n"
        "손절 -5%\n"
        "10일 저점 이탈 청산"
    )


def _telegram_update_with_text(run_id: str, suffix: str, text: str) -> dict[str, object]:
    return {
        "update_id": 9200 + (abs(hash((run_id, suffix))) % 700),
        "message": {
            "message_id": abs(hash((run_id, suffix, "message"))) % 100000000,
            "chat": {"id": 100, "type": "private"},
            "from": {"id": 200, "username": "youngha"},
            "text": text,
        },
    }


def _failure_tool_executor(store: RuntimeStateStore, exc: Exception) -> SafeToolExecutor:
    registry = ToolRegistry()

    def raise_failure(_args):
        raise exc

    registry.register(
        ToolDefinition(
            "krx_real_research",
            "Run the read-only KRX real-research pipeline with explicit source provenance.",
            ToolRiskLevel.READ_ONLY,
            required_args=("request_text",),
            allowed_args=("symbol",),
        ),
        raise_failure,
    )
    return SafeToolExecutor(registry, store.tool_audit)


def _run_telegram_failure_case(store: RuntimeStateStore, run_id: str, suffix: str, tool_executor, provider, text: str) -> str:
    client = _ReleaseCheckTelegramClient()
    config = GaonRuntimeConfig(
        mode="execute",
        dry_run=False,
        telegram_enabled=True,
        telegram_bot_token="synthetic-token",
        telegram_allowed_chat_ids=("100",),
        approval_signing_secret="synthetic-approval-secret",
        assistant_enabled=True,
        assistant_provider="openai-compatible",
        assistant_api_key="ollama-dummy-key",
        assistant_base_url="http://ollama.invalid/v1",
        assistant_model="qwen3:8b",
    )
    update = parse_update_result(_telegram_update_with_text(run_id, suffix, text), received_at=_utc_now())
    runtime = TelegramRuntime(
        TelegramConversationAgent(config, store._connection, assistant_provider=provider, tool_executor=tool_executor),
        allowed_chat_ids=("100",),
    )
    result = process_update(update, runtime, client)
    if result.status != "sent" or not client.sent:
        raise ConfigurationError(f"telegram failure case did not send a classified response: {suffix}:{result.status}")
    return client.sent[0][1]


class _StrictTelegramHallucinatingProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake-telegram-hallucinating", "fixture", False, True, 2048)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake-telegram-hallucinating", True)

    def respond(self, request) -> AssistantProviderResponse:
        self.calls += 1
        return AssistantProviderResponse(
            "총 수익률 5.32%, 10일 기간, 평균 거래 수익률 1.77%, MDD 8%, PF 1.42, 거래 횟수 4회입니다. "
            "동시에 10일간 단 1회 청산했고 -3% 손절, 5% 익절, RSI(14) 30, MA15/MA90, 거래량 평균 * 1.5를 추천합니다.",
            provider_name="fake-telegram-hallucinating",
            route="provider",
        )


class _TimeoutAssistantProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake-timeout", "fixture", False, True, 2048)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake-timeout", True)

    def respond(self, request) -> AssistantProviderResponse:
        self.calls += 1
        raise ProviderTimeoutError("synthetic provider timeout")


class _RaisingToolExecutor:
    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def assistant_tool_definitions(self) -> tuple[object, ...]:
        return ()

    def execute(self, request):
        raise self._exc


class _ReleaseCheckTelegramClient:
    def __init__(self, updates: tuple[dict[str, object], ...] = ()) -> None:
        self._updates = updates
        self.sent: list[tuple[str, str]] = []

    def get_updates(self, *, offset=None, timeout=0, limit=100):
        return self._updates

    def send_message(self, chat_id: str, text: str, parse_mode=None, reply_to_message_id=None):
        from gaon.integrations.telegram.contracts import TelegramResponse

        self.sent.append((chat_id, text))
        return TelegramResponse(chat_id, text, dry_run=False, correlation_id=f"release-check:{len(self.sent)}", message_id=str(len(self.sent)))


def _agent_run_plan(agent: str, now: str) -> ExecutivePlan:
    mapping = {
        "research": (RoutingDecision.RESEARCH, AgentSelection.RESEARCH_BRAIN, (ToolSelection.RESEARCH_PLANNER, ToolSelection.EVIDENCE_SEARCH, ToolSelection.KNOWLEDGE_PROPOSAL)),
        "coding": (RoutingDecision.RUNTIME, AgentSelection.CODING_ASSISTANT, (ToolSelection.NOOP,)),
        "memory": (RoutingDecision.MEMORY, AgentSelection.LEARNING_MEMORY, (ToolSelection.MEMORY_RETRIEVAL,)),
        "trading": (RoutingDecision.TRADING, AgentSelection.TRADING_AGENT, (ToolSelection.TRADING_SIMULATION,)),
    }
    decision, selected_agent, tools = mapping[agent]
    return ExecutivePlan(
        plan_id="exec-plan:cli-agent-request",
        request_id="cli-agent-request",
        routing_decision=decision,
        agents=(selected_agent,),
        tools=tools,
        approval_required=False,
        reason="CLI deterministic agent smoke plan",
        provider="deterministic",
        route="agent_run",
        created_at=now,
        scope="agent",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
    )


def _schedule_agent_constraints(agent: str | None):
    if agent == "research":
        return AgentSelection.RESEARCH_BRAIN, (ToolSelection.RESEARCH_PLANNER,)
    if agent == "memory":
        return AgentSelection.LEARNING_MEMORY, (ToolSelection.MEMORY_RETRIEVAL,)
    if agent == "coding":
        return AgentSelection.CODING_ASSISTANT, (ToolSelection.NOOP,)
    if agent == "trading":
        return AgentSelection.TRADING_AGENT, (ToolSelection.TRADING_SIMULATION,)
    return None, ()


def _add_dry_run_flags(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", help="prepare output without external side effects")
    mode.add_argument("--execute", dest="dry_run", action="store_false", help="request execution after all production gates pass")
    parser.set_defaults(dry_run=True)


def _conversation_status_rows(store: RuntimeStateStore, session_id: str | None) -> list[dict[str, object]]:
    if session_id is None:
        rows = store._connection.execute(
            """
            SELECT s.session_id, s.status, s.updated_at, COUNT(m.message_id) AS messages
              FROM conversation_sessions s
              LEFT JOIN conversation_messages m ON s.session_id = m.session_id
             GROUP BY s.session_id, s.status, s.updated_at
             ORDER BY s.updated_at DESC, s.session_id DESC
             LIMIT 20
            """
        ).fetchall()
    else:
        rows = store._connection.execute(
            """
            SELECT s.session_id, s.status, s.updated_at, COUNT(m.message_id) AS messages
              FROM conversation_sessions s
              LEFT JOIN conversation_messages m ON s.session_id = m.session_id
             WHERE s.session_id = ?
             GROUP BY s.session_id, s.status, s.updated_at
            """,
            (session_id,),
        ).fetchall()
    return [{"session_id": str(row[0]), "status": str(row[1]), "updated_at": str(row[2]), "messages": int(row[3])} for row in rows]


def _dumps_json(payload: dict[str, object]) -> str:
    return dumps_json(payload)


def _sanitized_base_url(value: str | None) -> str:
    if not value:
        return "unset"
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return "configured"
    return f"{parsed.scheme}://{parsed.netloc}"


class _NoopProjection:
    projection_id = "cli:dry-run"

    def apply(self, event: DurableEvent, *, dry_run: bool) -> None:
        if not dry_run:
            raise RuntimeError("CLI replay diagnostic must remain dry-run")


class _LongResponseReleaseProvider:
    def __init__(self) -> None:
        self.calls = 0

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("fake-long-response", "fixture", False, False, 128)

    def health(self) -> ProviderHealth:
        return ProviderHealth("fake-long-response", True)

    def respond(self, _request) -> AssistantProviderResponse:
        self.calls += 1
        if self.calls == 1:
            return AssistantProviderResponse(
                text="시작 문단입니다. " + ("긴 한국어 응답입니다. " * 30),
                provider_name="fake-long-response",
                finish_reason="length",
                truncated=True,
                warnings=("LLM_TRUNCATED",),
            )
        return AssistantProviderResponse(
            text="이어서 작성합니다. 중복 없이 continuation을 완료했습니다. 마무리 문단입니다.",
            provider_name="fake-long-response",
            finish_reason="stop",
        )


if __name__ == "__main__":
    raise SystemExit(main())
