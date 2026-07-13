import unittest

from strategylab.broker import BrokerOrder, OrderSide, OrderStatus, PaperBrokerAdapter


class BrokerPaperTest(unittest.TestCase):
    def test_paper_broker_fills_known_symbol(self) -> None:
        fill = PaperBrokerAdapter({"AAA": 100.0}).submit_order(BrokerOrder("AAA", OrderSide.BUY, 1))
        self.assertEqual(fill.status, OrderStatus.FILLED)
        self.assertEqual(fill.fill_price, 100.0)

    def test_paper_broker_rejects_missing_mark(self) -> None:
        fill = PaperBrokerAdapter({}).submit_order(BrokerOrder("AAA", OrderSide.BUY, 1))
        self.assertEqual(fill.status, OrderStatus.REJECTED)

    def test_paper_broker_rejects_limit_not_met(self) -> None:
        fill = PaperBrokerAdapter({"AAA": 101.0}).submit_order(BrokerOrder("AAA", OrderSide.BUY, 1, limit_price=100.0))
        self.assertEqual(fill.status, OrderStatus.REJECTED)


if __name__ == "__main__":
    unittest.main()

