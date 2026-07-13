"""Dashboard state assembler."""

from __future__ import annotations

from strategylab.backtest import BacktestResult
from strategylab.dashboard.models import DashboardSummary, MetricCard, TableView


class DashboardShell:
    """Build display-ready dashboard state from domain objects."""

    def from_backtest_result(self, result: BacktestResult) -> DashboardSummary:
        final_equity = result.equity_curve[-1].total_equity if result.equity_curve else result.config.initial_capital
        metrics = (
            MetricCard("Result ID", result.result_id),
            MetricCard("Trades", str(len(result.trades))),
            MetricCard("Final Equity", f"{final_equity:.2f}"),
        )
        rows = tuple(
            (
                trade.timestamp.isoformat(),
                trade.symbol,
                trade.side.value,
                str(trade.quantity),
                f"{trade.price:.2f}",
            )
            for trade in result.trades
        )
        table = TableView(columns=("timestamp", "symbol", "side", "quantity", "price"), rows=rows)
        return DashboardSummary(title="Backtest Summary", metrics=metrics, tables=(table,))

