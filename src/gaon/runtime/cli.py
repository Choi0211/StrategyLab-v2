"""Safe runtime CLI."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
import sys
from typing import Any
from urllib.parse import urlparse

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
from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import discover_private_chats, parse_update_result
from gaon.runtime.agents import AgentDispatcher, AgentRequest, default_agent_registry
from gaon.runtime.agent_planner import AgentPlanExecutor, AgentPlanner, AgentPlanPolicy
from gaon.runtime.config import GaonRuntimeConfig, load_runtime_config
from gaon.runtime.conversation import ConversationRuntime
from gaon.runtime.daily_research import DailyResearchPipeline, DailyResearchProfile, DailyResearchRepository, record_daily_research_profile_metric, daily_research_event
from gaon.runtime.errors import ConfigurationError, GaonRuntimeError
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.executive_planner import AgentSelection, DeterministicExecutivePlanner, ExecutivePlan, ExecutiveRequest, RoutingDecision, ToolSelection, executive_plan_event
from gaon.runtime.health import readiness
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.provider_registry import build_assistant_provider
from gaon.runtime.reports import build_daily_report, build_weekly_review
from gaon.runtime.repositories import TelegramStateRepository
from gaon.runtime.scheduled_automation import ScheduleDefinition, ScheduledAutomationRunner, ScheduledJob, ScheduledJobRepository, record_scheduled_job_metric, scheduled_event
from gaon.runtime.serialization import dumps_json
from gaon.runtime.service import GaonRuntimeService
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_worker import TelegramPollingWorker
from gaon.runtime.v5_pipeline import GaonV5PipelineOrchestrator, GaonV5PipelineRequest, SQLiteGaonV5PipelineRepository
from gaon.research.orchestration_v3 import ResearchOrchestratorV3, SQLiteResearchRunRepository

TELEGRAM_SMOKE_TEXT = "Gaon Telegram 연결 테스트가 성공했습니다."
TELEGRAM_POLL_OFFSET_KEY = "__telegram_poll__"


def main(argv: list[str] | None = None) -> int:
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
    agent_status = sub.add_parser("agent-status")
    agent_status.add_argument("--db", default=":memory:")
    agent_plan_history = sub.add_parser("agent-plan-history")
    agent_plan_history.add_argument("--db", default=":memory:")
    tool_chain_history = sub.add_parser("tool-chain-history")
    tool_chain_history.add_argument("--db", default=":memory:")
    llm_agent_release = sub.add_parser("llm-agent-release-check")
    llm_agent_release.add_argument("--db", default=":memory:")
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
            checks = (
                brain.respond(LLMConversationRequest("release-check:runtime", "cli", "cli", "가온 상태 알려줘", _utc_now(), "release-check:runtime")),
                brain.respond(LLMConversationRequest("release-check:champion", "cli", "cli", "현재 챔피언 상태 알려줘", _utc_now(), "release-check:champion")),
                brain.respond(LLMConversationRequest("release-check:v5", "cli", "cli", "v5 파이프라인 실행 이력 알려줘", _utc_now(), "release-check:v5")),
            )
            if {call for response in checks for call in response.tool_calls} != {"runtime_status", "champion_status", "v5_pipeline_history"}:
                raise ConfigurationError("conversation release check failed to route deterministic read-only tools")
            print(
                "conversation-release-check: PASS "
                f"schema_version={store.status().schema_version} provider={config.assistant_provider} "
                f"free_only={config.free_only_mode} tools={len(tools)}"
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


if __name__ == "__main__":
    raise SystemExit(main())
