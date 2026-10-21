import sqlite3
import unittest
from gaon.research.offline_research_pipeline import research_and_record
from gaon.learning.experience_journal import summary

class OfflineResearchPipelineTests(unittest.TestCase):
    def test_unclosed_or_future_candles_are_rejected_before_journal_write(self):
        from datetime import datetime, timedelta, timezone
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        bars = [dict(symbol="AAPL", timestamp=(start+timedelta(minutes=i)).isoformat(),
                     open=100, high=102, low=99, close=101, volume=1000) for i in range(80)]
        for observed, timeframe in ((start+timedelta(minutes=79, seconds=30), "1m"),
                                    (start+timedelta(minutes=78), "1m"),
                                    (start+timedelta(days=1), "unknown")):
            with self.subTest(observed=observed, timeframe=timeframe), sqlite3.connect(":memory:") as db:
                with self.assertRaises(ValueError):
                    research_and_record(db, bars, market="US_STOCK", account="test",
                        strategy_version_id="v1", timeframe=timeframe, observed_at=observed.isoformat())
                self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [])

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
