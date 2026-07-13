"""Plugin loading boundary for StrategyLab v2."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PluginSpec:
    """Metadata for a discovered plugin path."""

    name: str
    path: Path


class PluginLoader:
    """Discover plugin directories without importing plugin code."""

    def __init__(self, paths: tuple[Path, ...] = ()) -> None:
        self.paths = paths

    def discover(self) -> tuple[PluginSpec, ...]:
        plugins: list[PluginSpec] = []
        for root in self.paths:
            if not root.exists():
                continue
            for child in sorted(root.iterdir()):
                if child.is_dir() and (child / "plugin.toml").exists():
                    plugins.append(PluginSpec(name=child.name, path=child))
        return tuple(plugins)

