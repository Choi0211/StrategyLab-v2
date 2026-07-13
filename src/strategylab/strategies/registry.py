"""Strategy registry."""

from __future__ import annotations

from strategylab.strategies.interface import Strategy


class StrategyRegistry:
    """Register and retrieve strategy classes by name."""

    def __init__(self) -> None:
        self._strategies: dict[str, type[Strategy]] = {}

    def register(self, strategy_cls: type[Strategy]) -> None:
        strategy = strategy_cls()
        name = strategy.metadata.name
        if name in self._strategies:
            raise ValueError(f"strategy already registered: {name}")
        self._strategies[name] = strategy_cls

    def get(self, name: str) -> type[Strategy]:
        try:
            return self._strategies[name]
        except KeyError as exc:
            raise KeyError(f"unknown strategy: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._strategies)
