from datetime import date
import unittest

from market_fixtures import sample_dataset
from strategylab.backtest import BacktestConfig, SimpleBacktestRunner
from strategylab.broker import BrokerOrder, OrderSide, OrderStatus, PaperBrokerAdapter
from strategylab.market import InMemoryMarketDataAdapter, MarketDataValidator
from strategylab.portfolio import FixedQuantitySizer
from strategylab.risk import max_drawdown, portfolio_exposure, risk_score
from strategylab.strategies import CloseAboveThresholdStrategy


class ResearchPipelineIntegrationTest(unittest.TestCase):
    def test_market_strategy_portfolio_risk_backtest_and_paper_broker(self) -> None:
        adapter = InMemoryMarketDataAdapter(sample_dataset())
        dataset = adapter.load(symbols=("AAA", "BBB"), start=date(2026, 1, 1), end=date(2026, 1, 3))

        validation = MarketDataValidator().validate(dataset, expected_symbols=("AAA", "BBB"))
        self.assertTrue(validation.passed)

        strategy = CloseAboveThresholdStrategy()
        strategy_config = strategy.build_config({"threshold": 100.0, "strength": 1.0})
        signals = strategy.generate_signals(dataset, strategy_config)
        self.assertGreater(len(signals), 0)

        quantity = FixedQuantitySizer(1).size(cash=1000.0, price=dataset.bars[0].close)
        self.assertEqual(quantity, 1)

        result = SimpleBacktestRunner().run(
            dataset,
            signals,
            strategy_config,
            BacktestConfig(initial_capital=1000.0, quantity_per_signal=quantity),
        )
        self.assertTrue(result.result_id)
        self.assertGreater(len(result.trades), 0)

        equity_values = tuple(point.total_equity for point in result.equity_curve)
        drawdown = max_drawdown(equity_values)
        exposure = portfolio_exposure(result.equity_curve[-1].holdings_value, result.equity_curve[-1].total_equity)
        score = risk_score(drawdown, exposure)
        self.assertGreaterEqual(score.score, 0.0)

        paper_fill = PaperBrokerAdapter({"AAA": dataset.bars[0].close}).submit_order(
            BrokerOrder("AAA", OrderSide.BUY, quantity)
        )
        self.assertEqual(paper_fill.status, OrderStatus.FILLED)


if __name__ == "__main__":
    unittest.main()

