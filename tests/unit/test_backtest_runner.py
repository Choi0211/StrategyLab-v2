import unittest

from market_fixtures import sample_dataset
from strategylab.backtest import BacktestConfig, SimpleBacktestRunner, TradeSide
from strategylab.strategies import CloseAboveThresholdStrategy


class BacktestRunnerTest(unittest.TestCase):
    def test_known_scenario_generates_trades_and_equity_curve(self) -> None:
        dataset = sample_dataset()
        strategy = CloseAboveThresholdStrategy()
        strategy_config = strategy.build_config({"threshold": 100.0})
        signals = strategy.generate_signals(dataset, strategy_config)
        backtest_config = BacktestConfig(initial_capital=1000.0)

        result = SimpleBacktestRunner().run(dataset, signals, strategy_config, backtest_config)

        self.assertEqual(len(result.trades), 2)
        self.assertEqual(result.trades[0].side, TradeSide.BUY)
        self.assertEqual(result.trades[0].symbol, "AAA")
        self.assertEqual(len(result.equity_curve), len(signals))
        self.assertEqual(result.equity_curve[0].cash, 895.0)
        self.assertEqual(result.equity_curve[0].holdings_value, 105.0)
        self.assertEqual(result.equity_curve[0].total_equity, 1000.0)

    def test_transaction_cost_and_slippage_are_applied(self) -> None:
        dataset = sample_dataset()
        strategy = CloseAboveThresholdStrategy()
        strategy_config = strategy.build_config({"threshold": 100.0})
        signals = strategy.generate_signals(dataset, strategy_config)
        backtest_config = BacktestConfig(
            initial_capital=1000.0,
            transaction_cost_rate=0.01,
            slippage_rate=0.01,
        )

        result = SimpleBacktestRunner().run(dataset, signals, strategy_config, backtest_config)
        trade = result.trades[0]

        self.assertEqual(trade.price, 106.05)
        self.assertEqual(trade.fees, 1.0605)
        self.assertEqual(trade.slippage, 1.05)

    def test_runner_does_not_buy_without_cash(self) -> None:
        dataset = sample_dataset()
        strategy = CloseAboveThresholdStrategy()
        strategy_config = strategy.build_config({"threshold": 100.0})
        signals = strategy.generate_signals(dataset, strategy_config)
        backtest_config = BacktestConfig(initial_capital=10.0)

        result = SimpleBacktestRunner().run(dataset, signals, strategy_config, backtest_config)

        self.assertEqual(result.trades, ())
        self.assertEqual(result.equity_curve[0].cash, 10.0)


if __name__ == "__main__":
    unittest.main()

