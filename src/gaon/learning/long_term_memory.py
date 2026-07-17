"""Long-term memory foundation that extends Learning Memory without replacing it."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import json
import sqlite3


class MemoryNamespace(str, Enum):
    LEARNING = "learning"
    RESEARCH = "research"
    CONVERSATION = "conversation"
    SYSTEM = "system"


class MemoryLifecycle(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    REJECTED = "rejected"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class RetentionPolicy:
    retain_until: str | None
    archive_after_days: int | None = None


@dataclass(frozen=True)
class MemoryRecord:
    memory_id: str
    namespace: MemoryNamespace
    lifecycle: MemoryLifecycle
    content: str
    source_refs: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    created_at: str
    updated_at: str
    validation_ref: str | None = None
    conflict_flag: bool = False
    revalidation_flag: bool = False
    retention: RetentionPolicy = RetentionPolicy(None)
    archived_at: str | None = None

    @classmethod
    def propose(
        cls,
        memory_id: str,
        namespace: MemoryNamespace,
        content: str,
        *,
        source_refs: tuple[str, ...],
        evidence_refs: tuple[str, ...],
        created_at: str,
        retention: RetentionPolicy = RetentionPolicy(None),
        authorized_system_write: bool = False,
    ) -> "MemoryRecord":
        if namespace is MemoryNamespace.SYSTEM and not authorized_system_write:
            raise PermissionError("system memory requires stricter authorization")
        if not source_refs or not evidence_refs:
            raise ValueError("memory requires source and evidence references")
        if _contains_secret_marker(content):
            raise ValueError("memory content must not store secrets or raw credentials")
        return cls(memory_id, namespace, MemoryLifecycle.PROPOSED, content, source_refs, evidence_refs, created_at, created_at, retention=retention)

    def validate(self, *, validation_ref: str, trusted_workflow: bool, updated_at: str) -> "MemoryRecord":
        if not trusted_workflow:
            raise PermissionError("memory validation requires trusted workflow")
        if self.lifecycle is not MemoryLifecycle.PROPOSED:
            raise ValueError("only proposed memory can be validated")
        return replace(self, lifecycle=MemoryLifecycle.VALIDATED, validation_ref=validation_ref, updated_at=updated_at)

    def reject(self, *, updated_at: str) -> "MemoryRecord":
        if self.lifecycle is not MemoryLifecycle.PROPOSED:
            raise ValueError("only proposed memory can be rejected")
        return replace(self, lifecycle=MemoryLifecycle.REJECTED, updated_at=updated_at)

    def archive(self, *, archived_at: str) -> "MemoryRecord":
        if self.lifecycle is MemoryLifecycle.ARCHIVED:
            raise ValueError("memory is already archived")
        return replace(self, lifecycle=MemoryLifecycle.ARCHIVED, archived_at=archived_at, updated_at=archived_at)

    def mark_conflict(self, *, updated_at: str) -> "MemoryRecord":
        return replace(self, conflict_flag=True, updated_at=updated_at)

    def mark_revalidation(self, *, updated_at: str) -> "MemoryRecord":
        return replace(self, revalidation_flag=True, updated_at=updated_at)


class SQLiteLongTermMemoryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, record: MemoryRecord) -> None:
        if record.lifecycle is not MemoryLifecycle.PROPOSED:
            raise ValueError("new memory records must enter as proposed")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO long_term_memory(
                    memory_id, namespace, lifecycle, content, source_refs_json, evidence_refs_json,
                    validation_ref, conflict_flag, revalidation_flag, retention_until, archived_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _record_row(record),
            )

    def update(self, record: MemoryRecord) -> None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE long_term_memory
                   SET lifecycle = ?, validation_ref = ?, conflict_flag = ?, revalidation_flag = ?,
                       retention_until = ?, archived_at = ?, updated_at = ?
                 WHERE memory_id = ?
                """,
                (
                    record.lifecycle.value,
                    record.validation_ref,
                    int(record.conflict_flag),
                    int(record.revalidation_flag),
                    record.retention.retain_until,
                    record.archived_at,
                    record.updated_at,
                    record.memory_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError(record.memory_id)

    def get(self, memory_id: str) -> MemoryRecord:
        row = self._connection.execute("SELECT * FROM long_term_memory WHERE memory_id = ?", (memory_id,)).fetchone()
        if row is None:
            raise KeyError(memory_id)
        return _record_from_row(row)

    def list_by_namespace(self, namespace: MemoryNamespace) -> tuple[MemoryRecord, ...]:
        rows = self._connection.execute(
            "SELECT * FROM long_term_memory WHERE namespace = ? ORDER BY created_at, memory_id",
            (namespace.value,),
        ).fetchall()
        return tuple(_record_from_row(row) for row in rows)

    def retrieve_context(self, namespace: MemoryNamespace, query: str, *, limit: int = 5) -> tuple[MemoryRecord, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM long_term_memory
             WHERE namespace = ? AND lifecycle IN (?, ?) AND content LIKE ?
             ORDER BY lifecycle DESC, updated_at DESC, memory_id
             LIMIT ?
            """,
            (namespace.value, MemoryLifecycle.PROPOSED.value, MemoryLifecycle.VALIDATED.value, f"%{query}%", limit),
        ).fetchall()
        return tuple(_record_from_row(row) for row in rows)


def _record_row(record: MemoryRecord) -> tuple[object, ...]:
    return (
        record.memory_id,
        record.namespace.value,
        record.lifecycle.value,
        record.content,
        json.dumps(list(record.source_refs), sort_keys=True),
        json.dumps(list(record.evidence_refs), sort_keys=True),
        record.validation_ref,
        int(record.conflict_flag),
        int(record.revalidation_flag),
        record.retention.retain_until,
        record.archived_at,
        record.created_at,
        record.updated_at,
    )


def _record_from_row(row: tuple[object, ...]) -> MemoryRecord:
    return MemoryRecord(
        memory_id=str(row[0]),
        namespace=MemoryNamespace(str(row[1])),
        lifecycle=MemoryLifecycle(str(row[2])),
        content=str(row[3]),
        source_refs=tuple(json.loads(str(row[4]))),
        evidence_refs=tuple(json.loads(str(row[5]))),
        validation_ref=str(row[6]) if row[6] is not None else None,
        conflict_flag=bool(row[7]),
        revalidation_flag=bool(row[8]),
        retention=RetentionPolicy(str(row[9]) if row[9] is not None else None),
        archived_at=str(row[10]) if row[10] is not None else None,
        created_at=str(row[11]),
        updated_at=str(row[12]),
    )


def _contains_secret_marker(content: str) -> bool:
    lowered = content.lower()
    return any(marker in lowered for marker in ("api_key=", "token=", "password=", "secret="))
