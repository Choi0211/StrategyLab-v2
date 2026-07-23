import sqlite3
import tempfile
import unittest

from gaon.runtime.cli import main
from gaon.runtime.migrations import SCHEMA_VERSION


class SelfImprovingResearchFlowTests(unittest.TestCase):
    def test_release_check_and_demos_persist_on_one_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/gaon.sqlite"
            self.assertEqual(main(["research-critic-demo", "--db", db, "--scenario", "overfit"]), 0)
            self.assertEqual(main(["research-memory-demo", "--db", db]), 0)
            self.assertEqual(main(["research-iteration-demo", "--db", db, "--max-iterations", "3"]), 0)
            self.assertEqual(main(["research-tournament-demo", "--db", db, "--top-n", "2"]), 0)
            self.assertEqual(main(["autonomous-research-demo", "--db", db, "--run-id", "integration-auto"]), 0)
            self.assertEqual(main(["self-improving-research-release-check", "--db", db]), 0)
            connection = sqlite3.connect(db)
            try:
                version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
                memories = connection.execute("SELECT COUNT(*) FROM research_memories").fetchone()[0]
                lineage = connection.execute("SELECT COUNT(*) FROM strategy_lineage").fetchone()[0]
                iterations = connection.execute("SELECT COUNT(*) FROM research_iterations").fetchone()[0]
                quality = connection.execute("SELECT COUNT(*) FROM research_quality_scores").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertGreaterEqual(memories, 2)
            self.assertGreaterEqual(lineage, 3)
            self.assertGreaterEqual(iterations, 1)
            self.assertGreaterEqual(quality, 1)

    def test_release_check_is_repeatable_and_duplicate_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/gaon.sqlite"
            self.assertEqual(main(["self-improving-research-release-check", "--db", db]), 0)
            self.assertEqual(main(["self-improving-research-release-check", "--db", db]), 0)
            self.assertEqual(main(["self-improving-research-release-check", "--db", db]), 0)
            connection = sqlite3.connect(db)
            try:
                fingerprints = connection.execute("SELECT fingerprint, COUNT(*) FROM research_memories GROUP BY fingerprint HAVING COUNT(*) > 1").fetchall()
                tool_names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                connection.close()
            self.assertEqual(fingerprints, [])
            self.assertIn("research_memories", tool_names)

    def test_regression_release_checks_still_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = f"{tmp}/gaon.sqlite"
            for command in (
                "feature-discovery-release-check",
                "ai-scientist-release-check",
                "quant-research-release-check",
                "conversation-release-check",
                "llm-agent-release-check",
                "long-response-release-check",
                "self-improving-research-release-check",
            ):
                with self.subTest(command=command):
                    self.assertEqual(main([command, "--db", db]), 0)


if __name__ == "__main__":
    unittest.main()
