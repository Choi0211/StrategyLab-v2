"""In-memory deterministic scheduler."""

from __future__ import annotations

from dataclasses import dataclass, replace
import sqlite3

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


class DurableScheduler:
    def __init__(self, connection: sqlite3.Connection, jobs: tuple[ScheduledJob, ...] = ()) -> None:
        self._connection = connection
        for job in jobs:
            self.add_job(job, next_run_at=job.spec.run_at, execution_status="pending")

    def add_job(self, job: ScheduledJob, *, next_run_at: str, execution_status: str = "pending") -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO scheduler_jobs(job_id, next_run_at, last_run_at, idempotency_key, execution_status) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET next_run_at = excluded.next_run_at, idempotency_key = excluded.idempotency_key, execution_status = excluded.execution_status",
                (job.job_id, next_run_at, job.last_run_at, job.idempotency_key, execution_status),
            )

    def run_due(self, reference_time: str) -> tuple[ScheduledJob, ...]:
        with self._connection:
            rows = self._connection.execute(
                """
                SELECT job_id, next_run_at, last_run_at, idempotency_key
                  FROM scheduler_jobs
                 WHERE execution_status = ? AND next_run_at <= ?
                 ORDER BY next_run_at ASC, job_id ASC
                """,
                ("pending", reference_time),
            ).fetchall()
            jobs: list[ScheduledJob] = []
            for row in rows:
                job = ScheduledJob(str(row[0]), ScheduleSpec("durable", "UTC", "00:00"), str(row[3]), last_run_at=str(row[2]) if row[2] else None)
                updated = self._connection.execute(
                    "UPDATE scheduler_jobs SET execution_status = ?, last_run_at = ?, next_run_at = ? WHERE job_id = ? AND execution_status = ?",
                    ("succeeded", reference_time, reference_time, job.job_id, "pending"),
                )
                if updated.rowcount == 1:
                    jobs.append(job)
        return tuple(jobs)

    def recover(self, *, now: str) -> int:
        with self._connection:
            return int(
                self._connection.execute(
                    "UPDATE scheduler_jobs SET execution_status = ?, next_run_at = ?, last_run_at = NULL WHERE execution_status = ?",
                    ("pending", now, "running"),
                ).rowcount
            )
