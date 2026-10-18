import unittest
from gaon.research.market_feature_engine import extract_features

def bars(n=40):
    return [dict(symbol="TEST",timestamp=f"2026-01-{i:03}",high=i+2,low=i,close=i+1,volume=i*100) for i in range(n)]

class MarketFeatureEngineTests(unittest.TestCase):
    def test_feature_report(self):
        for market in ("KR_STOCK","US_STOCK","BINANCE"):
            with self.subTest(market=market):
                r=extract_features(bars(),market=market,timeframe="1d")
                self.assertFalse(r.executable)
                self.assertGreater(r.features["volume"]["relative_volume"],1)
                self.assertIsNotNone(r.features["macd"])
                self.assertEqual(r.features["volume_profile"]["method"],"close_proxy")

    def test_warmup(self):
        r=extract_features(bars(3),market="KR_STOCK",timeframe="1d")
        self.assertIn("rsi14",r.missing)
        self.assertIn("macd",r.missing)

    def test_reject_bad_data(self):
        with self.assertRaises(ValueError): extract_features(bars(),market="UNKNOWN",timeframe="1d")
        b=bars(); b[0]["volume"]=-1
        with self.assertRaises(ValueError): extract_features(b,market="US_STOCK",timeframe="1d")
        b=bars(); b[1]["timestamp"]=b[0]["timestamp"]
        with self.assertRaises(ValueError): extract_features(b,market="BINANCE",timeframe="1m")

if __name__=="__main__": unittest.main()
