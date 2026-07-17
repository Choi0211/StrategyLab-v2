"""Runtime repository protocols and SQLite implementations."""

from __future__ import annotations

from dataclasses import dataclass
import sqlite3
from typing import Protocol

from gaon.research.approval import ApprovalRequest, ApprovalStatus
from gaon.runtime.serialization import dumps_json, loads_json


@dataclass(frozen=True)
class StoredProposal:
    proposal_id: str
    status: str
    payload: dict[str, object]


@dataclass(frozen=True)
class StoredResearchRun:
    run_id: str
    proposal_id: str
    status: str
    updated_at: str
    payload: dict[str, object]


@dataclass(frozen=True)
class StoredSchedulerJob:
    job_id: str
    next_run_at: str
    last_run_at: str | None = None
    idempotency_key: str | None = None
    execution_status: str = "pending"


@dataclass(frozen=True)
class StoredNotificationAttempt:
    attempt_id: str
    target_ref: str
    status: str
    created_at: str
    payload: dict[str, object]


class TelegramStateRepository(Protocol):
    def get_offset(self, chat_id: str) -> int | None: ...
    def save_offset(self, chat_id: str, next_offset: int, updated_at: str) -> None: ...
    def mark_processed(self, message_id: str, processed_at: str) -> bool: ...


class AuditEventRepository(Protocol):
    def append(self, event_id: str, event_type: str, payload: dict[str, object], created_at: str) -> None: ...
    def list_ids(self) -> tuple[str, ...]: ...


class ApprovalRepository(Protocol):
    def add(self, approval: ApprovalRequest) -> None: ...
    def get(self, approval_id: str) -> ApprovalRequest: ...
    def update(self, approval: ApprovalRequest) -> None: ...


class SQLiteTelegramStateRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

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


class SQLiteAuditEventRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(self, event_id: str, event_type: str, payload: dict[str, object], created_at: str) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO runtime_audit_events(event_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (event_id, event_type, dumps_json(payload), created_at),
            )

    def list_ids(self) -> tuple[str, ...]:
        rows = self._connection.execute("SELECT event_id FROM runtime_audit_events ORDER BY created_at, event_id").fetchall()
        return tuple(str(row[0]) for row in rows)


class SQLiteApprovalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, approval: ApprovalRequest) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO approvals(
                    approval_id, proposal_id, status, expires_at, requested_actor, requested_chat_id,
                    token_digest, issued_at, nonce, consumed_by_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _approval_row(approval),
            )

    def get(self, approval_id: str) -> ApprovalRequest:
        row = self._connection.execute(
            """
            SELECT approval_id, proposal_id, requested_actor, requested_chat_id, token_digest,
                   issued_at, expires_at, nonce, status, consumed_by_run_id
            FROM approvals WHERE approval_id = ?
            """,
            (approval_id,),
        ).fetchone()
        if row is None:
            raise KeyError(approval_id)
        return _approval_from_row(row)

    def update(self, approval: ApprovalRequest) -> None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE approvals
                   SET status = ?, consumed_by_run_id = ?, expires_at = ?
                 WHERE approval_id = ?
                """,
                (approval.status.value, approval.consumed_by_run_id, approval.expires_at, approval.approval_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(approval.approval_id)


class SQLiteProposalRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, proposal: StoredProposal) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO research_proposals(proposal_id, status, payload_json) VALUES (?, ?, ?) "
                "ON CONFLICT(proposal_id) DO UPDATE SET status = excluded.status, payload_json = excluded.payload_json",
                (proposal.proposal_id, proposal.status, dumps_json(proposal.payload)),
            )

    def get(self, proposal_id: str) -> StoredProposal:
        row = self._connection.execute("SELECT proposal_id, status, payload_json FROM research_proposals WHERE proposal_id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise KeyError(proposal_id)
        return StoredProposal(str(row[0]), str(row[1]), loads_json(str(row[2])))


class SQLiteResearchRunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, run: StoredResearchRun) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO research_runs(run_id, proposal_id, status, updated_at, payload_json) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at, payload_json = excluded.payload_json",
                (run.run_id, run.proposal_id, run.status, run.updated_at, dumps_json(run.payload)),
            )

    def get(self, run_id: str) -> StoredResearchRun:
        row = self._connection.execute("SELECT run_id, proposal_id, status, updated_at, payload_json FROM research_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return StoredResearchRun(str(row[0]), str(row[1]), str(row[2]), str(row[3]), loads_json(str(row[4])))


class SQLiteSchedulerJobRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert(self, job: StoredSchedulerJob) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO scheduler_jobs(job_id, next_run_at, last_run_at, idempotency_key, execution_status) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET next_run_at = excluded.next_run_at, last_run_at = excluded.last_run_at, "
                "idempotency_key = excluded.idempotency_key, execution_status = excluded.execution_status",
                (job.job_id, job.next_run_at, job.last_run_at, job.idempotency_key, job.execution_status),
            )


class SQLiteNotificationAttemptRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, attempt: StoredNotificationAttempt) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO notification_attempts(attempt_id, target_ref, status, created_at, payload_json) VALUES (?, ?, ?, ?, ?)",
                (attempt.attempt_id, attempt.target_ref, attempt.status, attempt.created_at, dumps_json(attempt.payload)),
            )


def _approval_row(approval: ApprovalRequest) -> tuple[str, str, str, str, str, str, str, str, str, str | None]:
    return (
        approval.approval_id,
        approval.proposal_id,
        approval.status.value,
        approval.expires_at,
        approval.requested_actor,
        approval.requested_chat_id,
        approval.token_digest,
        approval.issued_at,
        approval.nonce,
        approval.consumed_by_run_id,
    )


def _approval_from_row(row: tuple[object, ...]) -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=str(row[0]),
        proposal_id=str(row[1]),
        requested_actor=str(row[2]),
        requested_chat_id=str(row[3]),
        token_digest=str(row[4]),
        issued_at=str(row[5]),
        expires_at=str(row[6]),
        nonce=str(row[7]),
        status=ApprovalStatus(str(row[8])),
        consumed_by_run_id=str(row[9]) if row[9] is not None else None,
    )
