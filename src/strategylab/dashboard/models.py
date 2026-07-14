"""Dashboard view models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MetricCard:
    """Single dashboard metric card."""

    label: str
    value: str
    status: str = "neutral"


@dataclass(frozen=True)
class TableView:
    """Simple tabular dashboard view."""

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class DashboardSummary:
    """Dashboard state bundle."""

    title: str
    metrics: tuple[MetricCard, ...]
    tables: tuple[TableView, ...]

