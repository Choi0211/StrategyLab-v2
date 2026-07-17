"""In-memory deterministic scheduler."""

from __future__ import annotations

from dataclasses import dataclass, replace

from gaon.runtime.config import validate_hhmm, validate_timezone, validate_weekday


@dataclass(frozen=True)
class ScheduleSpec:
    job_type: str
    timezone: str
    run_at: str
    weekday: str | None = None

    def __post_init__(self) -> None:
        validate_timezone(self.timezone)
        validate_hhmm(self.run_at, "run_at")
        if self.weekday is not None:
            validate_weekday(self.weekday)


@dataclass(frozen=True)
class ScheduledJob:
    job_id: str
    spec: ScheduleSpec
    idempotency_key: str
    last_run_at: str | None = None


class InMemoryScheduler:
    def __init__(self, jobs: tuple[ScheduledJob, ...] = ()) -> None:
        self._jobs = jobs

    def due_jobs(self, reference_time: str) -> tuple[ScheduledJob, ...]:
        day = reference_time[:10]
        time = reference_time[11:16]
        return tuple(job for job in self._jobs if job.spec.run_at <= time and job.last_run_at != day)

    def run_due(self, reference_time: str) -> tuple[ScheduledJob, ...]:
        due = self.due_jobs(reference_time)
        day = reference_time[:10]
        self._jobs = tuple(replace(job, last_run_at=day) if job in due else job for job in self._jobs)
        return due
