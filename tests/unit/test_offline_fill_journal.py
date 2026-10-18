import sqlite3
import tempfile
import unittest
from pathlib import Path
from gaon.research.offline_fill_journal import simulate_and_record
from gaon.learning.experience_journal import summary

def arguments():
    return dict(account="offline",strategy_version_id="v1",symbol="BTCUSDT",
                direction="LONG",notional_usd=100,observed_at="2026-10-18T00:00:00Z",
                next_bar={"symbol":"BTCUSDT","timestamp":"2026-10-17T00:00:00Z",
                          "open":100,"high":105,"low":98,"close":103})

class OfflineFillJournalTests(unittest.TestCase):
    def test_durable_offline_fill_and_replay(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            db=Path(tmp_path)/"offline.sqlite"
            with sqlite3.connect(db) as connection:
                a=simulate_and_record(connection,**arguments())
                b=simulate_and_record(connection,**arguments())
                self.assertTrue(a["inserted"])
                self.assertFalse(b["inserted"])
                self.assertEqual(a["run_id"],b["run_id"])
                self.assertEqual(a["kind"],"offline_simulated_not_exchange_fill")
                self.assertFalse(a["promotion_allowed"])
            with sqlite3.connect(db) as connection:
                s=summary(connection,market="BINANCE",account="offline",strategy_version_id="v1")
                self.assertEqual(s["trades"],1)
                self.assertEqual(s["net_pnl"],a["net_pnl"])

    def test_rejects_bad_candle_without_write(self):
        with sqlite3.connect(":memory:") as connection:
            args=arguments()
            args["next_bar"]={**args["next_bar"],"symbol":"ETHUSDT"}
            with self.assertRaises(ValueError):
                simulate_and_record(connection,**args)
            self.assertIsNone(connection.execute(
                "SELECT name FROM sqlite_master WHERE name='gaon_research_experiences'").fetchone())

if __name__=="__main__": unittest.main()
