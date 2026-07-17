"""Production runtime service skeleton."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.health import HealthCheckResult, readiness
from gaon.runtime.storage import RuntimeStateStore


@dataclass(frozen=True)
class RuntimeServiceStatus:
    running: bool
    checks: tuple[HealthCheckResult, ...]


class GaonRuntimeService:
    """Small service boundary; it does not start external network loops in tests."""

    def __init__(self, config: GaonRuntimeConfig, store: RuntimeStateStore) -> None:
        self._config = config
        self._store = store
        self._running = False

    def start(self) -> RuntimeServiceStatus:
        checks = readiness(self._config, self._store)
        if not all(check.ready for check in checks):
            raise RuntimeError("runtime service readiness failed")
        self._running = True
        return RuntimeServiceStatus(True, checks)

    def stop(self) -> RuntimeServiceStatus:
        self._running = False
        return RuntimeServiceStatus(False, readiness(self._config, self._store))

    def status(self) -> RuntimeServiceStatus:
        return RuntimeServiceStatus(self._running, readiness(self._config, self._store))
