import tempfile
import unittest
from pathlib import Path

from gaon.runtime.cli import main
from gaon.runtime.storage import RuntimeStateStore


class AIScientistFlowTests(unittest.TestCase):
    def test_feature_discovery_and_ai_scientist_release_checks_persist_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "gaon-runtime.sqlite")
            self.assertEqual(main(["feature-discovery-release-check", "--db", db]), 0)
            self.assertEqual(main(["feature-discovery-demo", "--db", db, "--symbol", "KOSPI"]), 0)
            self.assertEqual(main(["ai-scientist-release-check", "--db", db]), 0)
            self.assertEqual(main(["ai-scientist-demo", "--db", db, "--report-id", "integration-ai-scientist"]), 0)
            store = RuntimeStateStore(db)
            try:
                rows = store._connection.execute("SELECT report_id FROM ai_scientist_reports ORDER BY report_id").fetchall()
                self.assertEqual({str(row[0]) for row in rows}, {"ai-scientist-release-check", "integration-ai-scientist"})
                selected = store._connection.execute("SELECT COUNT(*) FROM ai_feature_importance").fetchone()[0]
                walk_forward = store._connection.execute("SELECT COUNT(*) FROM ai_walk_forward_results").fetchone()[0]
                monte_carlo = store._connection.execute("SELECT COUNT(*) FROM ai_monte_carlo_results").fetchone()[0]
                self.assertEqual(int(selected), 6)
                self.assertEqual(int(walk_forward), 6)
                self.assertEqual(int(monte_carlo), 2)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
