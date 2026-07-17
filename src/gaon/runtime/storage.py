"""Durable runtime state storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3

from gaon.runtime.migrations import SCHEMA_VERSION, migrate


@dataclass(frozen=True)
class RuntimeDatabaseStatus:
    path: str
    schema_version: int
    ready: bool


class RuntimeStateStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self._connection = sqlite3.connect(path)
        migrate(self._connection)

    def close(self) -> None:
        self._connection.close()

    def status(self) -> RuntimeDatabaseStatus:
        version = self._connection.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone()
        return RuntimeDatabaseStatus(self.path, int(version[0]), int(version[0]) == SCHEMA_VERSION)

    def get_offset(self, chat_id: str) -> int | None:
        row = self._connection.execute("SELECT next_offset FROM telegram_offsets WHERE chat_id = ?", (chat_id,)).fetchone()
        return int(row[0]) if row else None

    def save_offset(self, chat_id: str, next_offset: int, updated_at: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO telegram_offsets(chat_id, next_offset, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET next_offset = excluded.next_offset, updated_at = excluded.updated_at",
                (chat_id, next_offset, updated_at),
            )

    def mark_processed(self, message_id: str, processed_at: str) -> bool:
        try:
            with self._connection:
                self._connection.execute("INSERT INTO processed_messages(message_id, processed_at) VALUES (?, ?)", (message_id, processed_at))
            return True
        except sqlite3.IntegrityError:
            return False

    def append_audit(self, event_id: str, event_type: str, payload_json: str, created_at: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO runtime_audit_events(event_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (event_id, event_type, payload_json, created_at),
            )

    def list_audit(self) -> tuple[str, ...]:
        rows = self._connection.execute("SELECT event_id FROM runtime_audit_events ORDER BY created_at, event_id").fetchall()
        return tuple(str(row[0]) for row in rows)

    def backup(self, destination: str) -> str:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._connection.commit()
        shutil.copyfile(self.path, dest)
        return str(dest)
