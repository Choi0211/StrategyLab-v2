import unittest
from datetime import datetime,timezone
from gaon.research.real_research import MarketBar,MarketDataMetadata,MarketDataset,MarketSymbol
from gaon.research.real_equity_research_bridge import fetch_real_daily_bars

class Provider:
    def __init__(self,fixture=False):self.fixture=fixture
    def fetch_bars(self,symbol,*,start_date,end_date,timeframe):
        from datetime import date,timedelta
        start=date.fromisoformat(start_date)
        bars=tuple(MarketBar((start+timedelta(days=i)).isoformat(),symbol,100,105,95,101,1000,100000) for i in range(45))
        meta=MarketDataMetadata("fixture:fake" if self.fixture else "real:test", "NASDAQ",timeframe,start_date,end_date,True,datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),self.fixture)
        return MarketDataset("test", (MarketSymbol(symbol,symbol,"NASDAQ"),),bars,meta)

class RealEquityResearchBridgeTests(unittest.TestCase):
    def test_real_provider_bridge(self):
        bars=fetch_real_daily_bars(market="US_STOCK",symbol="AAPL",start_date="2025-01-01",end_date="2025-04-01",provider=Provider())
        self.assertEqual(len(bars),45)
        self.assertEqual(bars[0]["timestamp"],"2025-01-01T00:00:00Z")

    def test_fixture_rejected(self):
        with self.assertRaisesRegex(ValueError,"provenance"):
            fetch_real_daily_bars(market="US_STOCK",symbol="AAPL",start_date="2025-01-01",end_date="2025-04-01",provider=Provider(True))

    def test_future_date_rejected(self):
        with self.assertRaises(ValueError):
            fetch_real_daily_bars(market="US_STOCK",symbol="AAPL",start_date="2025-01-01",end_date="2099-01-01",provider=Provider())

if __name__=="__main__": unittest.main()
