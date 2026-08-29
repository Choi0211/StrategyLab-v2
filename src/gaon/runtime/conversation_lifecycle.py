"""Conversation lifecycle: list, archive, and delete web/Telegram
conversations, and paginate their message history.

Deliberately separate from ``gaon.runtime.llm_conversation``'s core
repository: this module never reads or writes ResearchMission/
StrategyCandidate state (that lives in ``conversation_sessions.
metadata_json``'s ``conversation_mvp.research_mission`` key), never touches
``cognitive_records`` (Cognitive Core durable goals/preferences), and never
deletes a ``conversation_sessions`` row. "Delete conversation" here means
exactly one thing: purge that session's own message history
(``conversation_messages`` + its two per-message dependent tables,
``conversation_summaries`` and ``conversation_tool_results``) - the session
row itself, and therefore any ResearchMission/StrategyCandidate JSON
embedded in its ``metadata_json``, is left untouched. This is deliberate,
not an oversight: mission/candidate state is Gaon's own durable research
record, not conversation history, and chat-lifecycle actions (new/archive/
delete) must never be able to reset it.

No schema migration: "archive" reuses the existing ``conversation_sessions.
status`` TEXT column (already present, previously only ever set to the
literal "active"); "list" reuses the existing
``idx_conversation_sessions_user(user_ref, updated_at)`` index; pagination
adds only a new WHERE clause over already-indexed columns
(``idx_conversation_messages_session(session_id, created_at, message_id)``).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from gaon.runtime.llm_conversation import LLMConversationMessage

STATUS_ACTIVE = "active"
STATUS_ARCHIVED = "archived"
STATUS_DELETED = "deleted"


@dataclass(frozen=True)
class ConversationSummary:
    session_id: str
    user_ref: str
    source: str
    status: str
    created_at: str
    updated_at: str
    message_count: int


def list_conversations(
    connection: sqlite3.Connection,
    *,
    user_ref: str,
    limit: int = 50,
    include_archived: bool = True,
) -> tuple[ConversationSummary, ...]:
    """Most-recently-updated-first list of a user's conversations.

    Deleted conversations (``status == "deleted"``) are always excluded -
    their message history has already been purged, so there is nothing
    left to re-enter; the session row (and any ResearchMission state on
    it) still exists and is unaffected, just no longer listed as a
    conversation to resume. Archived conversations are included by
    default (``include_archived=True``) so a client can render an
    "archived" section; pass ``include_archived=False`` for an
    active-only list.
    """
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    statuses = [STATUS_ACTIVE] + ([STATUS_ARCHIVED] if include_archived else [])
    placeholders = ",".join("?" for _ in statuses)
    rows = connection.execute(
        f"""
        SELECT s.session_id, s.user_ref, s.source, s.status, s.created_at, s.updated_at,
               (SELECT COUNT(*) FROM conversation_messages m WHERE m.session_id = s.session_id) AS message_count
          FROM conversation_sessions s
         WHERE s.user_ref = ? AND s.status IN ({placeholders})
         ORDER BY s.updated_at DESC, s.session_id DESC
         LIMIT ?
        """,
        (user_ref, *statuses, limit),
    ).fetchall()
    return tuple(
        ConversationSummary(str(r[0]), str(r[1]), str(r[2]), str(r[3]), str(r[4]), str(r[5]), int(r[6]))
        for r in rows
    )


def archive_conversation(connection: sqlite3.Connection, *, session_id: str, now: str) -> bool:
    """Marks a conversation archived. Returns False if the session does
    not exist. Never touches ``metadata_json`` (mission/candidate state)."""
    return _set_status(connection, session_id=session_id, status=STATUS_ARCHIVED, now=now)


def unarchive_conversation(connection: sqlite3.Connection, *, session_id: str, now: str) -> bool:
    return _set_status(connection, session_id=session_id, status=STATUS_ACTIVE, now=now)


def _set_status(connection: sqlite3.Connection, *, session_id: str, status: str, now: str) -> bool:
    with connection:
        cursor = connection.execute(
            "UPDATE conversation_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
            (status, now, session_id),
        )
    return cursor.rowcount > 0


def delete_conversation_messages(connection: sqlite3.Connection, *, session_id: str, now: str, confirm: bool) -> int:
    """Purges this session's message history only. Requires
    ``confirm=True`` - a destructive action must never happen from a
    caller that forgot to ask; this is the same explicit-confirmation
    contract ``gaon.runtime.web_api`` should enforce at the HTTP layer,
    enforced again here so no other future caller of this function can
    skip it either.

    Returns the number of ``conversation_messages`` rows removed (0 if
    the session does not exist or already has no messages). The
    ``conversation_sessions`` row survives with its ``metadata_json``
    (ResearchMission/StrategyCandidate state) completely unchanged - only
    its ``status`` is set to "deleted" and ``updated_at`` bumped, exactly
    like archive.
    """
    if not confirm:
        raise ValueError("delete_conversation_messages requires confirm=True")
    with connection:
        deleted = connection.execute(
            "DELETE FROM conversation_messages WHERE session_id = ?", (session_id,)
        ).rowcount
        connection.execute("DELETE FROM conversation_summaries WHERE session_id = ?", (session_id,))
        connection.execute("DELETE FROM conversation_tool_results WHERE session_id = ?", (session_id,))
        connection.execute(
            "UPDATE conversation_sessions SET status = ?, updated_at = ? WHERE session_id = ?",
            (STATUS_DELETED, now, session_id),
        )
    return int(deleted)


def list_messages_page(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    limit: int = 30,
    before_message_id: str | None = None,
) -> tuple[LLMConversationMessage, ...]:
    """Chronological page of messages, newest page first when no cursor
    is given (mirrors ``SQLiteConversationRepository.list_messages``'s
    existing most-recent-N behavior exactly when ``before_message_id`` is
    omitted, so this is backward compatible with that method rather than
    a competing read path). Pass the oldest message_id from a previous
    page as ``before_message_id`` to fetch the next-older page for
    infinite-scroll/pagination.
    """
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if before_message_id is None:
        rows = connection.execute(
            """
            SELECT message_id, session_id, role, content, intent, route,
                   references_json, warnings_json, tool_calls_json, created_at
              FROM conversation_messages
             WHERE session_id = ?
             ORDER BY created_at DESC, message_id DESC
             LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    else:
        anchor = connection.execute(
            "SELECT created_at FROM conversation_messages WHERE session_id = ? AND message_id = ?",
            (session_id, before_message_id),
        ).fetchone()
        if anchor is None:
            return ()
        rows = connection.execute(
            """
            SELECT message_id, session_id, role, content, intent, route,
                   references_json, warnings_json, tool_calls_json, created_at
              FROM conversation_messages
             WHERE session_id = ?
               AND (created_at < ? OR (created_at = ? AND message_id < ?))
             ORDER BY created_at DESC, message_id DESC
             LIMIT ?
            """,
            (session_id, anchor[0], anchor[0], before_message_id, limit),
        ).fetchall()
    messages = tuple(_message_from_row(row) for row in rows)
    return tuple(reversed(messages))


def _loads_str_tuple(value: str) -> tuple[str, ...]:
    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("conversation JSON arrays must contain strings")
    return tuple(loaded)


def _message_from_row(row: tuple[object, ...]) -> LLMConversationMessage:
    return LLMConversationMessage(
        str(row[0]),
        str(row[1]),
        str(row[2]),
        str(row[3]),
        str(row[4]),
        str(row[5]),
        _loads_str_tuple(str(row[6])),
        _loads_str_tuple(str(row[7])),
        _loads_str_tuple(str(row[8])),
        str(row[9]),
    )
