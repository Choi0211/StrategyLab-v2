import sqlite3
import tempfile
import unittest
from pathlib import Path
from gaon.learning.experience_journal import record, summary

def entry(**kw):
    data=dict(market="KR_STOCK",account="paper-a",strategy_version_id="v1",
        run_id="r1",observed_at="2026-10-18T00:00:00Z",outcome="LOSS",
        net_pnl=-2.5,evidence={"source":"paper","fees":0.2})
    data.update(kw)
    return data

class ExperienceJournalTests(unittest.TestCase):
    def test_durable_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            db=str(Path(tmp_path)/"experiences.sqlite")
            with sqlite3.connect(db) as conn:
                self.assertTrue(record(conn,**entry()))
                self.assertFalse(record(conn,**entry()))
                self.assertEqual(summary(conn,market="KR_STOCK",account="paper-a",strategy_version_id="v1")["net_pnl"],-2.5)
            with sqlite3.connect(db) as conn:
                self.assertEqual(summary(conn,market="KR_STOCK",account="paper-a",strategy_version_id="v1")["trades"],1)

    def test_reject_conflicting_replay(self):
        with sqlite3.connect(":memory:") as conn:
            record(conn,**entry())
            with self.assertRaises(ValueError): record(conn,**entry(net_pnl=999))
            self.assertIs(summary(conn,market="KR_STOCK",account="paper-a",strategy_version_id="v1")["promotion_allowed"], False)

    def test_invalid(self):
        cases=[
            {"market":"UNKNOWN"},{"outcome":"MAYBE"},{"net_pnl":float("nan")},
            {"observed_at":"2026-10-18"},{"evidence":{}},
        ]
        for kw in cases:
            with self.subTest(kw=kw):
                with sqlite3.connect(":memory:") as conn:
                    with self.assertRaises(ValueError): record(conn,**entry(**kw))

    def test_scope_isolation(self):
        with sqlite3.connect(":memory:") as conn:
            record(conn,**entry())
            self.assertEqual(summary(conn,market="US_STOCK",account="paper-a",strategy_version_id="v1")["trades"],0)

if __name__=="__main__": unittest.main()
