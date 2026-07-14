import unittest

from market_fixtures import sample_dataset
from strategylab.backtest import BacktestConfig, SimpleBacktestRunner
from strategylab.dashboard import DashboardShell
from strategylab.strategies import CloseAboveThresholdStrategy


class DashboardTest(unittest.TestCase):
    def test_dashboard_shell_builds_backtest_summary(self) -> None:
        strategy = CloseAboveThresholdStrategy()
        config = strategy.build_config({"threshold": 100.0})
        dataset = sample_dataset()
        result = SimpleBacktestRunner().run(
            dataset,
            strategy.generate_signals(dataset, config),
            config,
            BacktestConfig(initial_capital=1000.0),
        )

        summary = DashboardShell().from_backtest_result(result)

        self.assertEqual(summary.title, "Backtest Summary")
        self.assertEqual(summary.metrics[1].value, "2")
        self.assertEqual(summary.tables[0].columns[0], "timestamp")


if __name__ == "__main__":
    unittest.main()

