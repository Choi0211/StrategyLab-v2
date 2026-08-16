from __future__ import annotations
import json, os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gaon.research.live_trading_intelligence import (
    LiveTradingEvidenceAdapter, adaptive_budget, adaptive_batches, build_feedback, release_check
)
from gaon.research.real_research import MarketSymbol

class AutonomousResearchIntelligenceV7Tests(unittest.TestCase):
    def _root(self,tmp):
        root=Path(tmp)
        for name in ("trade_state.json","trade_state_daytrade.json","us_trade_state_daytrade.json"):
            (root/name).write_text(json.dumps({"positions":{}}),encoding="utf-8")
        (root/"us_trade_state.json").write_text(json.dumps({"date":"2026-08-15","positions":{"HPE":{"entry_price":59.94,"qty":1}}}),encoding="utf-8")
        return root

    def test_hban_round_trip_bxp_partial_and_dry_run(self):
        with TemporaryDirectory() as tmp:
            root=self._root(tmp)
            (root/"order_ledger.json").write_text(json.dumps({"orders":[
                {"datetime":"2026-06-16 06:20:12","market":"US","strategy":"turtle","side":"BUY","symbol":"HBAN","qty":1,"price":17.5278,"status":"FILLED_CONFIRMED","detail":"","reconciled_at":None},
                {"datetime":"2026-07-25 06:20:08","market":"US","strategy":"turtle","side":"SELL","symbol":"HBAN","qty":1,"price":17.44,"status":"ORDER_SENT_NOT_CONFIRMED","detail":"","reconciled_at":None},
                {"datetime":"2026-07-29 06:20:07","market":"US","strategy":"turtle","side":"SELL","symbol":"HBAN","qty":1,"price":17.16,"status":"FILLED_CONFIRMED","detail":"","reconciled_at":None},
                {"datetime":"2026-08-13 06:20:08","market":"US","strategy":"turtle","side":"SELL","symbol":"BXP","qty":1,"price":67.49,"status":"FILLED_CONFIRMED","detail":"","reconciled_at":None},
                {"datetime":"2026-07-11 06:20:14","market":"US","strategy":"turtle","side":"BUY","symbol":"AES","qty":1,"price":14.74,"status":"DRY_RUN","detail":"","reconciled_at":None}
            ]}),encoding="utf-8")
            snap=LiveTradingEvidenceAdapter(root).load()
            self.assertEqual(len(snap.round_trips),1)
            self.assertEqual(snap.round_trips[0].symbol,"HBAN")
            self.assertEqual(len(snap.unmatched_sells),1)
            self.assertEqual(snap.unmatched_sells[0].symbol,"BXP")
            self.assertEqual(snap.metrics()["dry_run_count"],1)
            fb=build_feedback(snap,"US")
            self.assertEqual(fb.completed_trade_count,1)
            self.assertIn("incomplete_history",fb.classifications)

    def test_inaccessible_production_root_is_unavailable(self):
        adapter = LiveTradingEvidenceAdapter(
            "/root/MyMoneyGuard"
        )

        with patch.object(
            Path,
            "is_dir",
            side_effect=PermissionError(
                "CI runner cannot stat /root"
            ),
        ):
            self.assertFalse(adapter.available())

    def test_secret_access_is_denied(self):
        with TemporaryDirectory() as tmp:
            root=self._root(tmp)
            (root/"order_ledger.json").write_text('{"orders":[]}',encoding="utf-8")
            adapter=LiveTradingEvidenceAdapter(root)
            with self.assertRaises(PermissionError): adapter._read_json(".env")
            with self.assertRaises(PermissionError): adapter._read_json("../order_ledger.json")

    def test_adaptive_budget_and_sampling(self):
        candidates=tuple(MarketSymbol(f"S{i:02d}",f"S{i:02d}","MULTI",ex) for i,ex in enumerate(
            ("KOSPI","KOSDAQ","NASDAQ","NYSE","AMEX")*3,start=1))
        batches=adaptive_batches(candidates,("KOSPI","KOSDAQ","NASDAQ","NYSE","AMEX"),
            ("S01","S02"),10,4,"unit")
        symbols=tuple(x for b in batches for x in b)
        self.assertEqual(len(symbols),len(set(symbols)))
        self.assertLessEqual(2+len(symbols),10)
        env={"GAON_GLOBAL_RESEARCH_MAX_SYMBOLS":"3"}
        self.assertEqual(adaptive_budget(env,3,5000),3)

    def test_release_check(self):
        payload=release_check()
        self.assertEqual(payload["round_trips"],1)
        self.assertEqual(payload["unmatched_sells"],1)
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["order_executed"])

if __name__=="__main__":
    unittest.main()
