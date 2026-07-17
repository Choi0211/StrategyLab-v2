"""SQLite runtime schema migrations."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 5


def migrate(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    current = connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
    if current is None:
        _create_v1(connection)
        _upgrade_v1_to_v2(connection)
        _upgrade_v2_to_v3(connection)
        _upgrade_v3_to_v4(connection)
        _upgrade_v4_to_v5(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 1:
        _upgrade_v1_to_v2(connection)
        _upgrade_v2_to_v3(connection)
        _upgrade_v3_to_v4(connection)
        _upgrade_v4_to_v5(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 2:
        _upgrade_v2_to_v3(connection)
        _upgrade_v3_to_v4(connection)
        _upgrade_v4_to_v5(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 3:
        _upgrade_v3_to_v4(connection)
        _upgrade_v4_to_v5(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 4:
        _upgrade_v4_to_v5(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) != SCHEMA_VERSION:
        raise RuntimeError("unsupported runtime database schema version")
    connection.commit()


def _create_v1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS telegram_offsets (
            chat_id TEXT PRIMARY KEY,
            next_offset INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS processed_messages (
            message_id TEXT PRIMARY KEY,
            processed_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scheduler_jobs (
            job_id TEXT PRIMARY KEY,
            next_run_at TEXT NOT NULL,
            last_run_at TEXT
        );
        CREATE TABLE IF NOT EXISTS research_proposals (
            proposal_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS approvals (
            approval_id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            status TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_runs (
            run_id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS runtime_audit_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS notification_attempts (
            attempt_id TEXT PRIMARY KEY,
            target_ref TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )


def _upgrade_v1_to_v2(connection: sqlite3.Connection) -> None:
    _add_column(connection, "approvals", "requested_actor", "TEXT NOT NULL DEFAULT ''")
    _add_column(connection, "approvals", "requested_chat_id", "TEXT NOT NULL DEFAULT ''")
    _add_column(connection, "approvals", "token_digest", "TEXT NOT NULL DEFAULT ''")
    _add_column(connection, "approvals", "issued_at", "TEXT NOT NULL DEFAULT ''")
    _add_column(connection, "approvals", "nonce", "TEXT NOT NULL DEFAULT ''")
    _add_column(connection, "approvals", "consumed_by_run_id", "TEXT")
    _add_column(connection, "research_runs", "payload_json", "TEXT NOT NULL DEFAULT '{}'")
    _add_column(connection, "scheduler_jobs", "idempotency_key", "TEXT")
    _add_column(connection, "scheduler_jobs", "execution_status", "TEXT NOT NULL DEFAULT 'pending'")
    _add_column(connection, "notification_attempts", "payload_json", "TEXT NOT NULL DEFAULT '{}'")
    connection.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_approvals_proposal_status ON approvals(proposal_id, status);
        CREATE INDEX IF NOT EXISTS idx_research_runs_proposal_status ON research_runs(proposal_id, status);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduler_jobs_idempotency ON scheduler_jobs(idempotency_key) WHERE idempotency_key IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_notifications_target_status ON notification_attempts(target_ref, status);
        CREATE INDEX IF NOT EXISTS idx_runtime_audit_type_created ON runtime_audit_events(event_type, created_at);
        """
    )


def _upgrade_v2_to_v3(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS runtime_queue (
            item_id TEXT PRIMARY KEY,
            dedupe_key TEXT NOT NULL UNIQUE,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            priority INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            available_at TEXT NOT NULL,
            leased_until TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_runtime_queue_status_available ON runtime_queue(status, available_at, priority);
        CREATE INDEX IF NOT EXISTS idx_scheduler_jobs_status_next ON scheduler_jobs(execution_status, next_run_at);
        """
    )


def _upgrade_v3_to_v4(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS durable_events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            actor_ref TEXT NOT NULL,
            correlation_id TEXT NOT NULL,
            causation_id TEXT,
            scope TEXT NOT NULL,
            project TEXT NOT NULL,
            strategy TEXT NOT NULL,
            market TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL,
            audit_refs_json TEXT NOT NULL,
            appended_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_durable_events_order ON durable_events(occurred_at, event_id);
        CREATE TABLE IF NOT EXISTS replay_checkpoints (
            projection_id TEXT PRIMARY KEY,
            last_event_id TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS replay_failures (
            failure_id TEXT PRIMARY KEY,
            projection_id TEXT NOT NULL,
            event_id TEXT NOT NULL,
            error_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )


def _upgrade_v4_to_v5(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS long_term_memory (
            memory_id TEXT PRIMARY KEY,
            namespace TEXT NOT NULL,
            lifecycle TEXT NOT NULL,
            content TEXT NOT NULL,
            source_refs_json TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL,
            validation_ref TEXT,
            conflict_flag INTEGER NOT NULL DEFAULT 0,
            revalidation_flag INTEGER NOT NULL DEFAULT 0,
            retention_until TEXT,
            archived_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_long_memory_namespace_lifecycle ON long_term_memory(namespace, lifecycle);
        CREATE INDEX IF NOT EXISTS idx_long_memory_retention ON long_term_memory(retention_until);
        """
    )


def _add_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
