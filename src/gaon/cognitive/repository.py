"""SQLite persistence for additive Cognitive Core records."""

from __future__ import annotations

import sqlite3
import json

from gaon.cognitive.models import CognitiveRecord, CognitiveRecordType
from gaon.runtime.serialization import dumps_json, loads_json


class SQLiteCognitiveRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def put(self, record: CognitiveRecord) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO cognitive_records(
                    record_id, record_type, namespace, title, status, payload_json,
                    source_refs_json, evidence_refs_json, confidence,
                    verification_state, related_goal, supersedes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    title=excluded.title, status=excluded.status,
                    payload_json=excluded.payload_json,
                    source_refs_json=excluded.source_refs_json,
                    evidence_refs_json=excluded.evidence_refs_json,
                    confidence=excluded.confidence,
                    verification_state=excluded.verification_state,
                    related_goal=excluded.related_goal,
                    supersedes=excluded.supersedes,
                    updated_at=excluded.updated_at
                WHERE cognitive_records.namespace=excluded.namespace
                  AND cognitive_records.record_type=excluded.record_type
                """,
                _row(record),
            )
            if self._connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise ValueError("cognitive identity belongs to another namespace/type")

    def get(self, record_id: str) -> CognitiveRecord:
        row = self._connection.execute(
            "SELECT * FROM cognitive_records WHERE record_id = ?", (record_id,)
        ).fetchone()
        if row is None:
            raise KeyError(record_id)
        return _from_row(row)

    def list(
        self,
        *,
        namespace: str,
        record_type: CognitiveRecordType | None = None,
        statuses: tuple[str, ...] = (),
        limit: int = 20,
    ) -> tuple[CognitiveRecord, ...]:
        if limit <= 0:
            return ()
        clauses = ["namespace = ?"]
        values: list[object] = [namespace]
        if record_type is not None:
            clauses.append("record_type = ?")
            values.append(record_type.value)
        if statuses:
            clauses.append("status IN (" + ",".join("?" for _ in statuses) + ")")
            values.extend(statuses)
        values.append(max(1, min(limit, 100)))
        rows = self._connection.execute(
            "SELECT * FROM cognitive_records WHERE " + " AND ".join(clauses)
            + " ORDER BY updated_at DESC, record_id LIMIT ?",
            tuple(values),
        ).fetchall()
        return tuple(_from_row(row) for row in rows)


def _row(record: CognitiveRecord) -> tuple[object, ...]:
    return (
        record.record_id,
        record.record_type.value,
        record.namespace,
        record.title,
        record.status,
        dumps_json(record.payload),
        dumps_json(list(record.source_refs)),
        dumps_json(list(record.evidence_refs)),
        record.confidence,
        record.verification_state,
        record.related_goal,
        record.supersedes,
        record.created_at,
        record.updated_at,
    )


def _from_row(row: tuple[object, ...]) -> CognitiveRecord:
    return CognitiveRecord(
        record_id=str(row[0]),
        record_type=CognitiveRecordType(str(row[1])),
        namespace=str(row[2]),
        title=str(row[3]),
        status=str(row[4]),
        payload=dict(loads_json(str(row[5]))),
        source_refs=tuple(json.loads(str(row[6]))),
        evidence_refs=tuple(json.loads(str(row[7]))),
        confidence=float(row[8]),
        verification_state=str(row[9]),
        related_goal=str(row[10]) if row[10] is not None else None,
        supersedes=str(row[11]) if row[11] is not None else None,
        created_at=str(row[12]),
        updated_at=str(row[13]),
    )
