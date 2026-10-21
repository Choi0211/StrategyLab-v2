from __future__ import annotations
import tempfile
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import gaon.runtime.research_learning as learning

class ResearchLearningTests(unittest.TestCase):
    def test_us_validation_uses_multisymbol_provider_and_backtest_provenance(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(learning, "ROOT", Path(tmp)), \
             patch.object(learning, "INDEX", Path(tmp)/"learned_sources.jsonl"), \
             patch.object(learning, "url_read", return_value={"source":"https://example.com/research", "text":"Untrusted evidence. "*10}):
            first = learning.learn({"url":"https://example.com/research"})
            for source, fixture, eligible, expected in (("real", False, True, True),
                    ("fixture", True, True, False), ("real", False, False, False)):
                report = {"request":{"source":source, "provider":"real:kis-master+yahoo-chart", "fixture_backed":fixture},
                          "evidence":[{"eligible":eligible, "fixture_backed":fixture, "source":source, "provider":"real:yahoo-chart"}]}
                with patch("gaon.research.multi_symbol.multi_symbol_research_payload", return_value=report):
                    with sqlite3.connect(":memory:") as connection:
                        result = learning.validate(connection, {"evidence_id":first["evidence_id"], "market":"US", "symbol":"AAPL"})
                self.assertEqual(result["validation"]["independent_market_evidence"], expected)
                self.assertFalse(result["validated"])

    def test_fixture_or_failed_reports_never_become_independent_evidence(self):
        for metadata, usable in (({}, True), ({"source": "fixture:test", "fixture_backed": True}, True),
                                 ({"source": "real:test", "fixture_backed": False}, False)):
            validation = {}
            learning._attach_market_evidence(validation, {}, metadata, usable=usable)
            self.assertFalse(validation["independent_market_evidence"])
            self.assertEqual(validation["status"], "market_evidence_unverified")

    def test_kr_validation_checks_actual_dataset_provenance(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(learning, "ROOT", Path(tmp)), \
             patch.object(learning, "INDEX", Path(tmp)/"learned_sources.jsonl"), \
             patch.object(learning, "url_read", return_value={"source":"https://example.com/research", "text":"Evidence is untrusted until independent validation. "*3}):
            first = learning.learn({"url":"https://example.com/research"})
            for fixture in (True, False):
                report = {"dataset": {"metadata": {"source":"fixture:test" if fixture else "real:test", "fixture_backed":fixture}},
                          "quality":{"status":"pass"}, "backtest":{"status":"completed"}}
                with patch("gaon.research.krx_real_pipeline.krx_real_research_payload", return_value=report):
                    with sqlite3.connect(":memory:") as connection:
                        result = learning.validate(connection, {"evidence_id":first["evidence_id"], "market":"KR", "symbol":"005930"})
                self.assertEqual(result["validation"]["independent_market_evidence"], not fixture)
                self.assertFalse(result["validated"])
                self.assertFalse(result["automatic_promotion"])
            self.assertFalse(learning._load(first["evidence_id"])["validated"])

    def test_store_recall_duplicate_and_advisory_validation(self):
        old_root,old_index,old_reader=learning.ROOT,learning.INDEX,learning.url_read
        with tempfile.TemporaryDirectory() as tmp:
            learning.ROOT=Path(tmp); learning.INDEX=Path(tmp)/"learned_sources.jsonl"
            learning.url_read=lambda _args:{"source":"https://example.com/research","mime":"text/html","text":"Momentum strategy transaction cost evidence "*5}
            try:
                first=learning.learn({"url":"https://example.com/research"})
                self.assertEqual(first["status"],"stored")
                second=learning.learn({"url":"https://example.com/research"})
                self.assertEqual(second["status"],"duplicate")
                recalled=learning.recall({"query":"transaction cost"})
                self.assertEqual(len(recalled["results"]),1)
                result=learning.validate(sqlite3.connect(":memory:"),{"evidence_id":first["evidence_id"]})
                self.assertEqual(result["validation"]["status"],"needs_market_context")
                self.assertFalse(result["validated"])
            finally:
                learning.ROOT,learning.INDEX,learning.url_read=old_root,old_index,old_reader

if __name__ == "__main__": unittest.main()
