"""Durable runtime state storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import sqlite3

from gaon.runtime.migrations import SCHEMA_VERSION, migrate
from gaon.runtime.repositories import SQLiteAuditEventRepository, SQLiteTelegramStateRepository
from gaon.runtime.serialization import loads_json


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
        self.telegram = SQLiteTelegramStateRepository(self._connection)
        self.audit = SQLiteAuditEventRepository(self._connection)

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
        shutil.copyfile(self.path, dest)
        return str(dest)
