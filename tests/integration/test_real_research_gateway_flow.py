import sqlite3
import tempfile
import unittest

from gaon.runtime.cli import main
from gaon.runtime.migrations import SCHEMA_VERSION


class RealResearchGatewayFlowTests(unittest.TestCase):
    def test_demos_and_release_check_persist_on_one_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/gaon.sqlite"
            self.assertEqual(main(["market-data-demo", "--db", db, "--symbol", "005930"]), 0)
            self.assertEqual(main(["data-quality-demo", "--db", db, "--symbol", "005930"]), 0)
            self.assertEqual(main(["backtest-contract-demo", "--db", db, "--symbol", "005930"]), 0)
            self.assertEqual(main(["external-backtest-demo", "--db", db, "--symbol", "005930"]), 0)
            self.assertEqual(main(["real-research-demo", "--db", db, "--symbol", "005930", "--request-id", "integration-real"]), 0)
            self.assertEqual(main(["real-research-integration-release-check", "--db", db]), 0)
            connection = sqlite3.connect(db)
            try:
                version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
                datasets = connection.execute("SELECT COUNT(*) FROM market_datasets").fetchone()[0]
                specs = connection.execute("SELECT COUNT(*) FROM strategy_specs").fetchone()[0]
                runs = connection.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
                results = connection.execute("SELECT COUNT(*) FROM real_backtest_results").fetchone()[0]
                reports = connection.execute("SELECT COUNT(*) FROM real_research_reports").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertGreaterEqual(datasets, 1)
            self.assertGreaterEqual(specs, 1)
            self.assertGreaterEqual(runs, 2)
            self.assertGreaterEqual(results, 2)
            self.assertGreaterEqual(reports, 2)

    def test_release_check_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/gaon.sqlite"
            self.assertEqual(main(["real-research-integration-release-check", "--db", db]), 0)
            self.assertEqual(main(["real-research-integration-release-check", "--db", db]), 0)
            self.assertEqual(main(["real-research-integration-release-check", "--db", db]), 0)
            connection = sqlite3.connect(db)
            try:
                duplicate_datasets = connection.execute("SELECT fingerprint, COUNT(*) FROM market_datasets GROUP BY fingerprint HAVING COUNT(*) > 1").fetchall()
                duplicate_runs = connection.execute("SELECT request_fingerprint, COUNT(*) FROM backtest_runs GROUP BY request_fingerprint HAVING COUNT(*) > 1").fetchall()
            finally:
                connection.close()
            self.assertEqual(duplicate_datasets, [])
            self.assertEqual(duplicate_runs, [])

    def test_existing_release_checks_still_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/gaon.sqlite"
            for command in (
                "conversation-release-check",
                "llm-agent-release-check",
                "long-response-release-check",
                "external-research-release-check",
                "quant-research-release-check",
                "feature-discovery-release-check",
                "ai-scientist-release-check",
                "self-improving-research-release-check",
                "real-research-integration-release-check",
            ):
                with self.subTest(command=command):
                    self.assertEqual(main([command, "--db", db]), 0)


if __name__ == "__main__":
    unittest.main()
