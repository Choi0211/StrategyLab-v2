"""Safe configuration loading for StrategyLab v2."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StrategyLabConfig:
    """Runtime configuration loaded from the public example config."""

    app_name: str
    environment: str
    log_level: str
    log_directory: Path
    enabled_modules: tuple[str, ...] = field(default_factory=tuple)
    plugin_paths: tuple[Path, ...] = field(default_factory=tuple)


def load_config(path: str | Path) -> StrategyLabConfig:
    """Load the subset of YAML used by config.example.yaml without secrets."""

    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    data = _parse_simple_yaml(config_path.read_text(encoding="utf-8"))
    app = data.get("app", {})
    logging = data.get("logging", {})
    modules = data.get("modules", {})
    plugins = data.get("plugins", {})

    return StrategyLabConfig(
        app_name=str(app.get("name", "StrategyLab v2")),
        environment=str(app.get("environment", "development")),
        log_level=str(logging.get("level", "INFO")).upper(),
        log_directory=Path(str(logging.get("directory", "logs"))),
        enabled_modules=tuple(str(item) for item in modules.get("enabled", [])),
        plugin_paths=tuple(Path(str(item)) for item in plugins.get("paths", [])),
    )


def _parse_simple_yaml(content: str) -> dict[str, Any]:
    """Parse the small YAML subset used for public example configuration."""

    root: dict[str, Any] = {}
    current_section: dict[str, Any] | None = None
    current_key: str | None = None

    for raw_line in content.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and stripped.endswith(":"):
            section = stripped[:-1]
            current_section = {}
            root[section] = current_section
            current_key = None
            continue

        if current_section is None:
            raise ValueError(f"Unsupported config line outside section: {line}")

        if stripped.startswith("- "):
            if current_key is None:
                raise ValueError(f"List item without parent key: {line}")
            current_section.setdefault(current_key, []).append(stripped[2:])
            continue

        if ":" not in stripped:
            raise ValueError(f"Unsupported config line: {line}")

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value in {"", "[]"}:
            current_section[key] = []
        else:
            current_section[key] = value
        current_key = key

    return root

