import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO

from gaon.research.orchestration_v3 import ResearchOrchestratorV3, ResearchRunState, SQLiteResearchRunRepository, research_run_event
from gaon.runtime.cli import main as cli_main
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


class ResearchOrchestrationV3FlowTest(unittest.TestCase):
    def test_complete_deterministic_research_run_and_resume(self) -> None:
        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        repo = SQLiteResearchRunRepository(store._connection)
        orchestrator = ResearchOrchestratorV3(repo, metrics=metrics)

        run, report = orchestrator.run("ORB evidence", run_id="run-1", dry_run=True)
        restored = orchestrator.resume("run-1")
        event = research_run_event(run)

        self.assertEqual(run.status, ResearchRunState.COMPLETED)
        self.assertEqual(restored.status, ResearchRunState.COMPLETED)
        self.assertIn("C1", report.to_markdown())
        self.assertIn("knowledge_proposals", report.to_json())
        self.assertEqual(event.event_type, "ResearchRunStateChanged")
        self.assertIn("gaon_research_runs_total", metrics.snapshot().to_text())
        store.close()

    def test_cli_research_smoke(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["research-plan", "--query", "ORB"]), 0)
            self.assertEqual(cli_main(["research-run", "--query", "ORB", "--dry-run"]), 0)
            self.assertEqual(cli_main(["research-status", "run-1"]), 0)
            self.assertEqual(cli_main(["research-report", "run-1", "--format", "markdown"]), 0)
            self.assertEqual(cli_main(["research-resume", "run-1"]), 0)
        self.assertIn("research-run", output.getvalue())

    def test_migration_from_v7(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (7);
                CREATE TABLE research_approval_decisions (decision_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, proposal_hash TEXT NOT NULL, proposal_version INTEGER NOT NULL, actor_ref TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL, decided_at TEXT NOT NULL, consumed INTEGER NOT NULL DEFAULT 0);
                """
            )
            connection.commit()
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertTrue(connection.execute("SELECT name FROM sqlite_master WHERE name = 'research_brain_runs'").fetchone())
            connection.close()

    def test_migration_from_v2_creates_research_brain_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (2);
                CREATE TABLE telegram_offsets (chat_id TEXT PRIMARY KEY, next_offset INTEGER NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE processed_messages (message_id TEXT PRIMARY KEY, processed_at TEXT NOT NULL);
                CREATE TABLE scheduler_jobs (job_id TEXT PRIMARY KEY, next_run_at TEXT NOT NULL, last_run_at TEXT, idempotency_key TEXT, execution_status TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE research_proposals (proposal_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE approvals (approval_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, status TEXT NOT NULL, expires_at TEXT NOT NULL, requested_actor TEXT NOT NULL DEFAULT '', requested_chat_id TEXT NOT NULL DEFAULT '', token_digest TEXT NOT NULL DEFAULT '', issued_at TEXT NOT NULL DEFAULT '', nonce TEXT NOT NULL DEFAULT '', consumed_by_run_id TEXT);
                CREATE TABLE research_runs (run_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE runtime_audit_events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE notification_attempts (attempt_id TEXT PRIMARY KEY, target_ref TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}');
                """
            )
            connection.commit()
            migrate(connection)
            self.assertEqual(connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0], SCHEMA_VERSION)
            self.assertTrue(connection.execute("SELECT name FROM sqlite_master WHERE name = 'knowledge_proposals'").fetchone())
            self.assertTrue(connection.execute("SELECT name FROM sqlite_master WHERE name = 'research_approval_decisions'").fetchone())
            self.assertTrue(connection.execute("SELECT name FROM sqlite_master WHERE name = 'research_brain_checkpoints'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
