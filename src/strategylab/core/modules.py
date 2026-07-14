"""Module registry for StrategyLab v2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleDefinition:
    """A planned StrategyLab v2 module boundary."""

    name: str
    package: str
    description: str


class ModuleRegistry:
    """Registry of module boundaries available to Sprint 1."""

    def __init__(self, modules: list[ModuleDefinition] | None = None) -> None:
        self._modules: dict[str, ModuleDefinition] = {}
        for module in modules or []:
            self.register(module)

    def register(self, module: ModuleDefinition) -> None:
        if module.name in self._modules:
            raise ValueError(f"Module already registered: {module.name}")
        self._modules[module.name] = module

    def names(self) -> tuple[str, ...]:
        return tuple(self._modules)

    def get(self, name: str) -> ModuleDefinition:
        try:
            return self._modules[name]
        except KeyError as exc:
            raise KeyError(f"Unknown module: {name}") from exc


def default_module_registry() -> ModuleRegistry:
    """Return the v2 module boundaries defined by the Master Blueprint."""

    return ModuleRegistry(
        [
            ModuleDefinition("core", "strategylab.core", "configuration, logging, lifecycle"),
            ModuleDefinition("market", "strategylab.market", "market data interfaces"),
            ModuleDefinition("strategies", "strategylab.strategies", "strategy plugins"),
            ModuleDefinition("portfolio", "strategylab.portfolio", "portfolio state"),
            ModuleDefinition("risk", "strategylab.risk", "risk controls and metrics"),
            ModuleDefinition("backtest", "strategylab.backtest", "backtest workflows"),
            ModuleDefinition("research", "strategylab.research", "AI-assisted research review"),
            ModuleDefinition("broker", "strategylab.broker", "broker abstractions"),
            ModuleDefinition("dashboard", "strategylab.dashboard", "research dashboard"),
            ModuleDefinition("reports", "strategylab.reports", "report generation"),
            ModuleDefinition("notification", "strategylab.notification", "notification interfaces"),
        ]
    )

