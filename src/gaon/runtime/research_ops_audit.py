"""Read-only, no-cost research scheduler and storage audit.

Never mutates a trading database, strategy, approval, or backup.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import sqlite3


def audit(connection: sqlite3.Connection, *, now: str, disk_used_percent: float,
          warning_disk_percent: float = 80.0) -> dict[str, object]:
    current = datetime.fromisoformat(now.replace("Z", "+00:00")).astimezone(UTC)
    jobs = connection.execute(
        """SELECT job_id, next_run_at FROM scheduled_automation_jobs
        WHERE enabled=1 AND name='Gaon Autonomous Research Tick'
        ORDER BY next_run_at DESC"""
    ).fetchall()
    last = connection.execute(
        """SELECT r.status,r.started_at FROM scheduled_automation_runs r
        JOIN scheduled_automation_jobs j ON j.job_id=r.job_id
        WHERE j.name='Gaon Autonomous Research Tick'
        ORDER BY r.started_at DESC LIMIT 1"""
    ).fetchone()
    warnings: list[str] = []
    if not jobs:
        warnings.append("research_scheduler_missing")
    elif len(jobs) != 1:
        warnings.append("research_scheduler_duplicate")
    else:
        due = datetime.fromisoformat(jobs[0][1].replace("Z", "+00:00")).astimezone(UTC)
        if current - due > timedelta(hours=2):
            warnings.append("research_scheduler_overdue")
    if last:
        started = datetime.fromisoformat(last[1].replace("Z", "+00:00")).astimezone(UTC)
        if last[0] == "running" and current - started > timedelta(hours=2):
            warnings.append("research_run_stale")
        if current - started > timedelta(hours=26):
            warnings.append("research_no_recent_runs")
    else:
        warnings.append("research_no_recent_runs")
    if disk_used_percent >= warning_disk_percent:
        warnings.append("disk_usage_high")
    return {
        "schema_version": 1, "status": "warning" if warnings else "ok",
        "warnings": warnings, "enabled_research_jobs": len(jobs),
        "last_run_status": last[0] if last else None,
        "disk_used_percent": disk_used_percent,
        "paid_api_required": False,
        "read_only": True,
    }


def audit_database(path: str | Path, *, now: str, disk_used_percent: float) -> dict[str, object]:
    # Explicit SQLite read-only mode: never create or alter the runtime DB.
    with sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True) as connection:
        return audit(connection, now=now, disk_used_percent=disk_used_percent)
