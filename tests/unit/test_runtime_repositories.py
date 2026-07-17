import os
import sqlite3
import tempfile
import unittest

from gaon.research.approval import ApprovalStatus, create_approval_request
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.repositories import SQLiteApprovalRepository, SQLiteProposalRepository, SQLiteSchedulerJobRepository, StoredProposal, StoredSchedulerJob
from gaon.runtime.serialization import loads_json
from gaon.runtime.storage import RuntimeStateStore


class RuntimeRepositoriesTest(unittest.TestCase):
    def test_schema_v2_new_database_and_repository_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStateStore(os.path.join(tmp, "runtime.sqlite"))
            self.assertEqual(store.status().schema_version, SCHEMA_VERSION)

            approval = create_approval_request(
                "approval-1",
                "proposal-1",
                "youngha",
                "100",
                "raw-token",
                "2026-07-17T00:00:00Z",
                "2026-07-18T00:00:00Z",
                signing_secret="secret",
                nonce="nonce-1",
            )
            repo = SQLiteApprovalRepository(store._connection)
            repo.add(approval)
            restored = repo.get("approval-1")

            self.assertEqual(restored.status, ApprovalStatus.PENDING)
            self.assertNotEqual(restored.token_digest, "raw-token")
            store.close()

    def test_v1_database_migrates_without_data_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (1);
                CREATE TABLE telegram_offsets (chat_id TEXT PRIMARY KEY, next_offset INTEGER NOT NULL, updated_at TEXT NOT NULL);
                INSERT INTO telegram_offsets(chat_id, next_offset, updated_at) VALUES ('100', 7, '2026-07-17T00:00:00Z');
                CREATE TABLE processed_messages (message_id TEXT PRIMARY KEY, processed_at TEXT NOT NULL);
                CREATE TABLE scheduler_jobs (job_id TEXT PRIMARY KEY, next_run_at TEXT NOT NULL, last_run_at TEXT);
                CREATE TABLE research_proposals (proposal_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE approvals (approval_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, status TEXT NOT NULL, expires_at TEXT NOT NULL);
                CREATE TABLE research_runs (run_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE runtime_audit_events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE notification_attempts (attempt_id TEXT PRIMARY KEY, target_ref TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
                """
            )
            connection.commit()
            migrate(connection)

            version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
            offset = connection.execute("SELECT next_offset FROM telegram_offsets WHERE chat_id = '100'").fetchone()[0]

            self.assertEqual(version, SCHEMA_VERSION)
            self.assertEqual(offset, 7)
            connection.close()

    def test_repository_json_validation_and_scheduler_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStateStore(os.path.join(tmp, "runtime.sqlite"))
            proposals = SQLiteProposalRepository(store._connection)
            scheduler = SQLiteSchedulerJobRepository(store._connection)

            proposals.upsert(StoredProposal("proposal-1", "pending", {"goal": "research"}))
            self.assertEqual(proposals.get("proposal-1").payload["goal"], "research")
            scheduler.upsert(StoredSchedulerJob("job-1", "2026-07-17T01:00:00Z", idempotency_key="daily:2026-07-17"))
            with self.assertRaises(sqlite3.IntegrityError):
                scheduler.upsert(StoredSchedulerJob("job-2", "2026-07-17T01:00:00Z", idempotency_key="daily:2026-07-17"))
            with self.assertRaises(ValueError):
                loads_json("[]")
            with self.assertRaises(ValueError):
                loads_json("{")
            store.close()


if __name__ == "__main__":
    unittest.main()
