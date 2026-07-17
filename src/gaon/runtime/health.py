"""Runtime health checks."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.storage import RuntimeStateStore


@dataclass(frozen=True)
class HealthCheckResult:
    name: str
    ready: bool
    message: str


def readiness(config: GaonRuntimeConfig, store: RuntimeStateStore | None = None) -> tuple[HealthCheckResult, ...]:
    results = [HealthCheckResult("config", True, "configuration loaded")]
    if store is not None:
        status = store.status()
        results.append(HealthCheckResult("database", status.ready, f"schema_version={status.schema_version}"))
    results.append(HealthCheckResult("telegram", bool(config.telegram_enabled and config.telegram_bot_token) or config.dry_run, "telegram gate checked"))
    return tuple(results)
