"""Safe runtime CLI."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
import sys
from typing import Any

from gaon.integrations.telegram.client import TelegramBotApiClient
from gaon.integrations.telegram.contracts import TelegramClient, TelegramDiscoveredChat, TelegramPollResult
from gaon.integrations.telegram.runtime import TelegramRuntime, process_update
from gaon.integrations.telegram.transport import discover_private_chats, parse_update_result
from gaon.runtime.agents import AgentDispatcher, AgentRequest, default_agent_registry
from gaon.runtime.config import GaonRuntimeConfig, load_runtime_config
from gaon.runtime.conversation import ConversationRuntime
from gaon.runtime.errors import ConfigurationError, GaonRuntimeError
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.executive_planner import AgentSelection, DeterministicExecutivePlanner, ExecutivePlan, ExecutiveRequest, RoutingDecision, ToolSelection, executive_plan_event
from gaon.runtime.health import readiness
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.reports import build_daily_report, build_weekly_review
from gaon.runtime.scheduled_automation import ScheduleDefinition, ScheduledAutomationRunner, ScheduledJob, ScheduledJobRepository, record_scheduled_job_metric, scheduled_event
from gaon.runtime.service import GaonRuntimeService
from gaon.runtime.storage import RuntimeStateStore
from gaon.research.orchestration_v3 import ResearchOrchestratorV3, SQLiteResearchRunRepository

TELEGRAM_SMOKE_TEXT = "Gaon Telegram 연결 테스트가 성공했습니다."


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
    run.add_argument("--once", action="store_true", default=True)
    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("--db", default=":memory:")
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
    agent_run.add_argument("--agent", choices=("research", "coding", "memory"), required=True)
    agent_run.add_argument("--request", required=True)
    agent_run.add_argument("--db", default=":memory:")
    agent_run.add_argument("--json", action="store_true")
    schedule_create = sub.add_parser("schedule-create")
    schedule_create.add_argument("--db", default="runtime.sqlite")
    schedule_create.add_argument("--job-id", required=True)
    schedule_create.add_argument("--name", required=True)
    schedule_create.add_argument("--request", required=True)
    schedule_create.add_argument("--next-run-at", required=True)
    schedule_create.add_argument("--agent", choices=("research", "memory", "coding"), required=False)
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
            service = GaonRuntimeService(load_runtime_config(os.environ), store)
            status = service.run_once() if args.command == "run" else service.status()
            print(f"running={status.running} ticks={status.ticks} active_workers={status.active_workers}")
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
            results = poll_once(_telegram_client(config), config, offset=args.offset, received_at=_utc_now())
            _print_poll_results(results)
    else:
        mode = "dry-run" if getattr(args, "dry_run", True) else "execute requested but not implemented"
        print(f"{args.command}: {mode}")
    return 0


def discover_chats(client: Any, *, received_at: str) -> tuple[TelegramDiscoveredChat, ...]:
    updates = client.get_updates(timeout=0, limit=100)
    return discover_private_chats(updates, received_at=received_at)


def poll_once(client: Any, config: GaonRuntimeConfig, *, offset: int | None, received_at: str) -> tuple[TelegramPollResult, ...]:
    updates = client.get_updates(offset=offset, timeout=0, limit=100)
    runtime = TelegramRuntime(ConversationRuntime(), allowed_chat_ids=config.telegram_allowed_chat_ids)
    results: list[TelegramPollResult] = []
    for payload in updates:
        update = parse_update_result(payload, received_at=received_at)
        results.append(process_update(update, runtime, client))
    return tuple(results)


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


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _agent_run_plan(agent: str, now: str) -> ExecutivePlan:
    mapping = {
        "research": (RoutingDecision.RESEARCH, AgentSelection.RESEARCH_BRAIN, (ToolSelection.RESEARCH_PLANNER, ToolSelection.EVIDENCE_SEARCH, ToolSelection.KNOWLEDGE_PROPOSAL)),
        "coding": (RoutingDecision.RUNTIME, AgentSelection.CODING_ASSISTANT, (ToolSelection.NOOP,)),
        "memory": (RoutingDecision.MEMORY, AgentSelection.LEARNING_MEMORY, (ToolSelection.MEMORY_RETRIEVAL,)),
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
    return None, ()


def _add_dry_run_flags(parser: argparse.ArgumentParser) -> None:
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", help="prepare output without external side effects")
    mode.add_argument("--execute", dest="dry_run", action="store_false", help="request execution after all production gates pass")
    parser.set_defaults(dry_run=True)


class _NoopProjection:
    projection_id = "cli:dry-run"

    def apply(self, event: DurableEvent, *, dry_run: bool) -> None:
        if not dry_run:
            raise RuntimeError("CLI replay diagnostic must remain dry-run")


if __name__ == "__main__":
    raise SystemExit(main())
