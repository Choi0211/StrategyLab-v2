"""Production runtime service skeleton."""

from __future__ import annotations

from dataclasses import dataclass
import signal
import threading
import time
from typing import Callable

from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import redact_mapping
from gaon.runtime.health import HealthCheckResult, readiness
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.plugins import PluginManager
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.worker import DurableTaskQueue


@dataclass(frozen=True)
class RuntimeServiceStatus:
    running: bool
    checks: tuple[HealthCheckResult, ...]
    active_workers: int = 0
    ticks: int = 0


class GaonRuntimeService:
    """Controlled runtime loop boundary; tests inject side-effect-free ticks."""

    def __init__(
        self,
        config: GaonRuntimeConfig,
        store: RuntimeStateStore,
        *,
        tick: Callable[[], None] | None = None,
        poll_interval_seconds: float = 1.0,
        drain_timeout_seconds: float = 5.0,
        metrics: MetricsCollector | None = None,
        plugin_manager: PluginManager | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._tick = tick or (lambda: None)
        self._poll_interval_seconds = poll_interval_seconds
        self._drain_timeout_seconds = drain_timeout_seconds
        self._metrics = metrics or MetricsCollector()
        self._plugin_manager = plugin_manager
        self._stop_event = threading.Event()
        self._running = False
        self._active_workers = 0
        self._ticks = 0
        self._logs: list[dict[str, object]] = []

    def start(self) -> RuntimeServiceStatus:
        checks = readiness(self._config, self._store)
        if not all(check.ready for check in checks):
            raise RuntimeError("runtime service readiness failed")
        DurableTaskQueue(self._store._connection).recover_stale(now="2026-07-17T00:00:00Z")
        if self._plugin_manager is not None:
            self._plugin_manager.configure()
            self._plugin_manager.start()
            for health in self._plugin_manager.health():
                self._metrics.gauge("plugin_health", 1 if health.healthy else 0, plugin=health.plugin_id)
        self._stop_event.clear()
        self._running = True
        self._metrics.increment("runtime_loops", component="service")
        self._log("service_started", {"mode": self._config.mode, "telegram_token": self._config.telegram_bot_token or ""})
        return self.status()

    def run_once(self) -> RuntimeServiceStatus:
        if not self._running:
            self.start()
        self._active_workers += 1
        try:
            self._tick()
            self._ticks += 1
            self._metrics.increment("runtime_loops", component="tick")
        finally:
            self._active_workers -= 1
        return self.status()

    def run_forever(self) -> RuntimeServiceStatus:
        if not self._running:
            self.start()
        self._install_signal_handlers()
        while not self._stop_event.is_set():
            self.run_once()
            self._stop_event.wait(self._poll_interval_seconds)
        return self.stop()

    def stop(self) -> RuntimeServiceStatus:
        self._stop_event.set()
        deadline = time.monotonic() + self._drain_timeout_seconds
        while self._active_workers > 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        if self._plugin_manager is not None:
            self._plugin_manager.stop()
        self._running = False
        self._log("service_stopped", {"active_workers": self._active_workers})
        return self.status()

    def status(self) -> RuntimeServiceStatus:
        return RuntimeServiceStatus(self._running, readiness(self._config, self._store), self._active_workers, self._ticks)

    def request_stop(self) -> None:
        self._stop_event.set()

    @property
    def logs(self) -> tuple[dict[str, object], ...]:
        return tuple(self._logs)

    def _log(self, event: str, payload: dict[str, object]) -> None:
        self._logs.append({"event": event, **redact_mapping(payload)})

    def _install_signal_handlers(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(signum, lambda *_: self.request_stop())
            except (ValueError, AttributeError):
                continue
