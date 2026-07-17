import os
import sqlite3
import tempfile
import unittest

from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.storage import RuntimeStateStore


class RecordingProjection:
    projection_id = "projection:test"

    def __init__(self, fail_event_id: str | None = None) -> None:
        self.events: list[str] = []
        self.fail_event_id = fail_event_id

    def apply(self, event: DurableEvent, *, dry_run: bool) -> None:
        if event.event_id == self.fail_event_id:
            raise RuntimeError("synthetic")
        if not dry_run:
            self.events.append(event.event_id)


class EventStoreTest(unittest.TestCase):
    def event(self, event_id: str, occurred_at: str = "2026-07-18T00:00:00Z") -> DurableEvent:
        return DurableEvent(
            event_id=event_id,
            event_type="RuntimeEvent",
            occurred_at=occurred_at,
            actor_ref="actor:redacted",
            correlation_id="corr",
            causation_id=None,
            scope="runtime",
            project="StrategyLab",
            strategy="N/A",
            market="N/A",
            payload={"status": "ok"},
            evidence_refs=("ev-1",),
            audit_refs=("audit-1",),
            appended_at=occurred_at,
        )

    def test_append_read_duplicate_and_order(self) -> None:
        store = RuntimeStateStore(":memory:")
        events = SQLiteEventStore(store._connection)
        events.append(self.event("event-2", "2026-07-18T00:00:02Z"))
        events.append(self.event("event-1", "2026-07-18T00:00:01Z"))

        ordered = events.read_after(limit=10)

        self.assertEqual(tuple(event.event_id for event in ordered), ("event-1", "event-2"))
        with self.assertRaises(sqlite3.IntegrityError):
            events.append(self.event("event-1"))
        store.close()

    def test_replay_dry_run_checkpoint_and_failure_isolation(self) -> None:
        store = RuntimeStateStore(":memory:")
        events = SQLiteEventStore(store._connection)
        events.append(self.event("event-1", "2026-07-18T00:00:01Z"))
        events.append(self.event("event-2", "2026-07-18T00:00:02Z"))

        dry = events.replay(RecordingProjection(), dry_run=True)
        self.assertEqual(dry.processed, 2)
        self.assertIsNone(events.checkpoint("projection:test"))

        live_projection = RecordingProjection(fail_event_id="event-2")
        live = events.replay(live_projection, dry_run=False)

        self.assertEqual(live.processed, 1)
        self.assertEqual(live.failed, 1)
        self.assertEqual(events.checkpoint("projection:test"), "event-1")
        self.assertEqual(live_projection.events, ["event-1"])
        store.close()

    def test_oversized_payload_and_batch_limit(self) -> None:
        store = RuntimeStateStore(":memory:")
        events = SQLiteEventStore(store._connection)
        big = self.event("event-big")
        big = DurableEvent(**{**big.__dict__, "payload": {"x": "y" * 40_000}})

        with self.assertRaises(ValueError):
            events.append(big)
        with self.assertRaises(ValueError):
            events.read_after(limit=0)
        store.close()

    def test_schema_v3_migrates_to_v4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "runtime.sqlite")
            connection = sqlite3.connect(db)
            connection.executescript(
                """
                CREATE TABLE schema_version (version INTEGER NOT NULL);
                INSERT INTO schema_version(version) VALUES (3);
                CREATE TABLE telegram_offsets (chat_id TEXT PRIMARY KEY, next_offset INTEGER NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE processed_messages (message_id TEXT PRIMARY KEY, processed_at TEXT NOT NULL);
                CREATE TABLE scheduler_jobs (job_id TEXT PRIMARY KEY, next_run_at TEXT NOT NULL, last_run_at TEXT, idempotency_key TEXT, execution_status TEXT NOT NULL DEFAULT 'pending');
                CREATE TABLE research_proposals (proposal_id TEXT PRIMARY KEY, status TEXT NOT NULL, payload_json TEXT NOT NULL);
                CREATE TABLE approvals (approval_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, status TEXT NOT NULL, expires_at TEXT NOT NULL);
                CREATE TABLE research_runs (run_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE runtime_audit_events (event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE notification_attempts (attempt_id TEXT PRIMARY KEY, target_ref TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}');
                CREATE TABLE runtime_queue (item_id TEXT PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE, payload_json TEXT NOT NULL, status TEXT NOT NULL, priority INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3, available_at TEXT NOT NULL, leased_until TEXT, last_error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                """
            )
            connection.commit()
            migrate(connection)
            version = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()[0]
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertTrue(connection.execute("SELECT name FROM sqlite_master WHERE name = 'durable_events'").fetchone())
            connection.close()


if __name__ == "__main__":
    unittest.main()
