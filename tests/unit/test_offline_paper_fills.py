import unittest
from gaon.research.offline_paper_fills import simulate_next_bar
B=dict(symbol="BTCUSDT",open=100,high=110,low=90,close=105)

class OfflinePaperFillsTests(unittest.TestCase):
    def test_long_paper_fill_costs(self):
        x=simulate_next_bar(symbol="BTCUSDT",direction="LONG",next_bar=B,notional_usd=1000)
        self.assertLess(x.net_pnl,x.gross_pnl)
        self.assertGreater(x.fees,0)
        self.assertEqual(x.kind,"offline_simulated_not_exchange_fill")

    def test_short_paper_fill_costs(self):
        x=simulate_next_bar(symbol="BTCUSDT",direction="SHORT",next_bar=B,notional_usd=1000)
        self.assertLess(x.net_pnl,0)
        self.assertLess(x.gross_pnl,0)

    def test_reject_unsafe_simulation(self):
        cases=[
            {"notional_usd":0},{"notional_usd":float("nan")},
            {"direction":"BUY"},{"symbol":"ETHUSDT"},{"fee_bps":-1},
            {"slippage_bps":1001},{"next_bar":dict(B,open=-1)},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                args=dict(symbol="BTCUSDT",direction="LONG",next_bar=B,notional_usd=1000)
                args.update(changes)
                with self.assertRaises(ValueError): simulate_next_bar(**args)

if __name__=="__main__": unittest.main()
