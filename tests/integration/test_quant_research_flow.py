import tempfile
import unittest
from pathlib import Path

from gaon.runtime.cli import main
from gaon.runtime.storage import RuntimeStateStore


class QuantResearchFlowTests(unittest.TestCase):
    def test_quant_research_release_and_demo_persist_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "gaon-runtime.sqlite")
            self.assertEqual(main(["quant-research-release-check", "--db", db]), 0)
            self.assertEqual(main(["quant-research-demo", "--db", db, "--report-id", "integration-quant"]), 0)
            store = RuntimeStateStore(db)
            try:
                rows = store._connection.execute("SELECT report_id FROM quant_research_reports ORDER BY report_id").fetchall()
                self.assertEqual({str(row[0]) for row in rows}, {"integration-quant", "quant-research-release-check"})
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
