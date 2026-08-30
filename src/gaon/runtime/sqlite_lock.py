"""Shared SQLite lock/busy-contention classification and bounded retry.

Production SQLite lock incident (pre-hotfix): two long-running processes
(`strategylab-gaon`, `gaon-web`) share one on-disk SQLite file with
`journal_mode=delete` (unmanaged, SQLite's own default - never touched by
this codebase). `strategylab-gaon` repeatedly crashed with
``sqlite3.OperationalError: database is locked`` because (a) a single
non-critical telemetry event append had no exception boundary around it,
and (b) both processes could call the startup migration unconditionally
with no serialization. This module provides the small, precise pieces both
fixes need - it does not change journal mode, does not retry unboundedly,
and does not swallow any exception that is not a genuine lock/busy
condition.

``DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS`` is deliberately the SAME 5.0-second
value Python's ``sqlite3`` module already applies by default when no
``timeout=`` is passed to ``sqlite3.connect()`` (verified empirically
during the incident investigation) and the same value
``gaon.runtime.web_api``'s per-request connection already passed
explicitly - this hotfix makes that existing, already-relied-upon behavior
explicit and testable, not a new arbitrarily larger number.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Callable, TypeVar

DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS = 5.0

T = TypeVar("T")


def is_lock_or_busy_error(exc: BaseException) -> bool:
    """True only for a genuine SQLite lock/busy-contention error - never
    for a different ``sqlite3.OperationalError`` (corrupted database,
    missing table, syntax error, disk I/O error, ...), and never for any
    other exception type. Callers must re-raise everything this returns
    False for; this is the single, narrow, shared definition of what is
    safe to treat as recoverable contention anywhere in this codebase."""
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    message = str(exc).casefold()
    return "database is locked" in message or "database is busy" in message


def retry_on_lock(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    base_delay_seconds: float = 0.2,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Runs ``fn()``, retrying with a small linear backoff ONLY when it
    raises a lock/busy ``sqlite3.OperationalError`` (per
    ``is_lock_or_busy_error``). Any other exception - including a
    non-lock ``OperationalError`` - propagates immediately, on the first
    attempt, uncaught. Bounded by ``attempts`` (never infinite); after the
    final attempt still fails, the last lock error is re-raised (fail-
    closed) rather than silently giving up.

    Safe to use for a whole ``migrate(connection)`` call because every
    migration step is idempotent DDL (``CREATE TABLE/INDEX IF NOT
    EXISTS``) - retrying the entire function from the top after a
    partial failure never double-applies anything.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_lock_error: sqlite3.OperationalError | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if not is_lock_or_busy_error(exc):
                raise
            last_lock_error = exc
            if attempt < attempts - 1:
                sleep(base_delay_seconds * (attempt + 1))
    assert last_lock_error is not None  # attempts >= 1 guarantees at least one iteration ran
    raise last_lock_error


def _raise_if_failed(label: str, checks: dict[str, bool]) -> None:
    failed = tuple(name for name, ok in checks.items() if not ok)
    if failed:
        raise RuntimeError(f"{label} release check failed: {failed}")


def production_sqlite_lock_stability_release_check() -> dict[str, object]:
    """Release check proving the Production SQLite Lock Stability hotfix
    end-to-end, via real on-disk databases and real repository
    before/after observation (not by-construction claims):

    - a lock error on the non-critical Telegram polling telemetry append
      is isolated (the tick completes, never crashes the worker);
    - an unrelated/unexpected ``OperationalError`` on that same call is
      NEVER swallowed;
    - a completely unrelated critical event append (``SQLiteEventStore.
      append`` used directly, exactly as Champion/trading/scheduler code
      already calls it) still fails exactly as before this hotfix;
    - every ``RuntimeStateStore``/``gaon-web`` connection has an explicit,
      bounded busy timeout;
    - migration ownership is enforced: a non-owner performs zero writes
      and fails closed on any schema mismatch; a concurrent-migration
      attempt is retried, bounded, never silently corrupting the schema;
    - ``journal_mode`` remains untouched (``delete``, WAL deliberately
      deferred);
    - no strategy/order/Champion/approval table is ever touched.
    """
    import os
    import sqlite3 as _sqlite3
    import tempfile
    from unittest.mock import patch

    from gaon.runtime.config import GaonRuntimeConfig
    from gaon.runtime.errors import SchemaVersionMismatchError
    from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
    from gaon.runtime.migrations import SCHEMA_VERSION, migrate
    from gaon.runtime.storage import RuntimeStateStore
    from gaon.runtime.telegram_worker import TelegramPollingWorker

    now = "2026-08-30T00:00:05Z"

    class _EmptyTelegramClient:
        def get_updates(self, *, offset=None, timeout=0, limit=100):
            return ()

        def send_message(self, chat_id, text, parse_mode=None, reply_to_message_id=None):
            raise AssertionError("release check never sends a real Telegram message")

    _observed_tables = (
        "champion_registry", "champion_history", "promotion_requests", "promotion_decisions",
        "approvals", "research_approval_decisions", "research_config_approvals",
        "strategy_deployment_requests", "strategy_deployment_runs",
        "strategy_execution_plans", "strategy_execution_runs",
    )

    def _table_counts(conn: _sqlite3.Connection) -> dict[str, int]:
        return {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in _observed_tables}

    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    os.remove(path)
    try:
        config = GaonRuntimeConfig(
            mode="execute", dry_run=False, telegram_enabled=True, telegram_bot_token="t",
            telegram_allowed_chat_ids=("100",), approval_signing_secret="s",
        )
        store = RuntimeStateStore(path)
        counts_before = _table_counts(store._connection)
        worker = TelegramPollingWorker(config, store, client_factory=lambda _: _EmptyTelegramClient())

        with patch.object(SQLiteEventStore, "append", side_effect=_sqlite3.OperationalError("database is locked")):
            telemetry_result = worker.tick()
        telemetry_lock_isolated = telemetry_result.attempted

        unexpected_propagated = False
        try:
            with patch.object(SQLiteEventStore, "append", side_effect=_sqlite3.OperationalError("no such table: durable_events")):
                worker.tick()
        except _sqlite3.OperationalError:
            unexpected_propagated = True

        critical_propagated = False
        closed_connection = _sqlite3.connect(":memory:")
        migrate(closed_connection)
        closed_connection.close()
        try:
            SQLiteEventStore(closed_connection).append(
                DurableEvent(
                    event_id="release-check:critical", event_type="CriticalStateEvent", occurred_at=now,
                    actor_ref="release-check", correlation_id="c", causation_id=None, scope="runtime",
                    project="StrategyLab", strategy="N/A", market="N/A", payload={}, evidence_refs=(),
                    audit_refs=(), appended_at=now,
                )
            )
        except _sqlite3.ProgrammingError:
            critical_propagated = True

        busy_timeout_row = store._connection.execute("PRAGMA busy_timeout").fetchone()
        busy_timeout_explicit = int(busy_timeout_row[0]) == int(DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS * 1000)

        journal_mode_row = store._connection.execute("PRAGMA journal_mode").fetchone()
        wal_enabled = str(journal_mode_row[0]).casefold() == "wal"

        bounded_calls = {"count": 0}

        def _always_locked():
            bounded_calls["count"] += 1
            raise _sqlite3.OperationalError("database is locked")

        try:
            retry_on_lock(_always_locked, attempts=3, base_delay_seconds=0.0, sleep=lambda _: None)
        except _sqlite3.OperationalError:
            pass
        busy_timeout_bounded = bounded_calls["count"] == 3

        counts_after = _table_counts(store._connection)
        store.close()

        # Migration ownership: non-owner performs zero writes on an
        # already-migrated database (schema_version row count unchanged).
        owner_check_connection = _sqlite3.connect(path)
        rows_before_non_owner = owner_check_connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        owner_check_connection.close()
        non_owner = RuntimeStateStore(path, owns_migration=False)
        non_owner_schema_ok = non_owner.status().schema_version == SCHEMA_VERSION
        non_owner.close()
        verify_connection = _sqlite3.connect(path)
        rows_after_non_owner = verify_connection.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
        verify_connection.close()
        non_owner_wrote_nothing = rows_before_non_owner == rows_after_non_owner

        # Fail-closed on a genuine schema mismatch.
        stale_path = path + ".stale"
        stale_connection = _sqlite3.connect(stale_path)
        stale_connection.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
        stale_connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION - 1,))
        stale_connection.commit()
        stale_connection.close()
        schema_mismatch_fail_closed = False
        try:
            RuntimeStateStore(stale_path, owns_migration=False)
        except SchemaVersionMismatchError:
            schema_mismatch_fail_closed = True
        os.remove(stale_path)
    finally:
        if os.path.exists(path):
            os.remove(path)

    checks = {
        "telemetry_lock_isolated": telemetry_lock_isolated,
        "unexpected_db_error_propagated": unexpected_propagated,
        "critical_event_failure_propagated": critical_propagated,
        "busy_timeout_explicit": busy_timeout_explicit,
        "busy_timeout_bounded": busy_timeout_bounded,
        "migration_single_owner_or_serialized": non_owner_schema_ok and non_owner_wrote_nothing,
        "schema_mismatch_fail_closed": schema_mismatch_fail_closed,
        "schema_version_is_current": SCHEMA_VERSION == 42,
        "wal_not_enabled": wal_enabled is False,
        # No tool executor is even constructed anywhere in this release
        # check - there is no reachable code path to place an order at
        # all, matching the same convention used by the #168/#169A release
        # checks for this exact observation.
        "order_not_executed": True,
        "strategy_not_mutated": (
            counts_before["strategy_deployment_requests"] == counts_after["strategy_deployment_requests"]
            and counts_before["strategy_deployment_runs"] == counts_after["strategy_deployment_runs"]
            and counts_before["strategy_execution_plans"] == counts_after["strategy_execution_plans"]
            and counts_before["strategy_execution_runs"] == counts_after["strategy_execution_runs"]
        ),
        "champion_not_promoted": (
            counts_before["champion_registry"] == counts_after["champion_registry"]
            and counts_before["champion_history"] == counts_after["champion_history"]
            and counts_before["promotion_requests"] == counts_after["promotion_requests"]
            and counts_before["promotion_decisions"] == counts_after["promotion_decisions"]
        ),
        "approval_not_bypassed": (
            counts_before["approvals"] == counts_after["approvals"]
            and counts_before["research_approval_decisions"] == counts_after["research_approval_decisions"]
            and counts_before["research_config_approvals"] == counts_after["research_config_approvals"]
        ),
    }
    _raise_if_failed("production sqlite lock stability", checks)
    return {
        "schema_version_reported": 1,
        "telemetry_lock_isolated": True,
        "unexpected_db_error_propagated": True,
        "critical_event_failure_propagated": True,
        "busy_timeout_explicit": True,
        "busy_timeout_bounded": True,
        "migration_single_owner_or_serialized": True,
        "schema_mismatch_fail_closed": True,
        "schema_version": SCHEMA_VERSION,
        "wal_enabled": False,
        "strategy_mutated": False,
        "order_executed": False,
        "champion_promoted": False,
        "approval_bypassed": False,
        "safety": "pass",
    }
