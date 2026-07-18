"""SQLite runtime schema migrations."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 13


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
        _upgrade_v5_to_v6(connection)
        _upgrade_v6_to_v7(connection)
        _upgrade_v7_to_v8(connection)
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 1:
        _upgrade_v1_to_v2(connection)
        _upgrade_v2_to_v3(connection)
        _upgrade_v3_to_v4(connection)
        _upgrade_v4_to_v5(connection)
        _upgrade_v5_to_v6(connection)
        _upgrade_v6_to_v7(connection)
        _upgrade_v7_to_v8(connection)
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 2:
        _upgrade_v2_to_v3(connection)
        _upgrade_v3_to_v4(connection)
        _upgrade_v4_to_v5(connection)
        _upgrade_v5_to_v6(connection)
        _upgrade_v6_to_v7(connection)
        _upgrade_v7_to_v8(connection)
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 3:
        _upgrade_v3_to_v4(connection)
        _upgrade_v4_to_v5(connection)
        _upgrade_v5_to_v6(connection)
        _upgrade_v6_to_v7(connection)
        _upgrade_v7_to_v8(connection)
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 4:
        _upgrade_v4_to_v5(connection)
        _upgrade_v5_to_v6(connection)
        _upgrade_v6_to_v7(connection)
        _upgrade_v7_to_v8(connection)
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 5:
        _upgrade_v5_to_v6(connection)
        _upgrade_v6_to_v7(connection)
        _upgrade_v7_to_v8(connection)
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 6:
        _upgrade_v6_to_v7(connection)
        _upgrade_v7_to_v8(connection)
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 7:
        _upgrade_v7_to_v8(connection)
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 8:
        _upgrade_v8_to_v9(connection)
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 9:
        _upgrade_v9_to_v10(connection)
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 10:
        _upgrade_v10_to_v11(connection)
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 11:
        _upgrade_v11_to_v12(connection)
        _upgrade_v12_to_v13(connection)
        connection.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(current[0]) == 12:
        _upgrade_v12_to_v13(connection)
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


def _upgrade_v5_to_v6(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_proposals (
            proposal_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            proposal_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence REAL NOT NULL,
            claims_json TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL,
            provenance_json TEXT NOT NULL,
            review_after TEXT,
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_proposal_hash_version ON knowledge_proposals(proposal_hash, version);
        CREATE TABLE IF NOT EXISTS trusted_knowledge (
            knowledge_id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            proposal_hash TEXT NOT NULL,
            approved_at TEXT NOT NULL,
            claims_json TEXT NOT NULL,
            evidence_refs_json TEXT NOT NULL
        );
        """
    )


def _upgrade_v6_to_v7(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_approval_decisions (
            decision_id TEXT PRIMARY KEY,
            proposal_id TEXT NOT NULL,
            proposal_hash TEXT NOT NULL,
            proposal_version INTEGER NOT NULL,
            actor_ref TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            decided_at TEXT NOT NULL,
            consumed INTEGER NOT NULL DEFAULT 0
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_research_approval_idempotency
            ON research_approval_decisions(proposal_id, proposal_hash, proposal_version, actor_ref, decision);
        """
    )


def _upgrade_v7_to_v8(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_brain_runs (
            run_id TEXT PRIMARY KEY,
            query TEXT NOT NULL,
            status TEXT NOT NULL,
            plan_hash TEXT,
            report_json TEXT,
            failure_reason TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS research_brain_checkpoints (
            run_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            checkpoint_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_research_brain_runs_status ON research_brain_runs(status, updated_at);
        """
    )


def _upgrade_v8_to_v9(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS scheduled_automation_jobs (
            job_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            request_text TEXT NOT NULL,
            schedule_json TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            approval_required INTEGER NOT NULL,
            agent_selection TEXT,
            tools_json TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            next_run_at TEXT NOT NULL,
            max_attempts INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_scheduled_automation_due
            ON scheduled_automation_jobs(enabled, next_run_at, job_id);
        CREATE TABLE IF NOT EXISTS scheduled_automation_runs (
            run_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            status TEXT NOT NULL,
            attempt INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            result_json TEXT NOT NULL,
            error TEXT,
            UNIQUE(job_id, started_at)
        );
        CREATE INDEX IF NOT EXISTS idx_scheduled_automation_runs_job
            ON scheduled_automation_runs(job_id, started_at);
        """
    )


def _upgrade_v9_to_v10(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS daily_research_profiles (
            profile_id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            query TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            priority INTEGER NOT NULL,
            source_preferences_json TEXT NOT NULL,
            time_range TEXT NOT NULL,
            language TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_daily_research_profiles_enabled_priority
            ON daily_research_profiles(enabled, priority, profile_id);
        CREATE TABLE IF NOT EXISTS daily_research_runs (
            run_id TEXT PRIMARY KEY,
            profile_id TEXT NOT NULL,
            status TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            report_json TEXT NOT NULL,
            proposal_ids_json TEXT NOT NULL,
            error TEXT,
            UNIQUE(profile_id, started_at)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_research_runs_profile
            ON daily_research_runs(profile_id, started_at);
        """
    )


def _upgrade_v10_to_v11(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS trading_requests (
            request_id TEXT PRIMARY KEY,
            intent TEXT NOT NULL,
            symbol TEXT NOT NULL,
            side TEXT,
            quantity REAL NOT NULL,
            order_type TEXT NOT NULL,
            limit_price REAL,
            actor_ref TEXT NOT NULL,
            created_at TEXT NOT NULL,
            simulation INTEGER NOT NULL,
            approval_ref TEXT,
            idempotency_key TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_trading_requests_idempotency
            ON trading_requests(idempotency_key) WHERE idempotency_key IS NOT NULL;
        CREATE TABLE IF NOT EXISTS trading_results (
            result_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            status TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_trading_results_request
            ON trading_results(request_id, created_at);
        """
    )


def _upgrade_v11_to_v12(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS backtest_requests (
            request_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            strategy_id TEXT NOT NULL,
            dataset_id TEXT NOT NULL,
            period_start TEXT NOT NULL,
            period_end TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_requests_fingerprint
            ON backtest_requests(fingerprint);
        CREATE TABLE IF NOT EXISTS backtest_results (
            result_id TEXT PRIMARY KEY,
            request_id TEXT NOT NULL,
            status TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            generated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_backtest_results_request
            ON backtest_results(request_id, generated_at);
        """
    )


def _upgrade_v12_to_v13(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS validation_requests (
            validation_id TEXT PRIMARY KEY,
            policy_version TEXT NOT NULL,
            backtest_result_ids_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            requested_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS validation_reports (
            validation_id TEXT PRIMARY KEY,
            backtest_run_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            status TEXT NOT NULL,
            score INTEGER NOT NULL,
            policy_version TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            generated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_validation_reports_fingerprint
            ON validation_reports(fingerprint, generated_at);
        CREATE INDEX IF NOT EXISTS idx_validation_reports_status
            ON validation_reports(status, generated_at);
        """
    )


def _add_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
