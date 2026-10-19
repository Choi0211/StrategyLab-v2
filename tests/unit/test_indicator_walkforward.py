import unittest
from gaon.research.indicator_walkforward import evaluate

def bars(n=80):
    return [dict(symbol="BTCUSDT",timestamp=f"2026-01-{i:04}",open=100+i*.3,
        high=102+i*.3,low=99+i*.3,close=101+i*.3,volume=1000+i*10)
        for i in range(n)]

class IndicatorWalkforwardTests(unittest.TestCase):
    def test_walkforward_is_research_only(self):
        x=evaluate(bars(),market="BINANCE",timeframe="1m")
        self.assertEqual(x.observations,80)
        self.assertFalse(x.order_allowed)
        self.assertFalse(x.promotion_allowed)
        self.assertEqual(x.trades,len(x.trade_returns))

    def test_lookahead_next_open_not_current_close(self):
        a=bars()
        b=bars()
        for i in range(36,80):
            b[i]["open"]=b[i]["close"]-.2
        x=evaluate(a,market="BINANCE",timeframe="1m")
        y=evaluate(b,market="BINANCE",timeframe="1m")
        self.assertEqual(x.trades,y.trades)
        if x.trades: self.assertNotEqual(x.total_return,y.total_return)

    def test_invalid_cost(self):
        for bad in (-1,float("nan"),True):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError): evaluate(bars(),market="BINANCE",timeframe="1m",fee_bps=bad)

    def test_bad_open_and_short_history(self):
        b=bars()
        b[-1]["open"]=-1
        with self.assertRaises(ValueError): evaluate(b,market="BINANCE",timeframe="1m")
        with self.assertRaises(ValueError): evaluate(b[:20],market="BINANCE",timeframe="1m")

if __name__=="__main__": unittest.main()
