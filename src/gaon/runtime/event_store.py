"""Durable append-only event store and safe replay."""

from __future__ import annotations

from dataclasses import dataclass
import json
import sqlite3
from typing import Protocol

from gaon.runtime.serialization import dumps_json, loads_json

MAX_EVENT_PAYLOAD_BYTES = 32_768


@dataclass(frozen=True)
class DurableEvent:
    event_id: str
    event_type: str
    occurred_at: str
    actor_ref: str
    correlation_id: str
    causation_id: str | None
    scope: str
    project: str
    strategy: str
    market: str
    payload: dict[str, object]
    evidence_refs: tuple[str, ...]
    audit_refs: tuple[str, ...]
    appended_at: str


@dataclass(frozen=True)
class ReplayResult:
    processed: int
    failed: int
    dry_run: bool
    last_event_id: str | None


class EventProjection(Protocol):
    projection_id: str
    def apply(self, event: DurableEvent, *, dry_run: bool) -> None: ...


class SQLiteEventStore:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(self, event: DurableEvent) -> None:
        payload_json = dumps_json(event.payload)
        if len(payload_json.encode("utf-8")) > MAX_EVENT_PAYLOAD_BYTES:
            raise ValueError("event payload is too large")
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO durable_events(
                    event_id, event_type, occurred_at, actor_ref, correlation_id, causation_id,
                    scope, project, strategy, market, payload_json, evidence_refs_json, audit_refs_json, appended_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.event_type,
                    event.occurred_at,
                    event.actor_ref,
                    event.correlation_id,
                    event.causation_id,
                    event.scope,
                    event.project,
                    event.strategy,
                    event.market,
                    payload_json,
                    json.dumps(list(event.evidence_refs), sort_keys=True),
                    json.dumps(list(event.audit_refs), sort_keys=True),
                    event.appended_at,
                ),
            )

    def read_after(self, cursor_event_id: str | None = None, *, limit: int = 100) -> tuple[DurableEvent, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("replay batch size must be between 1 and 1000")
        if cursor_event_id is None:
            rows = self._connection.execute("SELECT * FROM durable_events ORDER BY occurred_at, event_id LIMIT ?", (limit,)).fetchall()
        else:
            cursor = self._connection.execute("SELECT occurred_at, event_id FROM durable_events WHERE event_id = ?", (cursor_event_id,)).fetchone()
            if cursor is None:
                raise KeyError(cursor_event_id)
            rows = self._connection.execute(
                "SELECT * FROM durable_events WHERE (occurred_at, event_id) > (?, ?) ORDER BY occurred_at, event_id LIMIT ?",
                (cursor[0], cursor[1], limit),
            ).fetchall()
        return tuple(_event_from_row(row) for row in rows)

    def checkpoint(self, projection_id: str) -> str | None:
        row = self._connection.execute("SELECT last_event_id FROM replay_checkpoints WHERE projection_id = ?", (projection_id,)).fetchone()
        return str(row[0]) if row and row[0] is not None else None

    def replay(self, projection: EventProjection, *, dry_run: bool = True, limit: int = 100, now: str = "2026-07-18T00:00:00Z") -> ReplayResult:
        cursor = self.checkpoint(projection.projection_id)
        events = self.read_after(cursor, limit=limit)
        processed = 0
        failed = 0
        last_event_id = cursor
        for event in events:
            try:
                projection.apply(event, dry_run=dry_run)
            except Exception as exc:  # noqa: BLE001 - projection failures are isolated.
                failed += 1
                failure_id = f"failure:{projection.projection_id}:{event.event_id}"
                with self._connection:
                    self._connection.execute(
                        "INSERT OR REPLACE INTO replay_failures(failure_id, projection_id, event_id, error_type, created_at) VALUES (?, ?, ?, ?, ?)",
                        (failure_id, projection.projection_id, event.event_id, exc.__class__.__name__, now),
                    )
                continue
            processed += 1
            last_event_id = event.event_id
            if not dry_run:
                with self._connection:
                    self._connection.execute(
                        "INSERT INTO replay_checkpoints(projection_id, last_event_id, updated_at) VALUES (?, ?, ?) "
                        "ON CONFLICT(projection_id) DO UPDATE SET last_event_id = excluded.last_event_id, updated_at = excluded.updated_at",
                        (projection.projection_id, event.event_id, now),
                    )
        return ReplayResult(processed, failed, dry_run, last_event_id)


def _event_from_row(row: tuple[object, ...]) -> DurableEvent:
    payload = loads_json(str(row[10]))
    evidence = _loads_tuple(str(row[11]))
    audit = _loads_tuple(str(row[12]))
    return DurableEvent(
        event_id=str(row[0]),
        event_type=str(row[1]),
        occurred_at=str(row[2]),
        actor_ref=str(row[3]),
        correlation_id=str(row[4]),
        causation_id=str(row[5]) if row[5] is not None else None,
        scope=str(row[6]),
        project=str(row[7]),
        strategy=str(row[8]),
        market=str(row[9]),
        payload=payload,
        evidence_refs=evidence,
        audit_refs=audit,
        appended_at=str(row[13]),
    )


def _loads_tuple(value: str) -> tuple[str, ...]:
    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("event refs must be string arrays")
    return tuple(loaded)
