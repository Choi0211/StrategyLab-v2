import sqlite3
import tempfile
import unittest

from gaon.research.multi_symbol import PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT
from gaon.runtime.cli import main as cli_main
from gaon.runtime.migrations import SCHEMA_VERSION


class MultiSymbolResearchFlowTests(unittest.TestCase):
    def test_release_checks_are_isolated_and_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = f"{tempdir}/multi-symbol.sqlite"
            for _ in range(3):
                self.assertEqual(cli_main(["multi-symbol-research-release-check", "--db", db_path]), 0)
                self.assertEqual(cli_main(["telegram-multi-symbol-research-release-check", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM multi_symbol_research_runs").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM multi_symbol_symbol_evidence").fetchone()[0], 0)
            finally:
                connection.close()

    def test_demo_persistence_status_and_history(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = f"{tempdir}/multi-symbol-demo.sqlite"
            self.assertEqual(cli_main(["multi-symbol-research-demo", "--db", db_path, "--persist"]), 0)
            self.assertEqual(cli_main(["multi-symbol-research-status", "--db", db_path]), 0)
            self.assertEqual(cli_main(["multi-symbol-research-history", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM multi_symbol_research_runs").fetchone()[0], 1)
                self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM multi_symbol_symbol_evidence").fetchone()[0], 1)
            finally:
                connection.close()

    def test_telegram_routing_debug_accepts_production_text(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            text_path = f"{tempdir}/production-request.txt"
            with open(text_path, "w", encoding="utf-8") as handle:
                handle.write(PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT)

            self.assertEqual(cli_main(["telegram-routing-debug", "--text-file", text_path, "--json"]), 0)


if __name__ == "__main__":
    unittest.main()
