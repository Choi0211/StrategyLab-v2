import sqlite3
import tempfile
import unittest

from gaon.runtime.cli import main as cli_main


class ResearchOperationsFlowTests(unittest.TestCase):
    def test_research_ops_release_check_is_repeatable_on_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/research-ops.sqlite"
            for _ in range(3):
                self.assertEqual(cli_main(["research-ops-release-check", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
                self.assertEqual(version, 34)
                reports = connection.execute("SELECT COUNT(*) FROM research_operation_reports").fetchone()[0]
                configs = connection.execute("SELECT COUNT(*) FROM strategy_config_versions").fetchone()[0]
                audits = connection.execute("SELECT COUNT(*) FROM strategy_config_audit").fetchone()[0]
                self.assertGreaterEqual(reports, 9)
                self.assertGreaterEqual(configs, 6)
                self.assertGreaterEqual(audits, 15)
            finally:
                connection.close()

    def test_cli_demo_and_report_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/research-ops-demo.sqlite"
            self.assertEqual(cli_main(["research-ops-demo", "--db", db_path]), 0)
            self.assertEqual(cli_main(["research-ops-report", "--db", db_path]), 0)


if __name__ == "__main__":
    unittest.main()
