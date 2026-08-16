# Patch 8.0 Final Production Runtime Wiring

Status: COMPLETE

## Context

The production runtime service previously constructed its bounded tick from
`TelegramPollingWorker.tick` only. Daily briefing composition, durable scheduled
jobs, and Telegram delivery already existed and had release checks, but the
always-on `GaonRuntimeService` loop did not invoke the daily briefing scheduler.

## Goal

Wire the existing daily briefing durable scheduler into the production runtime
tick beside Telegram polling, without adding a new scheduler, Telegram
transport, database structure, trading path, approval bypass, or strategy
mutation path.

## Runtime Wiring

`_runtime_tick()` now returns one composite tick that invokes:

1. `TelegramPollingWorker.tick`
2. `DailyBriefingRuntimeWorker.tick`

The daily briefing worker reuses:

- `ScheduledJobRepository`
- `schedule_daily_briefing_jobs`
- `DailyBriefingScheduler`
- `send_daily_briefing`
- the existing Telegram client/send path

## Scheduler Registration

The runtime worker idempotently registers the deterministic daily briefing jobs
when at least one allowed Telegram chat is configured. Repeated service ticks or
process restarts do not create duplicate root jobs. Actual delivery only occurs
for due scheduled jobs.

## Safety

- No live trading
- No KIS/Broker order
- No Champion auto-promotion
- No approval bypass
- No strategy config mutation
- No arbitrary shell or SQL expansion

If no allowed Telegram chat is configured, briefing delivery is skipped safely.
If live trading evidence is unavailable, post-market briefing composition uses
an unavailable/insufficient state rather than failing the runtime.

## Release Check

`gaon-production-daily-briefing-runtime-wiring-release-check` proves:

- Telegram worker invoked
- daily briefing worker invoked
- jobs registered
- registration idempotent
- durable restart behavior
- no strategy mutation
- no order execution
- no Champion promotion
- no approval bypass
