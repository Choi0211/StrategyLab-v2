from datetime import datetime
import unittest

from strategylab.portfolio import (
    AllocationTarget,
    CashLedger,
    FixedQuantitySizer,
    PortfolioState,
    Position,
)


class PortfolioEngineTest(unittest.TestCase):
    def test_cash_ledger_debit_credit(self) -> None:
        ledger = CashLedger(1000.0).debit(250.0).credit(50.0)
        self.assertEqual(ledger.cash, 800.0)

    def test_position_buy_sell_and_value(self) -> None:
        position = Position("AAA").buy(2, 100.0).buy(1, 130.0).sell(1)
        self.assertEqual(position.quantity, 2)
        self.assertEqual(position.average_price, 110.0)
        self.assertEqual(position.market_value(120.0), 240.0)

    def test_portfolio_snapshot(self) -> None:
        state = PortfolioState(CashLedger(500.0), {"AAA": Position("AAA", 2, 100.0)})
        snapshot = state.snapshot(datetime(2026, 1, 1), {"AAA": 120.0})
        self.assertEqual(snapshot.holdings_value, 240.0)
        self.assertEqual(snapshot.total_equity, 740.0)

    def test_rebalance_instructions(self) -> None:
        state = PortfolioState(CashLedger(500.0), {"AAA": Position("AAA", 2, 100.0)})
        instructions = state.rebalance_instructions(
            (AllocationTarget("AAA", 0.5), AllocationTarget("BBB", 0.5)),
            {"AAA": 100.0, "BBB": 50.0},
        )
        self.assertEqual(instructions[0].delta_value, 150.0)
        self.assertEqual(instructions[1].target_value, 350.0)

    def test_allocation_weights_must_sum_to_one(self) -> None:
        state = PortfolioState(CashLedger(1000.0))
        with self.assertRaises(ValueError):
            state.rebalance_instructions((AllocationTarget("AAA", 0.5),), {"AAA": 10.0})

    def test_fixed_quantity_sizer(self) -> None:
        sizer = FixedQuantitySizer(3)
        self.assertEqual(sizer.size(100.0, 20.0), 3)
        self.assertEqual(sizer.size(10.0, 20.0), 0)


if __name__ == "__main__":
    unittest.main()

