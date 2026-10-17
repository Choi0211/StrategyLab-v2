from __future__ import annotations
import tempfile
from pathlib import Path
import sqlite3
import unittest
import gaon.runtime.research_learning as learning

class ResearchLearningTests(unittest.TestCase):
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
