import sqlite3
import unittest
from gaon.research.offline_research_pipeline import research_and_record
from gaon.learning.experience_journal import summary

class OfflineResearchPipelineTests(unittest.TestCase):
    def test_offline_pipeline_journals_without_fake_trades(self):
        bars=[dict(symbol="BTCUSDT",timestamp=f"2026-01-01T{i//60:02}:{i%60:02}:00Z",open=100+i*.3,
          high=102+i*.3,low=99+i*.3,close=101+i*.3,volume=1000+i*10)
          for i in range(80)]
        with sqlite3.connect(":memory:") as db:
            args=dict(market="BINANCE",account="paper",strategy_version_id="research-v1",
              timeframe="1m",observed_at="2026-10-18T07:00:00Z")
            a=research_and_record(db,bars,**args)
            b=research_and_record(db,bars,**args)
            self.assertTrue(a.journal_inserted)
            self.assertFalse(b.journal_inserted)
            self.assertFalse(a.eligible_for_promotion)
            x=summary(db,market="BINANCE",account="paper",strategy_version_id="research-v1")
            self.assertEqual(x["experiments"],1)
            self.assertEqual(x["trades"],0)
            self.assertEqual(x["net_pnl"],0)

if __name__=="__main__": unittest.main()
