import sqlite3
import tempfile
import unittest

from gaon.runtime.cli import main as cli_main


class AutonomousRetestFlowTests(unittest.TestCase):
    def test_release_check_repeats_on_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/retest.sqlite"
            for _ in range(3):
                self.assertEqual(cli_main(["autonomous-retest-release-check", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
                runs = connection.execute("SELECT COUNT(*) FROM research_retest_runs").fetchone()[0]
                evidence = connection.execute("SELECT COUNT(*) FROM research_retest_evidence").fetchone()[0]
                applied_configs = connection.execute("SELECT COUNT(*) FROM strategy_config_versions").fetchone()[0]
                self.assertEqual(version, 35)
                self.assertEqual(runs, 0)
                self.assertEqual(evidence, 0)
                self.assertEqual(applied_configs, 0)
            finally:
                connection.close()

    def test_demo_status_and_history_cli(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/retest-demo.sqlite"
            self.assertEqual(cli_main(["research-retest-demo", "--db", db_path, "--persist"]), 0)
            self.assertEqual(cli_main(["research-retest-status", "--db", db_path]), 0)
            self.assertEqual(cli_main(["research-retest-history", "--db", db_path]), 0)

    def test_telegram_retest_persistence_release_check_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/telegram-retest.sqlite"
            for _ in range(2):
                self.assertEqual(cli_main(["telegram-retest-persistence-release-check", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_retest_runs").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM research_retest_evidence").fetchone()[0], 0)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
