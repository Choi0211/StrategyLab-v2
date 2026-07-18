"""Durable scheduled automation over Executive Planner and Agent Dispatcher."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import re
import sqlite3

from gaon.runtime.agents import AgentDispatcher, AgentRequest, AgentResult, AgentStatus, default_agent_registry
from gaon.runtime.config import GaonRuntimeConfig, validate_timezone
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.executive_planner import AgentSelection, DeterministicExecutivePlanner, ExecutivePlan, ExecutiveRequest, RoutingDecision, ToolSelection
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.serialization import dumps_json, loads_json

ISO_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


class ScheduledRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class ScheduleDefinition:
    timezone: str
    next_run_at: str
    cadence: str = "manual"

    def __post_init__(self) -> None:
        validate_timezone(self.timezone)
        _validate_utc(self.next_run_at)
        if self.cadence not in {"manual", "daily", "weekly"}:
            raise ValueError("unsupported schedule cadence")


@dataclass(frozen=True)
class ScheduledJob:
    job_id: str
    name: str
    request_text: str
    schedule: ScheduleDefinition
    enabled: bool
    created_at: str
    updated_at: str
    approval_required: bool = False
    agent_selection: AgentSelection | None = None
    tool_constraints: tuple[ToolSelection, ...] = ()
    metadata: dict[str, str] | None = None
    max_attempts: int = 2

    def __post_init__(self) -> None:
        if not self.job_id or not self.name.strip() or not self.request_text.strip():
            raise ValueError("scheduled job requires id, name, and request")
        _validate_utc(self.created_at)
        _validate_utc(self.updated_at)
        if self.max_attempts < 1 or self.max_attempts > 5:
            raise ValueError("scheduled job max_attempts must be between 1 and 5")


@dataclass(frozen=True)
class ScheduledExecutionRequest:
    job: ScheduledJob
    now: str
    actor_ref: str = "scheduler"

    def __post_init__(self) -> None:
        _validate_utc(self.now)


@dataclass(frozen=True)
class ScheduledRun:
    run_id: str
    job_id: str
    status: ScheduledRunStatus
    attempt: int
    started_at: str
    completed_at: str | None
    result: dict[str, str]
    error: str | None = None


class ScheduledJobRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def create(self, job: ScheduledJob) -> None:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO scheduled_automation_jobs(
                        job_id, name, request_text, schedule_json, enabled, approval_required,
                        agent_selection, tools_json, metadata_json, next_run_at, max_attempts, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    _job_row(job),
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"duplicate scheduled job id: {job.job_id}") from exc

    def get(self, job_id: str) -> ScheduledJob:
        row = self._connection.execute(
            """
            SELECT job_id, name, request_text, schedule_json, enabled, approval_required,
                   agent_selection, tools_json, metadata_json, next_run_at, max_attempts, created_at, updated_at
              FROM scheduled_automation_jobs WHERE job_id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return _job_from_row(row)

    def list(self) -> tuple[ScheduledJob, ...]:
        rows = self._connection.execute(
            """
            SELECT job_id, name, request_text, schedule_json, enabled, approval_required,
                   agent_selection, tools_json, metadata_json, next_run_at, max_attempts, created_at, updated_at
              FROM scheduled_automation_jobs ORDER BY job_id
            """
        ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def set_enabled(self, job_id: str, enabled: bool, *, updated_at: str) -> ScheduledJob:
        _validate_utc(updated_at)
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE scheduled_automation_jobs SET enabled = ?, updated_at = ? WHERE job_id = ?",
                (1 if enabled else 0, updated_at, job_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(job_id)
        return self.get(job_id)

    def due(self, now: str) -> tuple[ScheduledJob, ...]:
        _validate_utc(now)
        rows = self._connection.execute(
            """
            SELECT job_id, name, request_text, schedule_json, enabled, approval_required,
                   agent_selection, tools_json, metadata_json, next_run_at, max_attempts, created_at, updated_at
              FROM scheduled_automation_jobs
             WHERE enabled = 1 AND next_run_at <= ?
             ORDER BY next_run_at, job_id
            """,
            (now,),
        ).fetchall()
        return tuple(_job_from_row(row) for row in rows)

    def claim_run(self, job: ScheduledJob, *, now: str) -> ScheduledRun | None:
        _validate_utc(now)
        attempt = self._connection.execute("SELECT COUNT(*) FROM scheduled_automation_runs WHERE job_id = ?", (job.job_id,)).fetchone()[0] + 1
        if int(attempt) > job.max_attempts:
            return None
        run = ScheduledRun(_run_id(job.job_id, now), job.job_id, ScheduledRunStatus.RUNNING, int(attempt), now, None, {})
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO scheduled_automation_runs(run_id, job_id, status, attempt, started_at, completed_at, result_json, error)
                    VALUES (?, ?, ?, ?, ?, NULL, ?, NULL)
                    """,
                    (run.run_id, run.job_id, run.status.value, run.attempt, run.started_at, dumps_json(run.result)),
                )
        except sqlite3.IntegrityError:
            return None
        return run

    def complete_run(self, run: ScheduledRun, status: ScheduledRunStatus, *, completed_at: str, result: dict[str, str], error: str | None = None) -> ScheduledRun:
        _validate_utc(completed_at)
        completed = ScheduledRun(run.run_id, run.job_id, status, run.attempt, run.started_at, completed_at, result, error)
        with self._connection:
            self._connection.execute(
                "UPDATE scheduled_automation_runs SET status = ?, completed_at = ?, result_json = ?, error = ? WHERE run_id = ?",
                (completed.status.value, completed.completed_at, dumps_json(completed.result), completed.error, completed.run_id),
            )
            if status in {ScheduledRunStatus.SUCCEEDED, ScheduledRunStatus.BLOCKED} or run.attempt >= self.get(run.job_id).max_attempts:
                self._connection.execute(
                    "UPDATE scheduled_automation_jobs SET enabled = 0, updated_at = ? WHERE job_id = ?",
                    (completed_at, run.job_id),
                )
        return completed

    def list_runs(self, job_id: str | None = None) -> tuple[ScheduledRun, ...]:
        if job_id is None:
            rows = self._connection.execute(
                "SELECT run_id, job_id, status, attempt, started_at, completed_at, result_json, error FROM scheduled_automation_runs ORDER BY started_at, run_id"
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT run_id, job_id, status, attempt, started_at, completed_at, result_json, error FROM scheduled_automation_runs WHERE job_id = ? ORDER BY started_at, run_id",
                (job_id,),
            ).fetchall()
        return tuple(_run_from_row(row) for row in rows)


class ScheduledAutomationRunner:
    def __init__(
        self,
        repository: ScheduledJobRepository,
        config: GaonRuntimeConfig,
        *,
        metrics: MetricsCollector | None = None,
        event_store: SQLiteEventStore | None = None,
    ) -> None:
        self._repository = repository
        self._config = config
        self._metrics = metrics or MetricsCollector()
        self._event_store = event_store

    def run_due(self, *, now: str) -> tuple[ScheduledRun, ...]:
        completed: list[ScheduledRun] = []
        for job in self._repository.due(now):
            run = self._repository.claim_run(job, now=now)
            if run is None:
                continue
            completed.append(self._execute(ScheduledExecutionRequest(job, now), run))
        return tuple(completed)

    def _execute(self, request: ScheduledExecutionRequest, run: ScheduledRun) -> ScheduledRun:
        job = request.job
        self._record(scheduled_event("ScheduledExecutionStarted", job, run, request.now))
        try:
            plan = DeterministicExecutivePlanner(metrics=self._metrics).plan(
                ExecutiveRequest(
                    request_id=run.run_id,
                    text=job.request_text,
                    actor_ref=request.actor_ref,
                    created_at=request.now,
                    scope="scheduled",
                    project="StrategyLab",
                    strategy="N/A",
                    market="N/A",
                    free_only=self._config.free_only_mode,
                )
            )
            if job.approval_required:
                plan = replace(plan, approval_required=True, routing_decision=RoutingDecision.HUMAN_REVIEW, tools=_append_tool(plan.tools, ToolSelection.APPROVAL_WORKFLOW))
            constraint_error = _constraint_error(job, plan)
            if constraint_error is not None:
                completed = self._repository.complete_run(run, ScheduledRunStatus.BLOCKED, completed_at=request.now, result={"reason": constraint_error}, error=None)
                self._metrics.increment("gaon_scheduled_execution_blocked_total", component="scheduler")
                self._record(scheduled_event("ScheduledExecutionBlocked", job, completed, request.now))
                return completed
            result = AgentDispatcher(default_agent_registry(), self._config, metrics=self._metrics, event_store=self._event_store).dispatch(
                plan,
                AgentRequest(run.run_id, job.request_text, request.actor_ref, request.now),
            )
        except Exception as exc:  # noqa: BLE001 - scheduled execution failure is isolated.
            completed = self._repository.complete_run(run, ScheduledRunStatus.FAILED, completed_at=request.now, result={}, error=exc.__class__.__name__)
            self._metrics.increment("gaon_scheduled_execution_failures_total", component="scheduler")
            self._record(scheduled_event("ScheduledExecutionFailed", job, completed, request.now))
            return completed
        status = _scheduled_status(result)
        completed = self._repository.complete_run(
            run,
            status,
            completed_at=request.now,
            result={"agent_name": result.agent_name, "agent_status": result.status.value, "output": result.output},
            error=result.error,
        )
        if status == ScheduledRunStatus.SUCCEEDED:
            self._metrics.increment("gaon_scheduled_executions_total", component="scheduler")
            self._record(scheduled_event("ScheduledExecutionCompleted", job, completed, request.now))
        elif status == ScheduledRunStatus.BLOCKED:
            self._metrics.increment("gaon_scheduled_execution_blocked_total", component="scheduler")
            self._record(scheduled_event("ScheduledExecutionBlocked", job, completed, request.now))
        else:
            self._metrics.increment("gaon_scheduled_execution_failures_total", component="scheduler")
            self._record(scheduled_event("ScheduledExecutionFailed", job, completed, request.now))
        return completed

    def _record(self, event: DurableEvent) -> None:
        if self._event_store is not None:
            self._event_store.append(event)


def scheduled_event(event_type: str, job: ScheduledJob, run: ScheduledRun | None, occurred_at: str) -> DurableEvent:
    event_ref = run.run_id if run else occurred_at
    return DurableEvent(
        event_id=f"event:scheduled:{event_type}:{job.job_id}:{event_ref}",
        event_type=event_type,
        occurred_at=occurred_at,
        actor_ref="scheduler",
        correlation_id=run.run_id if run else job.job_id,
        causation_id=job.job_id,
        scope="scheduled",
        project="StrategyLab",
        strategy="N/A",
        market="N/A",
        payload={
            "job_id": job.job_id,
            "run_id": run.run_id if run else "",
            "status": run.status.value if run else "",
            "enabled": str(job.enabled),
        },
        evidence_refs=(),
        audit_refs=(),
        appended_at=occurred_at,
    )


def record_scheduled_job_metric(metrics: MetricsCollector, repository: ScheduledJobRepository) -> None:
    metrics.gauge("gaon_scheduled_jobs_total", float(len(repository.list())), component="scheduler")


def _job_row(job: ScheduledJob) -> tuple[object, ...]:
    return (
        job.job_id,
        job.name,
        job.request_text,
        dumps_json({"timezone": job.schedule.timezone, "next_run_at": job.schedule.next_run_at, "cadence": job.schedule.cadence}),
        1 if job.enabled else 0,
        1 if job.approval_required else 0,
        job.agent_selection.value if job.agent_selection else None,
        dumps_json({"tools": [tool.value for tool in job.tool_constraints]}),
        dumps_json(job.metadata or {}),
        job.schedule.next_run_at,
        job.max_attempts,
        job.created_at,
        job.updated_at,
    )


def _job_from_row(row: tuple[object, ...]) -> ScheduledJob:
    schedule = loads_json(str(row[3]))
    tools = loads_json(str(row[7]))
    return ScheduledJob(
        job_id=str(row[0]),
        name=str(row[1]),
        request_text=str(row[2]),
        schedule=ScheduleDefinition(str(schedule["timezone"]), str(schedule["next_run_at"]), str(schedule["cadence"])),
        enabled=bool(row[4]),
        approval_required=bool(row[5]),
        agent_selection=AgentSelection(str(row[6])) if row[6] is not None else None,
        tool_constraints=tuple(ToolSelection(str(tool)) for tool in tools.get("tools", ())),
        metadata={str(k): str(v) for k, v in loads_json(str(row[8])).items()},
        max_attempts=int(row[10]),
        created_at=str(row[11]),
        updated_at=str(row[12]),
    )


def _run_from_row(row: tuple[object, ...]) -> ScheduledRun:
    return ScheduledRun(
        run_id=str(row[0]),
        job_id=str(row[1]),
        status=ScheduledRunStatus(str(row[2])),
        attempt=int(row[3]),
        started_at=str(row[4]),
        completed_at=str(row[5]) if row[5] is not None else None,
        result={str(k): str(v) for k, v in loads_json(str(row[6])).items()},
        error=str(row[7]) if row[7] is not None else None,
    )


def _constraint_error(job: ScheduledJob, plan: ExecutivePlan) -> str | None:
    if job.agent_selection is not None and job.agent_selection not in plan.agents:
        return "planned agent does not match scheduled job constraint"
    missing_tools = tuple(tool for tool in job.tool_constraints if tool not in plan.tools)
    if missing_tools:
        return "planned tools do not satisfy scheduled job constraints"
    if plan.approval_required or plan.routing_decision == RoutingDecision.HUMAN_REVIEW:
        return "scheduled execution requires approval"
    return None


def _scheduled_status(result: AgentResult) -> ScheduledRunStatus:
    if result.status == AgentStatus.SUCCEEDED:
        return ScheduledRunStatus.SUCCEEDED
    if result.status in {AgentStatus.BLOCKED, AgentStatus.REQUIRES_APPROVAL}:
        return ScheduledRunStatus.BLOCKED
    return ScheduledRunStatus.FAILED


def _run_id(job_id: str, now: str) -> str:
    return f"scheduled-run:{job_id}:{now}"


def _validate_utc(value: str) -> None:
    if ISO_UTC.fullmatch(value) is None:
        raise ValueError("timestamp must use ISO 8601 UTC format")


def _append_tool(tools: tuple[ToolSelection, ...], tool: ToolSelection) -> tuple[ToolSelection, ...]:
    return tools if tool in tools else (*tools, tool)
