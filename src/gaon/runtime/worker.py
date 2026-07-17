"""Bounded runtime worker helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import sqlite3

from gaon.runtime.serialization import dumps_json, loads_json


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt < 1:
            raise ValueError("attempt must be positive")
        return min(self.base_delay_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)


class QueueItemStatus(str, Enum):
    PENDING = "pending"
    LEASED = "leased"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class DurableQueueItem:
    item_id: str
    dedupe_key: str
    payload: dict[str, object]
    status: QueueItemStatus
    priority: int
    attempts: int
    max_attempts: int
    available_at: str
    leased_until: str | None
    created_at: str
    updated_at: str
    last_error: str | None = None


class DurableTaskQueue:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def enqueue(self, item_id: str, dedupe_key: str, payload: dict[str, object], *, priority: int, available_at: str, max_attempts: int = 3) -> bool:
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO runtime_queue(
                        item_id, dedupe_key, payload_json, status, priority, attempts, max_attempts,
                        available_at, leased_until, last_error, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, ?, ?)
                    """,
                    (item_id, dedupe_key, dumps_json(payload), QueueItemStatus.PENDING.value, priority, max_attempts, available_at, available_at, available_at),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def lease_next(self, *, now: str, leased_until: str) -> DurableQueueItem | None:
        with self._connection:
            row = self._connection.execute(
                """
                SELECT item_id FROM runtime_queue
                 WHERE status = ? AND available_at <= ?
                 ORDER BY priority DESC, available_at ASC, item_id ASC
                 LIMIT 1
                """,
                (QueueItemStatus.PENDING.value, now),
            ).fetchone()
            if row is None:
                return None
            item_id = str(row[0])
            self._connection.execute(
                "UPDATE runtime_queue SET status = ?, leased_until = ?, updated_at = ? WHERE item_id = ? AND status = ?",
                (QueueItemStatus.LEASED.value, leased_until, now, item_id, QueueItemStatus.PENDING.value),
            )
        return self.get(item_id)

    def mark_running(self, item_id: str, *, now: str) -> DurableQueueItem:
        return self._transition(item_id, QueueItemStatus.LEASED, QueueItemStatus.RUNNING, now=now)

    def mark_succeeded(self, item_id: str, *, now: str) -> DurableQueueItem:
        return self._transition(item_id, QueueItemStatus.RUNNING, QueueItemStatus.SUCCEEDED, now=now)

    def mark_cancelled(self, item_id: str, *, now: str) -> DurableQueueItem:
        with self._connection:
            self._connection.execute(
                "UPDATE runtime_queue SET status = ?, updated_at = ? WHERE item_id = ? AND status NOT IN (?, ?, ?)",
                (QueueItemStatus.CANCELLED.value, now, item_id, QueueItemStatus.SUCCEEDED.value, QueueItemStatus.FAILED.value, QueueItemStatus.CANCELLED.value),
            )
        return self.get(item_id)

    def mark_failed(self, item_id: str, *, now: str, retry_at: str, error: str) -> DurableQueueItem:
        item = self.get(item_id)
        next_attempts = item.attempts + 1
        status = QueueItemStatus.FAILED if next_attempts >= item.max_attempts else QueueItemStatus.PENDING
        with self._connection:
            self._connection.execute(
                "UPDATE runtime_queue SET status = ?, attempts = ?, available_at = ?, leased_until = NULL, last_error = ?, updated_at = ? WHERE item_id = ?",
                (status.value, next_attempts, retry_at, error, now, item_id),
            )
        return self.get(item_id)

    def recover_stale(self, *, now: str) -> int:
        with self._connection:
            leased = self._connection.execute(
                "UPDATE runtime_queue SET status = ?, leased_until = NULL, updated_at = ? WHERE status = ? AND leased_until IS NOT NULL AND leased_until <= ?",
                (QueueItemStatus.PENDING.value, now, QueueItemStatus.LEASED.value, now),
            ).rowcount
            running = self._connection.execute(
                "UPDATE runtime_queue SET status = ?, updated_at = ? WHERE status = ?",
                (QueueItemStatus.PENDING.value, now, QueueItemStatus.RUNNING.value),
            ).rowcount
        return int(leased + running)

    def get(self, item_id: str) -> DurableQueueItem:
        row = self._connection.execute(
            """
            SELECT item_id, dedupe_key, payload_json, status, priority, attempts, max_attempts,
                   available_at, leased_until, created_at, updated_at, last_error
              FROM runtime_queue WHERE item_id = ?
            """,
            (item_id,),
        ).fetchone()
        if row is None:
            raise KeyError(item_id)
        return DurableQueueItem(
            item_id=str(row[0]),
            dedupe_key=str(row[1]),
            payload=loads_json(str(row[2])),
            status=QueueItemStatus(str(row[3])),
            priority=int(row[4]),
            attempts=int(row[5]),
            max_attempts=int(row[6]),
            available_at=str(row[7]),
            leased_until=str(row[8]) if row[8] is not None else None,
            created_at=str(row[9]),
            updated_at=str(row[10]),
            last_error=str(row[11]) if row[11] is not None else None,
        )

    def list_by_status(self, status: QueueItemStatus) -> tuple[DurableQueueItem, ...]:
        rows = self._connection.execute("SELECT item_id FROM runtime_queue WHERE status = ? ORDER BY priority DESC, item_id ASC", (status.value,)).fetchall()
        return tuple(self.get(str(row[0])) for row in rows)

    def _transition(self, item_id: str, expected: QueueItemStatus, target: QueueItemStatus, *, now: str) -> DurableQueueItem:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE runtime_queue SET status = ?, updated_at = ? WHERE item_id = ? AND status = ?",
                (target.value, now, item_id, expected.value),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"queue item {item_id} is not {expected.value}")
        return self.get(item_id)


class DuplicateMessageGuard:
    def __init__(self, store: object | None = None, *, processed_at: str = "2026-07-17T00:00:00Z") -> None:
        self._seen: set[str] = set()
        self._store = store
        self._processed_at = processed_at

    def mark(self, message_id: str) -> bool:
        if self._store is not None:
            return bool(self._store.mark_processed(message_id, self._processed_at))
        if message_id in self._seen:
            return False
        self._seen.add(message_id)
        return True
