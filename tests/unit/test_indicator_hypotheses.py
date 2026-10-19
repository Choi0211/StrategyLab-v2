import unittest
from dataclasses import replace
from gaon.research.market_feature_engine import FeatureReport
from gaon.research.indicator_hypotheses import propose

def report(*,macd=1,rsi=55,rv=1.5,adx=25,bars=50):
    return FeatureReport("BTCUSDT","BINANCE","1m",bars,
      {"sma20":10,"rsi14":rsi,"macd":{"histogram":macd},
       "volume":{"relative_volume":rv},"adx14":adx},())

class IndicatorHypothesesTests(unittest.TestCase):
    def test_research_hypothesis_never_executable(self):
        x=propose(report())
        self.assertEqual(x.direction,"LONG")
        self.assertEqual(x.status,"needs_backtest")
        self.assertFalse(x.order_allowed)
        x=propose(report(macd=-1,rsi=45))
        self.assertEqual(x.direction,"SHORT")
        self.assertFalse(x.order_allowed)

    def test_weak_or_conflicting_evidence_is_not_signal(self):
        cases=[{"rv":0.5},{"adx":15},{"rsi":85},{"macd":-1},{"bars":10}]
        for changes in cases:
            with self.subTest(changes=changes):
                x=propose(report(**changes))
                self.assertEqual(x.direction,"NONE")
                self.assertFalse(x.order_allowed)

    def test_reject_executable_report(self):
        with self.assertRaises(ValueError): propose(replace(report(),executable=True))

if __name__=="__main__": unittest.main()
