import math
import unittest
from gaon.research import technical_indicators as t

class TechnicalIndicatorsTests(unittest.TestCase):
    def test_warmup(self):
        self.assertIsNone(t.sma([1,2],3))
        self.assertIsNone(t.ema([1,2],3))
        self.assertIsNone(t.rsi([1,2],2))
        self.assertIsNone(t.atr([2],[1],[1.5]))
        self.assertIsNone(t.macd(list(range(30))))
        self.assertIsNone(t.adx([2]*10,[1]*10,[1.5]*10))

    def test_constant_prices(self):
        x=[10.0]*50
        self.assertEqual(t.sma(x),10)
        self.assertEqual(t.ema(x),10)
        self.assertEqual(t.rsi(x),50)
        self.assertEqual(t.roc(x),0)
        self.assertEqual(t.stochastic(x,x,x),50)
        self.assertEqual(t.macd(x)["histogram"],0)
        self.assertEqual(t.adx(x,x,x),0)

    def test_known_values(self):
        self.assertEqual(t.sma([1,2,3,4],2),3.5)
        self.assertEqual(t.ema([1,2,3,4],2),3.5)
        self.assertEqual(t.rsi(list(range(20))),100)
        self.assertEqual(t.obv([1,2,1,1],[2,3,5,7]),-2)
        self.assertEqual(t.vwap([2,4],[0,2],[1,3],[1,1]),2)
        self.assertEqual(t.atr([3,4,5],[1,2,3],[2,3,4],2),2)
        self.assertEqual(t.bollinger([1,1,1],2),{"lower":1,"middle":1,"upper":1})
        self.assertEqual(t.roc([2,3,4],2),100)

    def test_bad_inputs(self):
        with self.assertRaises(ValueError): t.sma([float("nan")])
        with self.assertRaises(ValueError): t.atr([1,2],[0],[1])
        with self.assertRaises(ValueError): t.obv([1,2],[1,-1])
        with self.assertRaises(ValueError): t.macd([1,2,3],fast=3,slow=2)
        with self.assertRaises(ValueError): t.vwap([1],[1],[1],[1],period=0)

    def test_prefix_invariance_no_lookahead(self):
        x=list(range(1,50))
        self.assertEqual(t.ema(x[:35]),t.ema(x[:36][:-1]))
        self.assertTrue(math.isfinite(t.adx([v+1 for v in x],[v-1 for v in x],x)))

    def test_relative_volume_uses_previous_candles(self):
        x=[10.,11.,12.,13.]
        out=t.volume_analysis([v+1 for v in x],[v-1 for v in x],x,[10,10,10,30],period=3)
        self.assertEqual(out['relative_volume'],3)
        self.assertEqual(out['signed_volume_proxy'],30)
        self.assertEqual(out['notional_proxy'],390)
        self.assertEqual(out['interpretation'],'proxy_not_trade_side_or_order_book')

    def test_volume_profile_and_missing_volume(self):
        self.assertEqual(t.volume_profile([10,10,11],[3,5,1],bins=2)['method'],'close_proxy')
        self.assertIsNone(t.volume_analysis([2]*4,[1]*4,[1.5]*4,[0]*4,period=3)['relative_volume'])
        self.assertIsNone(t.volume_profile([1,2],[0,0]))

    def test_volume_rejects_bad_data(self):
        with self.assertRaises(ValueError): t.volume_analysis([1,2],[1],[1],[1])
        with self.assertRaises(ValueError): t.volume_profile([1,2],[1,-1])

if __name__=="__main__": unittest.main()
