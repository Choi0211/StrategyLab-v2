import unittest

from market_fixtures import sample_dataset
from strategylab.backtest import BacktestConfig, SimpleBacktestRunner
from strategylab.strategies import CloseAboveThresholdStrategy


class BacktestDeterminismTest(unittest.TestCase):
    def test_same_inputs_produce_same_result(self) -> None:
        dataset = sample_dataset()
        strategy = CloseAboveThresholdStrategy()
        strategy_config = strategy.build_config({"threshold": 100.0, "strength": 0.8})
        signals = strategy.generate_signals(dataset, strategy_config)
        backtest_config = BacktestConfig(initial_capital=1000.0, transaction_cost_rate=0.001)
        runner = SimpleBacktestRunner()

        first = runner.run(dataset, signals, strategy_config, backtest_config)
        second = runner.run(dataset, signals, strategy_config, backtest_config)

        self.assertEqual(first.result_id, second.result_id)
        self.assertEqual(first.trades, second.trades)
        self.assertEqual(first.equity_curve, second.equity_curve)

    def test_different_config_changes_result_id(self) -> None:
        dataset = sample_dataset()
        strategy = CloseAboveThresholdStrategy()
        strategy_config = strategy.build_config({"threshold": 100.0})
        signals = strategy.generate_signals(dataset, strategy_config)
        runner = SimpleBacktestRunner()

        first = runner.run(dataset, signals, strategy_config, BacktestConfig(initial_capital=1000.0))
        second = runner.run(dataset, signals, strategy_config, BacktestConfig(initial_capital=2000.0))

        self.assertNotEqual(first.result_id, second.result_id)


if __name__ == "__main__":
    unittest.main()

