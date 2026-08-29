"""Durable runtime state storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import os

from gaon.runtime.migrations import SCHEMA_VERSION, check_schema_version_compatible, migrate
from gaon.runtime.conversation_context import SQLiteConversationSummaryRepository
from gaon.runtime.llm_conversation import SQLiteConversationRepository, SQLiteConversationToolResultRepository
from gaon.runtime.llm_tools import SQLiteToolAuditRepository
from gaon.runtime.telegram_agent import SQLiteTelegramConversationLinkRepository
from gaon.runtime.agent_planner import SQLiteAgentPlanRepository
from gaon.runtime.repositories import SQLiteAuditEventRepository, SQLiteTelegramStateRepository
from gaon.runtime.serialization import loads_json
from gaon.runtime.sqlite_lock import DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS, retry_on_lock


@dataclass(frozen=True)
class RuntimeDatabaseStatus:
    path: str
    schema_version: int
    ready: bool


class RuntimeStateStore:
    def __init__(self, path: str, *, owns_migration: bool = True) -> None:
        """``owns_migration=True`` (default, preserves prior behavior for
        every existing caller): this process is the schema migration
        owner - ``migrate()`` runs, retried with bounded backoff if it
        hits lock contention from a concurrent migration attempt (Section:
        Migration Ownership), and fails closed (the lock error propagates)
        if contention never clears within the retry budget.

        ``owns_migration=False`` (used by ``gaon-web-serve`` only): this
        process is NOT the migration owner - it never writes to the
        schema, only performs a read-only version check
        (``check_schema_version_compatible``) and fails closed
        (``SchemaVersionMismatchError``) if the schema is missing, older,
        or newer than expected, rather than starting against a
        potentially-stale or in-progress schema."""
        self.path = path
        self._connection = sqlite3.connect(path, timeout=DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS)
        try:
            self._connection.execute(f"PRAGMA busy_timeout = {int(DEFAULT_SQLITE_BUSY_TIMEOUT_SECONDS * 1000)}")
            if owns_migration:
                retry_on_lock(lambda: migrate(self._connection))
            else:
                check_schema_version_compatible(self._connection)
        except BaseException:
            # Never leak an open file handle when construction fails
            # (fail-closed schema mismatch, or a lock error exhausting the
            # retry budget) - the caller never gets a RuntimeStateStore
            # back to call .close() on.
            self._connection.close()
            raise
        self.telegram = SQLiteTelegramStateRepository(self._connection)
        self.audit = SQLiteAuditEventRepository(self._connection)
        self.conversations = SQLiteConversationRepository(self._connection)
        self.conversation_summaries = SQLiteConversationSummaryRepository(self._connection)
        self.tool_audit = SQLiteToolAuditRepository(self._connection)
        self.conversation_tool_results = SQLiteConversationToolResultRepository(self._connection)
        self.telegram_conversations = SQLiteTelegramConversationLinkRepository(self._connection)
        self.agent_plans = SQLiteAgentPlanRepository(self._connection)

    def close(self) -> None:
        self._connection.close()

    def status(self) -> RuntimeDatabaseStatus:
        version = self._connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        return RuntimeDatabaseStatus(self.path, int(version[0]), int(version[0]) == SCHEMA_VERSION)

    def get_offset(self, chat_id: str) -> int | None:
        return self.telegram.get_offset(chat_id)

    def save_offset(self, chat_id: str, next_offset: int, updated_at: str) -> None:
        self.telegram.save_offset(chat_id, next_offset, updated_at)

    def mark_processed(self, message_id: str, processed_at: str) -> bool:
        return self.telegram.mark_processed(message_id, processed_at)

    def append_audit(self, event_id: str, event_type: str, payload_json: str, created_at: str) -> None:
        self.audit.append(event_id, event_type, loads_json(payload_json), created_at)

    def list_audit(self) -> tuple[str, ...]:
        return self.audit.list_ids()

    def backup(self, destination: str) -> str:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._connection.commit()
        tmp = dest.with_name(f".{dest.name}.tmp")
        if tmp.exists():
            tmp.unlink()
        target = sqlite3.connect(str(tmp))
        try:
            self._connection.backup(target)
            target.commit()
        finally:
            target.close()
        restored = sqlite3.connect(str(tmp))
        try:
            migrate(restored)
        finally:
            restored.close()
        os.replace(tmp, dest)
        return str(dest)
