import sqlite3
import tempfile
import unittest

from gaon.runtime.cli import main as cli_main
from gaon.runtime.migrations import SCHEMA_VERSION


class ResearchOperationsFlowTests(unittest.TestCase):
    def test_research_ops_release_check_is_repeatable_on_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/research-ops.sqlite"
            for _ in range(3):
                self.assertEqual(cli_main(["research-ops-release-check", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
                self.assertEqual(version, SCHEMA_VERSION)
                reports = connection.execute("SELECT COUNT(*) FROM research_operation_reports").fetchone()[0]
                approvals = connection.execute("SELECT COUNT(*) FROM research_config_approvals").fetchone()[0]
                configs = connection.execute("SELECT COUNT(*) FROM strategy_config_versions").fetchone()[0]
                audits = connection.execute("SELECT COUNT(*) FROM strategy_config_audit").fetchone()[0]
                self.assertEqual(reports, 0)
                self.assertEqual(approvals, 0)
                self.assertEqual(configs, 0)
                self.assertEqual(audits, 0)
            finally:
                connection.close()

    def test_cli_demo_and_report_are_readable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/research-ops-demo.sqlite"
            self.assertEqual(cli_main(["research-ops-demo", "--db", db_path]), 0)
            self.assertEqual(cli_main(["research-ops-report", "--db", db_path]), 0)

    def test_cleanup_cli_removes_only_persisted_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/research-ops-cleanup.sqlite"
            self.assertEqual(cli_main(["research-ops-demo", "--db", db_path, "--persist"]), 0)
            self.assertEqual(cli_main(["research-ops-cleanup", "--db", db_path, "--dry-run"]), 0)
            connection = sqlite3.connect(db_path)
            try:
                before = connection.execute("SELECT COUNT(*) FROM research_operation_reports").fetchone()[0]
                self.assertEqual(before, 1)
            finally:
                connection.close()

            self.assertEqual(cli_main(["research-ops-cleanup", "--db", db_path, "--apply"]), 0)
            connection = sqlite3.connect(db_path)
            try:
                after = connection.execute("SELECT COUNT(*) FROM research_operation_reports").fetchone()[0]
                cleanup_audit = connection.execute("SELECT COUNT(*) FROM strategy_config_audit WHERE event_type = 'artifact_cleanup'").fetchone()[0]
                self.assertEqual(after, 0)
                self.assertEqual(cleanup_audit, 1)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
