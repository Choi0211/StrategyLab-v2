"""Bounded contextual memory orchestration for Gaon's conversation brain."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import sqlite3

from gaon.runtime.llm_conversation import ConversationRepository, LLMConversationMessage
from gaon.runtime.serialization import dumps_json


class ContextSourceType(str, Enum):
    RECENT_CONVERSATION = "recent_conversation"
    CHAMPION_REGISTRY = "champion_registry"
    VALIDATION_REPORT = "validation_report"
    PAPER_REVALIDATION = "paper_revalidation"
    V5_PIPELINE = "v5_pipeline"


@dataclass(frozen=True)
class ContextItem:
    source_type: ContextSourceType
    source_ref: str
    content: str
    created_at: str

    def bounded(self, max_chars: int) -> "ContextItem":
        if len(self.content) <= max_chars:
            return self
        return ContextItem(self.source_type, self.source_ref, self.content[: max_chars - 3] + "...", self.created_at)


@dataclass(frozen=True)
class ConversationContextBundle:
    session_id: str
    items: tuple[ContextItem, ...]
    warnings: tuple[str, ...]
    max_chars: int

    @property
    def references(self) -> tuple[str, ...]:
        return tuple(item.source_ref for item in self.items)

    def to_prompt_context(self) -> str:
        if not self.items:
            return "No verified runtime context is available."
        lines = ["Verified runtime context:"]
        for item in self.items:
            lines.append(f"- {item.source_type.value}:{item.source_ref}: {item.content}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ConversationSummaryRecord:
    summary_id: str
    session_id: str
    source_refs: tuple[str, ...]
    summary_text: str
    created_at: str


class SQLiteConversationSummaryRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, summary: ConversationSummaryRecord) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO conversation_summaries(summary_id, session_id, source_refs_json, summary_text, created_at) VALUES (?, ?, ?, ?, ?)",
                (summary.summary_id, summary.session_id, json.dumps(list(summary.source_refs), sort_keys=True), summary.summary_text, summary.created_at),
            )

    def list_for_session(self, session_id: str) -> tuple[ConversationSummaryRecord, ...]:
        rows = self._connection.execute(
            "SELECT summary_id, session_id, source_refs_json, summary_text, created_at FROM conversation_summaries WHERE session_id = ? ORDER BY created_at, summary_id",
            (session_id,),
        ).fetchall()
        return tuple(
            ConversationSummaryRecord(str(row[0]), str(row[1]), _loads_tuple(str(row[2])), str(row[3]), str(row[4]))
            for row in rows
        )


class ConversationContextOrchestrator:
    """Collects read-only, bounded context without inventing unavailable state."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        conversation_repository: ConversationRepository,
        *,
        recent_message_limit: int = 6,
        max_chars: int = 2400,
    ) -> None:
        if recent_message_limit < 0 or recent_message_limit > 50:
            raise ValueError("recent message limit must be between 0 and 50")
        if max_chars < 200 or max_chars > 12000:
            raise ValueError("context max chars must be between 200 and 12000")
        self._connection = connection
        self._conversation_repository = conversation_repository
        self._recent_message_limit = recent_message_limit
        self._max_chars = max_chars

    def build(self, session_id: str) -> ConversationContextBundle:
        items: list[ContextItem] = []
        warnings: list[str] = []
        items.extend(self._recent_conversation(session_id))
        items.extend(self._latest_rows("champion_registry", "slot", "payload_json", "updated_at", ContextSourceType.CHAMPION_REGISTRY, limit=1))
        items.extend(self._latest_rows("validation_reports", "validation_id", "payload_json", "generated_at", ContextSourceType.VALIDATION_REPORT, limit=2))
        items.extend(self._latest_rows("paper_revalidation_reports", "revalidation_id", "payload_json", "generated_at", ContextSourceType.PAPER_REVALIDATION, limit=2))
        items.extend(self._latest_rows("gaon_v5_pipeline_runs", "run_id", "payload_json", "updated_at", ContextSourceType.V5_PIPELINE, limit=2))
        bounded = self._fit_budget(items)
        if not bounded:
            warnings.append("no verified context available")
        return ConversationContextBundle(session_id=session_id, items=tuple(bounded), warnings=tuple(warnings), max_chars=self._max_chars)

    def _recent_conversation(self, session_id: str) -> list[ContextItem]:
        messages = self._conversation_repository.list_messages(session_id, limit=self._recent_message_limit)
        return [
            ContextItem(ContextSourceType.RECENT_CONVERSATION, message.message_id, _message_summary(message), message.created_at)
            for message in messages
        ]

    def _latest_rows(self, table: str, id_column: str, payload_column: str, time_column: str, source_type: ContextSourceType, *, limit: int) -> list[ContextItem]:
        if not _table_exists(self._connection, table):
            return []
        rows = self._connection.execute(
            f"SELECT {id_column}, {payload_column}, {time_column} FROM {table} ORDER BY {time_column} DESC, {id_column} DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [ContextItem(source_type, f"{table}:{row[0]}", _compact_json(str(row[1])), str(row[2])) for row in rows]

    def _fit_budget(self, items: list[ContextItem]) -> list[ContextItem]:
        output: list[ContextItem] = []
        used = 0
        per_item_cap = max(80, self._max_chars // max(1, min(len(items), 8)))
        for item in items:
            candidate = item.bounded(per_item_cap)
            cost = len(candidate.source_type.value) + len(candidate.source_ref) + len(candidate.content) + 8
            if used + cost > self._max_chars:
                continue
            output.append(candidate)
            used += cost
        return output


def _message_summary(message: LLMConversationMessage) -> str:
    return f"{message.role}/{message.intent}/{message.route}: {message.content}"


def _compact_json(value: str) -> str:
    try:
        payload = json.loads(value)
        if isinstance(payload, dict):
            return dumps_json(payload)
    except json.JSONDecodeError:
        pass
    return value


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row is not None


def _loads_tuple(value: str) -> tuple[str, ...]:
    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("summary source refs must be strings")
    return tuple(loaded)
