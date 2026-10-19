import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from gaon.research.daily_equity_research import run
from gaon.research.real_research import MarketBar,MarketDataMetadata,MarketDataset,MarketSymbol

class Fake:
    def fetch_bars(self,symbol,*,start_date,end_date,timeframe):
        start=date.fromisoformat(start_date)
        bars=tuple(MarketBar((start+timedelta(days=i)).isoformat(),symbol,100,103,98,101,1000,100000) for i in range(50))
        meta=MarketDataMetadata("real:mock","NASDAQ",timeframe,start_date,end_date,True,"2026-10-18T00:00:00Z",False)
        return MarketDataset("test",(MarketSymbol(symbol,symbol,"NASDAQ"),),bars,meta)

class DailyEquityResearchTests(unittest.TestCase):
    def test_daily_research_end_to_end_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            db=str(Path(tmp_path)/"research.sqlite")
            args=dict(database=db,symbols=[("US_STOCK","AAPL")],as_of=date(2026,10,18),provider_factory=lambda market:Fake())
            first=run(**args)
            second=run(**args)
            self.assertTrue(first[0]["journal_inserted"])
            self.assertFalse(second[0]["journal_inserted"])
            self.assertEqual(first[0]["run_id"],second[0]["run_id"])

if __name__=="__main__": unittest.main()
