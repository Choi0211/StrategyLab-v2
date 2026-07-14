from datetime import datetime
import unittest

from strategylab.backtest import BacktestConfig, EquityCurvePoint, TradeRecord, TradeSide


class BacktestModelsTest(unittest.TestCase):
    def test_backtest_config_rejects_invalid_values(self) -> None:
        with self.assertRaises(ValueError):
            BacktestConfig(initial_capital=0)
        with self.assertRaises(ValueError):
            BacktestConfig(initial_capital=1000, transaction_cost_rate=-0.1)
        with self.assertRaises(ValueError):
            BacktestConfig(initial_capital=1000, quantity_per_signal=0)

    def test_trade_record_contract(self) -> None:
        trade = TradeRecord(
            timestamp=datetime(2026, 1, 1),
            symbol="AAA",
            side=TradeSide.BUY,
            price=100.0,
            quantity=1,
            fees=0.1,
            slippage=0.2,
            reason="test",
        )

        self.assertEqual(trade.side, TradeSide.BUY)
        self.assertEqual(trade.fees, 0.1)
        self.assertEqual(trade.slippage, 0.2)

    def test_equity_curve_point_contract(self) -> None:
        point = EquityCurvePoint(
            timestamp=datetime(2026, 1, 1),
            cash=900.0,
            holdings_value=105.0,
            total_equity=1005.0,
            drawdown=0.0,
        )

        self.assertEqual(point.total_equity, 1005.0)


if __name__ == "__main__":
    unittest.main()

