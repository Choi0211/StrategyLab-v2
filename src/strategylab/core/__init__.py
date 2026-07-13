"""Core services for StrategyLab v2."""

from strategylab.core.config import StrategyLabConfig, load_config
from strategylab.core.logging import configure_logger
from strategylab.core.modules import ModuleDefinition, ModuleRegistry, default_module_registry
from strategylab.core.plugins import PluginLoader, PluginSpec

__all__ = [
    "ModuleDefinition",
    "ModuleRegistry",
    "PluginLoader",
    "PluginSpec",
    "StrategyLabConfig",
    "configure_logger",
    "default_module_registry",
    "load_config",
]

