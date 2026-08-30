"""Production SQLite Lock Stability hotfix - regression tests.

Covers: non-critical Telegram telemetry lock isolation (never silently
swallowing anything beyond genuine lock/busy contention), explicit bounded
SQLite busy timeout, migration ownership (owner vs non-owner fail-closed
schema check), and bounded retry/serialization for concurrent migration
attempts. Uses real on-disk SQLite files (not ``:memory:``) wherever
genuine cross-connection lock contention needs to be exercised - an
in-memory database is not shared across connections the way a file-based
one is.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from gaon.runtime.errors import SchemaVersionMismatchError
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.migrations import SCHEMA_VERSION, check_schema_version_compatible, migrate
from gaon.runtime.sqlite_lock import DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS, is_lock_or_busy_error, retry_on_lock
from gaon.runtime.storage import RuntimeStateStore
from gaon.runtime.telegram_worker import TelegramPollingWorker

from test_runtime_service import _execute_telegram_config, _FakeTelegramClient

_NOW = "2026-08-30T00:00:00Z"


def _temp_db_path() -> str:
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    os.remove(path)  # RuntimeStateStore/sqlite3.connect creates it fresh
    return path


class LockClassificationTests(unittest.TestCase):
    def test_lock_message_is_classified(self) -> None:
        self.assertTrue(is_lock_or_busy_error(sqlite3.OperationalError("database is locked")))

    def test_busy_message_is_classified(self) -> None:
        self.assertTrue(is_lock_or_busy_error(sqlite3.OperationalError("database is busy")))

    def test_unrelated_operational_error_is_not_classified(self) -> None:
        self.assertFalse(is_lock_or_busy_error(sqlite3.OperationalError("no such table: durable_events")))
        self.assertFalse(is_lock_or_busy_error(sqlite3.OperationalError("disk I/O error")))

    def test_non_operational_error_is_not_classified(self) -> None:
        self.assertFalse(is_lock_or_busy_error(ValueError("database is locked")))  # message alone is not enough


class RetryOnLockTests(unittest.TestCase):
    def test_F_bounded_attempts_no_infinite_wait(self) -> None:
        calls = {"count": 0}
        sleeps: list[float] = []

        def always_locked():
            calls["count"] += 1
            raise sqlite3.OperationalError("database is locked")

        with self.assertRaises(sqlite3.OperationalError):
            retry_on_lock(always_locked, attempts=3, base_delay_seconds=0.01, sleep=sleeps.append)

        self.assertEqual(calls["count"], 3, "must stop after exactly `attempts` tries, never loop unboundedly")
        self.assertEqual(len(sleeps), 2, "sleeps only between attempts, never after the final one")

    def test_I_succeeds_once_lock_clears_within_attempt_budget(self) -> None:
        calls = {"count": 0}

        def locked_twice_then_ok():
            calls["count"] += 1
            if calls["count"] < 3:
                raise sqlite3.OperationalError("database is locked")
            return "ok"

        result = retry_on_lock(locked_twice_then_ok, attempts=5, base_delay_seconds=0.0, sleep=lambda _: None)
        self.assertEqual(result, "ok")
        self.assertEqual(calls["count"], 3)

    def test_J_non_lock_operational_error_never_retried(self) -> None:
        calls = {"count": 0}

        def raises_schema_error():
            calls["count"] += 1
            raise sqlite3.OperationalError("no such table: does_not_exist")

        with self.assertRaises(sqlite3.OperationalError):
            retry_on_lock(raises_schema_error, attempts=5, sleep=lambda _: None)
        self.assertEqual(calls["count"], 1, "a non-lock OperationalError must propagate on the first attempt, never retried")

    def test_C_non_sqlite_exception_never_swallowed(self) -> None:
        def raises_value_error():
            raise ValueError("programming error")

        with self.assertRaises(ValueError):
            retry_on_lock(raises_value_error, attempts=3, sleep=lambda _: None)

    def test_invalid_attempts_rejected(self) -> None:
        with self.assertRaises(ValueError):
            retry_on_lock(lambda: None, attempts=0)


class ExplicitBusyTimeoutTests(unittest.TestCase):
    def test_E_runtime_state_store_sets_explicit_busy_timeout(self) -> None:
        path = _temp_db_path()
        store = RuntimeStateStore(path)
        try:
            row = store._connection.execute("PRAGMA busy_timeout").fetchone()
            self.assertEqual(int(row[0]), int(DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS * 1000))
        finally:
            store.close()
            os.remove(path)

    def test_default_value_matches_repository_convention_not_an_arbitrary_number(self) -> None:
        # Matches Python's own sqlite3.connect() default timeout (5.0s),
        # already relied upon implicitly before this hotfix - not invented.
        self.assertEqual(DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS, 5.0)


class MigrationOwnershipTests(unittest.TestCase):
    def test_K_schema_version_is_41(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 41)

    def test_owner_migrates_on_fresh_database(self) -> None:
        path = _temp_db_path()
        store = RuntimeStateStore(path)  # owns_migration=True (default)
        try:
            self.assertEqual(store.status().schema_version, SCHEMA_VERSION)
        finally:
            store.close()
            os.remove(path)

    def test_L_non_owner_startup_allowed_when_schema_matches(self) -> None:
        path = _temp_db_path()
        owner = RuntimeStateStore(path)
        owner.close()
        non_owner = RuntimeStateStore(path, owns_migration=False)
        try:
            self.assertEqual(non_owner.status().schema_version, SCHEMA_VERSION)
        finally:
            non_owner.close()
            os.remove(path)

    def test_L_non_owner_fails_closed_on_fresh_unmigrated_database(self) -> None:
        path = _temp_db_path()
        # Create the file but never migrate it - simulates gaon-web-serve
        # starting before strategylab-gaon has ever run.
        sqlite3.connect(path).close()
        with self.assertRaises(SchemaVersionMismatchError):
            RuntimeStateStore(path, owns_migration=False)
        os.remove(path)

    def test_L_non_owner_fails_closed_on_stale_schema_version(self) -> None:
        path = _temp_db_path()
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION - 1,))
        connection.commit()
        connection.close()
        with self.assertRaises(SchemaVersionMismatchError):
            RuntimeStateStore(path, owns_migration=False)
        os.remove(path)

    def test_check_schema_version_compatible_never_writes(self) -> None:
        path = _temp_db_path()
        owner_connection = sqlite3.connect(path)
        migrate(owner_connection)
        owner_connection.close()

        checker_connection = sqlite3.connect(path)
        try:
            check_schema_version_compatible(checker_connection)  # must not raise
            # A read-only check must never itself create a write transaction.
            self.assertFalse(checker_connection.in_transaction)
        finally:
            checker_connection.close()
            os.remove(path)

    def test_H_simultaneous_migration_contention_is_bounded_and_schema_ends_correct(self) -> None:
        path = _temp_db_path()
        errors: list[BaseException] = []
        results: list[int] = []

        def open_and_migrate():
            try:
                store = RuntimeStateStore(path)  # default owns_migration=True -> retry_on_lock(migrate)
                results.append(store.status().schema_version)
                store.close()
            except BaseException as exc:  # noqa: BLE001 - captured for assertion, not swallowed
                errors.append(exc)

        threads = [threading.Thread(target=open_and_migrate) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertEqual(errors, [], f"no thread should raise an uncaught error under bounded retry: {errors}")
        self.assertTrue(all(version == SCHEMA_VERSION for version in results))

        # N: integrity intact after concurrent migration attempts.
        verify_connection = sqlite3.connect(path)
        try:
            quick_check = verify_connection.execute("PRAGMA quick_check").fetchone()[0]
            self.assertEqual(quick_check, "ok")
        finally:
            verify_connection.close()
            os.remove(path)

    def test_G_two_connections_contend_for_a_write_lock_boundedly(self) -> None:
        path = _temp_db_path()
        setup = sqlite3.connect(path)
        migrate(setup)
        setup.close()

        lock_acquired = threading.Event()

        def hold_then_release() -> None:
            # sqlite3 connections may only be used from the thread that
            # created them (check_same_thread default) - this holder
            # connection is created, used, and released entirely within
            # this one background thread.
            holder = sqlite3.connect(path, timeout=DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS)
            holder.execute(f"PRAGMA busy_timeout = {int(DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}")
            holder.execute("BEGIN IMMEDIATE")
            holder.execute("INSERT INTO schema_version(version) VALUES (?)", (999,))
            lock_acquired.set()
            time.sleep(0.3)
            holder.commit()
            holder.close()

        releaser = threading.Thread(target=hold_then_release)
        releaser.start()
        self.assertTrue(lock_acquired.wait(timeout=5), "holder thread must acquire the write lock before the waiter starts")

        waiter = sqlite3.connect(path, timeout=DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS)
        waiter.execute(f"PRAGMA busy_timeout = {int(DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}")
        started = time.monotonic()
        waiter.execute("INSERT INTO schema_version(version) VALUES (?)", (998,))
        waiter.commit()
        elapsed = time.monotonic() - started

        releaser.join(timeout=10)
        self.assertLess(elapsed, DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS, "the waiter must succeed once the holder releases, well within the busy timeout - bounded, not indefinite")

        waiter.close()
        os.remove(path)


class TelegramTelemetryLockIsolationTests(unittest.TestCase):
    """Sections 3/4/11 A-D: only genuine lock/busy contention on the
    NON-CRITICAL Telegram polling telemetry event is isolated; every other
    failure mode still propagates exactly as before this hotfix."""

    def _client(self):
        return _FakeTelegramClient(
            ({"update_id": 10, "message": {"message_id": 1, "chat": {"id": 100}, "from": {"id": 1}, "text": "/status"}},)
        )

    def test_A_telemetry_lock_error_is_isolated_tick_continues(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            worker = TelegramPollingWorker(_execute_telegram_config(), store, client_factory=lambda _: self._client())
            with patch.object(SQLiteEventStore, "append", side_effect=sqlite3.OperationalError("database is locked")):
                result = worker.tick()  # must NOT raise
            self.assertTrue(result.attempted)
            self.assertEqual(result.results[0].status, "sent", "the real Telegram processing work must have completed normally")
        finally:
            store.close()

    def test_A_telemetry_lock_error_is_observable_not_silent(self) -> None:
        from gaon.runtime.metrics import MetricsCollector

        store = RuntimeStateStore(":memory:")
        metrics = MetricsCollector()
        try:
            worker = TelegramPollingWorker(_execute_telegram_config(), store, client_factory=lambda _: self._client(), metrics=metrics)
            with patch.object(SQLiteEventStore, "append", side_effect=sqlite3.OperationalError("database is locked")):
                worker.tick()
            snapshot = metrics.snapshot()
            self.assertTrue(
                any(point.name == "telegram_telemetry_append_dropped" for point in snapshot.points),
                "a dropped telemetry event must be observable via metrics, never purely silent",
            )
        finally:
            store.close()

    def test_B_unexpected_operational_error_is_never_swallowed(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            worker = TelegramPollingWorker(_execute_telegram_config(), store, client_factory=lambda _: self._client())
            with patch.object(SQLiteEventStore, "append", side_effect=sqlite3.OperationalError("no such table: durable_events")):
                with self.assertRaises(sqlite3.OperationalError):
                    worker.tick()
        finally:
            store.close()

    def test_C_non_sqlite_unexpected_exception_is_never_swallowed(self) -> None:
        store = RuntimeStateStore(":memory:")
        try:
            worker = TelegramPollingWorker(_execute_telegram_config(), store, client_factory=lambda _: self._client())
            with patch.object(SQLiteEventStore, "append", side_effect=ValueError("programming error")):
                with self.assertRaises(ValueError):
                    worker.tick()
        finally:
            store.close()

    def test_D_critical_event_store_append_keeps_original_fail_semantics(self) -> None:
        """SQLiteEventStore.append() itself (used by Champion registry,
        trading execution, scheduler, daily research, etc. - genuinely
        critical event writes) is completely UNCHANGED by this hotfix; the
        isolation lives only inside TelegramPollingWorker._append_event.
        A failure on a critical append (here: a closed connection) must
        still raise, uncaught by anything this hotfix introduced."""
        from gaon.runtime.event_store import DurableEvent

        connection = sqlite3.connect(":memory:")
        migrate(connection)
        connection.close()

        event = DurableEvent(
            event_id="critical:1", event_type="CriticalStateEvent", occurred_at=_NOW, actor_ref="test",
            correlation_id="c", causation_id=None, scope="runtime", project="StrategyLab", strategy="N/A",
            market="N/A", payload={}, evidence_refs=(), audit_refs=(), appended_at=_NOW,
        )
        with self.assertRaises(sqlite3.ProgrammingError):
            SQLiteEventStore(connection).append(event)


if __name__ == "__main__":
    unittest.main()
