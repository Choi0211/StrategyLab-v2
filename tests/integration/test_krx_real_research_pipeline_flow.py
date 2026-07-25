import sqlite3
import tempfile
import unittest

from gaon.runtime.cli import main as cli_main
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest, default_tool_registry
from gaon.runtime.migrations import migrate


NOW = "2026-07-25T00:00:00Z"


class KRXRealResearchPipelineIntegrationTests(unittest.TestCase):
    def test_release_check_is_repeatable_on_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/krx-real-research.sqlite"
            for _ in range(3):
                self.assertEqual(cli_main(["krx-real-research-release-check", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM krx_real_research_memories").fetchone()[0], 6)
            finally:
                connection.close()

    def test_trading_calendar_release_check_is_repeatable_on_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/krx-calendar.sqlite"
            for _ in range(3):
                self.assertEqual(cli_main(["krx-trading-calendar-release-check", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
                self.assertEqual(version, 33)
                self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM market_datasets").fetchone()[0], 1)
            finally:
                connection.close()

    def test_provider_gap_release_check_is_repeatable_on_persistent_db(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            db_path = f"{folder}/provider-gap.sqlite"
            for _ in range(3):
                self.assertEqual(cli_main(["provider-gap-release-check", "--db", db_path]), 0)
            connection = sqlite3.connect(db_path)
            try:
                version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
                self.assertEqual(version, 33)
                self.assertGreaterEqual(connection.execute("SELECT COUNT(*) FROM market_datasets").fetchone()[0], 1)
            finally:
                connection.close()

    def test_safe_tool_runs_read_only_pipeline(self) -> None:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
        executor = SafeToolExecutor(default_tool_registry(connection))
        result = executor.execute(
            ToolRequest(
                "krx_real_research",
                {"request_text": "20일 고가 돌파 + 종가 > MA20 > MA60 + 거래량 >= 20일 평균 이상, 손절 -5%, 10일 저점 이탈 청산"},
                "integration",
                NOW,
            )
        )
        self.assertEqual(result.status, "success")
        self.assertEqual(result.output["backtest"]["source"], "fixture")
        self.assertFalse(result.output["automatic_order"])
        self.assertFalse(result.output["automatic_champion_promotion"])
        self.assertIn("source=fixture", result.output["korean_report"])

    def test_cli_release_checks_pass(self) -> None:
        self.assertEqual(cli_main(["strategy-parser-release-check", "--db", ":memory:"]), 0)
        self.assertEqual(cli_main(["real-backtest-release-check", "--db", ":memory:"]), 0)
        self.assertEqual(cli_main(["krx-real-research-release-check", "--db", ":memory:"]), 0)
        self.assertEqual(cli_main(["krx-trading-calendar-release-check", "--db", ":memory:"]), 0)
        self.assertEqual(cli_main(["provider-gap-release-check", "--db", ":memory:"]), 0)


if __name__ == "__main__":
    unittest.main()
