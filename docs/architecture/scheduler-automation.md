# Scheduler Automation

Status: Sprint 38

Scheduler Automation connects durable scheduled jobs to the Sprint 36 Executive Planner and Sprint 37 Agent Dispatcher.

The flow is:

`ScheduledJob -> ExecutiveRequest -> ExecutivePlan -> AgentDispatcher -> AgentResult -> Event Store / Metrics`

This sprint implements safe scheduled execution infrastructure only. It does not implement Daily Research business logic, Telegram delivery, GitHub polling automation, Notion synchronization, Trading Adapter execution, KIS integration, broker orders, automatic trading, or automatic approval.

## Durable Contracts

- `ScheduleDefinition`: timezone, next run time, and bounded cadence.
- `ScheduledJob`: stable ID, name, request text, schedule, enabled flag, approval flag, optional agent/tool constraints, metadata, and max attempts.
- `ScheduledExecutionRequest`: job plus execution timestamp and actor.
- `ScheduledRun`: durable run status, attempt, timestamps, result, and error.
- `ScheduledRunStatus`: `pending`, `running`, `succeeded`, `failed`, `blocked`, or `skipped`.

## Persistence

Runtime schema v9 adds:

- `scheduled_automation_jobs`
- `scheduled_automation_runs`
- due-job and run-history indexes

The migration is forward-only and preserves existing runtime data.

## Execution Boundary

`ScheduledAutomationRunner` always invokes the Executive Planner before dispatch. Job agent/tool constraints are validation boundaries, not a shortcut around planning.

If an `ExecutivePlan` requires approval or routes to human review, the scheduled run is marked `blocked`. No approval is created, consumed, or inferred automatically.

## Retry and Idempotency

Each job/run pair uses a stable run ID based on `job_id` and `now`, preventing overlapping duplicate execution for the same timestamp. Retries are bounded by `max_attempts`.

## Events

- `ScheduledJobCreated`
- `ScheduledJobEnabled`
- `ScheduledJobDisabled`
- `ScheduledExecutionStarted`
- `ScheduledExecutionCompleted`
- `ScheduledExecutionFailed`
- `ScheduledExecutionBlocked`

## Metrics

- `gaon_scheduled_jobs_total`
- `gaon_scheduled_executions_total`
- `gaon_scheduled_execution_failures_total`
- `gaon_scheduled_execution_blocked_total`

## CLI Smoke

```powershell
py -3.11 -m gaon.runtime.cli schedule-create --db runtime.sqlite --job-id smoke --name Smoke --request "research evidence" --next-run-at "2026-07-18T00:00:00Z" --agent research
py -3.11 -m gaon.runtime.cli schedule-list --db runtime.sqlite
py -3.11 -m gaon.runtime.cli schedule-show --db runtime.sqlite smoke
py -3.11 -m gaon.runtime.cli schedule-run-due --db runtime.sqlite --now "2026-07-18T00:00:00Z"
```

All commands are deterministic local smoke paths and require no live external service.
