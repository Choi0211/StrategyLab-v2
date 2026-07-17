"""Explicit plugin lifecycle management."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from gaon.adapters import FakeTradingAdapter
from gaon.runtime.errors import ConfigurationError, redact_mapping


@dataclass(frozen=True)
class PluginCapabilities:
    telegram: bool = False
    notion: bool = False
    trading: bool = False
    network: bool = False
    migrations: bool = False
    approval_bypass: bool = False


@dataclass(frozen=True)
class PluginMetadata:
    plugin_id: str
    name: str
    version: str
    enabled: bool
    capabilities: PluginCapabilities


@dataclass(frozen=True)
class PluginHealth:
    plugin_id: str
    healthy: bool
    status: str
    error: str | None = None


class GaonPlugin(Protocol):
    @property
    def metadata(self) -> PluginMetadata: ...
    def configure(self, config: dict[str, object]) -> None: ...
    def start(self) -> None: ...
    def health(self) -> PluginHealth: ...
    def stop(self) -> None: ...


class PluginRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, GaonPlugin] = {}

    def register(self, plugin: GaonPlugin) -> None:
        metadata = plugin.metadata
        _validate_metadata(metadata)
        if metadata.plugin_id in self._plugins:
            raise ConfigurationError(f"duplicate plugin id: {metadata.plugin_id}")
        self._plugins[metadata.plugin_id] = plugin

    def list_plugins(self) -> tuple[GaonPlugin, ...]:
        return tuple(self._plugins[key] for key in sorted(self._plugins))

    def get(self, plugin_id: str) -> GaonPlugin:
        return self._plugins[plugin_id]


class PluginManager:
    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry
        self._started: list[GaonPlugin] = []
        self._failures: list[dict[str, object]] = []

    @property
    def failures(self) -> tuple[dict[str, object], ...]:
        return tuple(self._failures)

    def configure(self, configs: dict[str, dict[str, object]] | None = None) -> None:
        configs = configs or {}
        for plugin in self._registry.list_plugins():
            plugin.configure(configs.get(plugin.metadata.plugin_id, {}))

    def start(self) -> None:
        for plugin in self._registry.list_plugins():
            metadata = plugin.metadata
            if not metadata.enabled:
                self._failures.append({"plugin_id": metadata.plugin_id, "status": "disabled"})
                continue
            try:
                plugin.start()
                self._started.append(plugin)
            except Exception as exc:  # noqa: BLE001 - failures are isolated and redacted.
                self._failures.append(redact_mapping({"plugin_id": metadata.plugin_id, "status": "start_failed", "error": exc.__class__.__name__}))

    def health(self) -> tuple[PluginHealth, ...]:
        results: list[PluginHealth] = []
        for plugin in self._registry.list_plugins():
            try:
                results.append(plugin.health())
            except Exception as exc:  # noqa: BLE001
                results.append(PluginHealth(plugin.metadata.plugin_id, False, "health_failed", exc.__class__.__name__))
        return tuple(results)

    def stop(self) -> None:
        for plugin in reversed(self._started):
            try:
                plugin.stop()
            except Exception as exc:  # noqa: BLE001
                self._failures.append(redact_mapping({"plugin_id": plugin.metadata.plugin_id, "status": "stop_failed", "error": exc.__class__.__name__}))
        self._started.clear()


class FakeTelegramPlugin:
    def __init__(self, plugin_id: str = "telegram", *, enabled: bool = True, fail_start: bool = False, log: list[str] | None = None) -> None:
        self._metadata = PluginMetadata(plugin_id, "Fake Telegram", "1.0", enabled, PluginCapabilities(telegram=True, network=False))
        self._fail_start = fail_start
        self._log = log if log is not None else []
        self._started = False

    @property
    def metadata(self) -> PluginMetadata:
        return self._metadata

    def configure(self, config: dict[str, object]) -> None:
        self._log.append(f"configure:{self.metadata.plugin_id}")

    def start(self) -> None:
        if self._fail_start:
            raise RuntimeError("synthetic plugin failure with secret-token")
        self._started = True
        self._log.append(f"start:{self.metadata.plugin_id}")

    def health(self) -> PluginHealth:
        return PluginHealth(self.metadata.plugin_id, self._started, "started" if self._started else "stopped")

    def stop(self) -> None:
        self._started = False
        self._log.append(f"stop:{self.metadata.plugin_id}")


class FakeNotionPlugin(FakeTelegramPlugin):
    def __init__(self, plugin_id: str = "notion", *, enabled: bool = True, log: list[str] | None = None) -> None:
        super().__init__(plugin_id, enabled=enabled, log=log)
        self._metadata = PluginMetadata(plugin_id, "Fake Notion", "1.0", enabled, PluginCapabilities(notion=True, network=False))


class FakeTradingPlugin(FakeTelegramPlugin):
    def __init__(self, plugin_id: str = "trading", *, enabled: bool = True, log: list[str] | None = None) -> None:
        super().__init__(plugin_id, enabled=enabled, log=log)
        self._metadata = PluginMetadata(plugin_id, "Fake Trading", "1.0", enabled, PluginCapabilities(trading=True, network=False))
        self.adapter = FakeTradingAdapter()


def _validate_metadata(metadata: PluginMetadata) -> None:
    if not metadata.plugin_id or metadata.plugin_id.strip() != metadata.plugin_id:
        raise ConfigurationError("plugin id must be stable and trimmed")
    if metadata.capabilities.migrations:
        raise ConfigurationError("plugins cannot run database migrations directly")
    if metadata.capabilities.approval_bypass:
        raise ConfigurationError("plugins cannot bypass approval")
