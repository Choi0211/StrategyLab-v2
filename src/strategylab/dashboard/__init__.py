"""Dashboard module boundary."""

from strategylab.dashboard.models import DashboardSummary, MetricCard, TableView
from strategylab.dashboard.shell import DashboardShell

__all__ = ["DashboardShell", "DashboardSummary", "MetricCard", "TableView"]

