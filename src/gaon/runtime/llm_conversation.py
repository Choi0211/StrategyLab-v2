"""Gaon LLM conversation brain with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import sqlite3
from typing import Protocol
from uuid import uuid4

from gaon.runtime.assistant_provider import AssistantRequest, ProviderError, validate_provider_response
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import ConfigurationError
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.intents import Intent, parse_intent
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.persona import RULE_BASED_ROUTE, persona_text, safety_warning
from gaon.runtime.provider_registry import build_assistant_provider
from gaon.runtime.serialization import dumps_json, loads_json

CONVERSATION_SCHEMA_VERSION = 1
MAX_CONVERSATION_INPUT_CHARS = 4096


@dataclass(frozen=True)
class LLMConversationMessage:
    message_id: str
    session_id: str
    role: str
    content: str
    intent: str
    route: str
    references: tuple[str, ...]
    warnings: tuple[str, ...]
    tool_calls: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": CONVERSATION_SCHEMA_VERSION,
            "message_id": self.message_id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "intent": self.intent,
            "route": self.route,
            "references": list(self.references),
            "warnings": list(self.warnings),
            "tool_calls": list(self.tool_calls),
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "LLMConversationMessage":
        if payload.get("schema_version") != CONVERSATION_SCHEMA_VERSION:
            raise ValueError("unsupported conversation message schema version")
        return cls(
            message_id=str(payload["message_id"]),
            session_id=str(payload["session_id"]),
            role=str(payload["role"]),
            content=str(payload["content"]),
            intent=str(payload["intent"]),
            route=str(payload["route"]),
            references=_tuple_of_str(payload.get("references", [])),
            warnings=_tuple_of_str(payload.get("warnings", [])),
            tool_calls=_tuple_of_str(payload.get("tool_calls", [])),
            created_at=str(payload["created_at"]),
        )


@dataclass(frozen=True)
class LLMConversationSession:
    session_id: str
    user_ref: str
    source: str
    status: str
    created_at: str
    updated_at: str
    metadata: dict[str, object]

    def to_json(self) -> dict[str, object]:
        return {
            "schema_version": CONVERSATION_SCHEMA_VERSION,
            "session_id": self.session_id,
            "user_ref": self.user_ref,
            "source": self.source,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> "LLMConversationSession":
        if payload.get("schema_version") != CONVERSATION_SCHEMA_VERSION:
            raise ValueError("unsupported conversation session schema version")
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("conversation session metadata must be an object")
        return cls(
            session_id=str(payload["session_id"]),
            user_ref=str(payload["user_ref"]),
            source=str(payload["source"]),
            status=str(payload["status"]),
            created_at=str(payload["created_at"]),
            updated_at=str(payload["updated_at"]),
            metadata=dict(metadata),
        )


@dataclass(frozen=True)
class LLMConversationRequest:
    session_id: str
    user_ref: str
    source: str
    text: str
    received_at: str
    message_id: str | None = None


@dataclass(frozen=True)
class LLMConversationResponse:
    response_id: str
    session_id: str
    text: str
    intent: Intent
    route: str
    references: tuple[str, ...]
    warnings: tuple[str, ...]
    approval_required: bool
    generated_at: str
    provider: str


class ConversationRepository(Protocol):
    def upsert_session(self, session: LLMConversationSession) -> None: ...
    def add_message(self, message: LLMConversationMessage) -> None: ...
    def get_session(self, session_id: str) -> LLMConversationSession: ...
    def list_messages(self, session_id: str, *, limit: int = 20) -> tuple[LLMConversationMessage, ...]: ...


class SQLiteConversationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert_session(self, session: LLMConversationSession) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO conversation_sessions(session_id, user_ref, source, status, created_at, updated_at, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    user_ref = excluded.user_ref,
                    source = excluded.source,
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    session.session_id,
                    session.user_ref,
                    session.source,
                    session.status,
                    session.created_at,
                    session.updated_at,
                    dumps_json(session.metadata),
                ),
            )

    def add_message(self, message: LLMConversationMessage) -> None:
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO conversation_messages(
                    message_id, session_id, role, content, intent, route, references_json,
                    warnings_json, tool_calls_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.message_id,
                    message.session_id,
                    message.role,
                    message.content,
                    message.intent,
                    message.route,
                    json.dumps(list(message.references), sort_keys=True),
                    json.dumps(list(message.warnings), sort_keys=True),
                    json.dumps(list(message.tool_calls), sort_keys=True),
                    message.created_at,
                ),
            )

    def get_session(self, session_id: str) -> LLMConversationSession:
        row = self._connection.execute(
            "SELECT session_id, user_ref, source, status, created_at, updated_at, metadata_json FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise KeyError(session_id)
        return LLMConversationSession(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), str(row[5]), loads_json(str(row[6])))

    def list_messages(self, session_id: str, *, limit: int = 20) -> tuple[LLMConversationMessage, ...]:
        rows = self._connection.execute(
            """
            SELECT message_id, session_id, role, content, intent, route, references_json, warnings_json, tool_calls_json, created_at
            FROM conversation_messages
            WHERE session_id = ?
            ORDER BY created_at DESC, message_id DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        messages = tuple(_message_from_row(row) for row in rows)
        return tuple(reversed(messages))


class LLMConversationBrain:
    def __init__(
        self,
        config: GaonRuntimeConfig,
        repository: ConversationRepository,
        *,
        event_store: SQLiteEventStore | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._config = config
        self._repository = repository
        self._event_store = event_store
        self._metrics = metrics or MetricsCollector()

    def respond(self, request: LLMConversationRequest) -> LLMConversationResponse:
        text = request.text.strip()
        if not text:
            text = ""
        if len(text) > MAX_CONVERSATION_INPUT_CHARS:
            raise ConfigurationError("conversation input is too long")
        now = request.received_at
        session = self._ensure_session(request, now)
        intent = parse_intent(text)
        approval_required = _requires_manual_boundary(text)
        user_message_id = request.message_id or f"conversation-user:{uuid4().hex}"
        self._repository.add_message(
            LLMConversationMessage(user_message_id, session.session_id, "user", text, intent.value, "input", (), (), (), now)
        )
        response_text, route, warnings, references, provider = self._generate(request, intent, approval_required)
        generated_at = now
        response_id = f"conversation-assistant:{uuid4().hex}"
        response = LLMConversationResponse(
            response_id=response_id,
            session_id=session.session_id,
            text=response_text,
            intent=intent,
            route=route,
            references=references,
            warnings=warnings,
            approval_required=approval_required,
            generated_at=generated_at,
            provider=provider,
        )
        self._repository.add_message(
            LLMConversationMessage(
                response_id,
                session.session_id,
                "assistant",
                response.text,
                intent.value,
                route,
                response.references,
                response.warnings,
                (),
                generated_at,
            )
        )
        self._repository.upsert_session(
            LLMConversationSession(session.session_id, session.user_ref, session.source, "active", session.created_at, generated_at, session.metadata)
        )
        self._metrics.increment("llm_conversation_responses", route=_metric_route(route), intent=intent.value)
        self._append_event(response, request)
        return response

    def _ensure_session(self, request: LLMConversationRequest, now: str) -> LLMConversationSession:
        try:
            return self._repository.get_session(request.session_id)
        except KeyError:
            session = LLMConversationSession(
                request.session_id,
                request.user_ref,
                request.source,
                "active",
                now,
                now,
                {"owner": "gaon", "release": "v5"},
            )
            self._repository.upsert_session(session)
            return session

    def _generate(self, request: LLMConversationRequest, intent: Intent, approval_required: bool) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str]:
        warnings: tuple[str, ...] = ()
        warning = safety_warning(request.text)
        if warning:
            approval_required = True
            warnings = (warning,)
        if not self._config.assistant_enabled or approval_required:
            if approval_required:
                warnings = (*warnings, "provider bypassed for approval boundary")
            return persona_text(intent), RULE_BASED_ROUTE, _dedupe(warnings), (), "deterministic"
        try:
            provider = build_assistant_provider(self._config)
            provider_response = validate_provider_response(
                provider.respond(
                    AssistantRequest(
                        text=request.text,
                        intent=intent,
                        user_id=request.user_ref,
                        conversation_id=request.session_id,
                        received_at=request.received_at,
                        prompt=_base_prompt(request.text),
                        references=(),
                    )
                ),
                max_chars=self._config.assistant_max_output_tokens * 8,
            )
            return (
                provider_response.text,
                provider_response.route,
                _dedupe((*warnings, *provider_response.warnings)),
                provider_response.references,
                provider_response.provider_name,
            )
        except ProviderError as exc:
            return persona_text(intent), "fallback", _dedupe((*warnings, f"provider fallback: {exc.__class__.__name__}")), (), "deterministic"

    def _append_event(self, response: LLMConversationResponse, request: LLMConversationRequest) -> None:
        if self._event_store is None:
            return
        self._event_store.append(
            DurableEvent(
                event_id=f"conversation:{uuid4().hex}",
                event_type="LLMConversationResponded",
                occurred_at=response.generated_at,
                actor_ref="gaon:llm-brain",
                correlation_id=response.session_id,
                causation_id=request.message_id,
                scope="runtime",
                project="StrategyLab",
                strategy="N/A",
                market="N/A",
                payload={"intent": response.intent.value, "route": response.route, "approval_required": response.approval_required},
                evidence_refs=response.references,
                audit_refs=(),
                appended_at=response.generated_at,
            )
        )


def _message_from_row(row: tuple[object, ...]) -> LLMConversationMessage:
    return LLMConversationMessage(
        str(row[0]),
        str(row[1]),
        str(row[2]),
        str(row[3]),
        str(row[4]),
        str(row[5]),
        _loads_tuple(str(row[6])),
        _loads_tuple(str(row[7])),
        _loads_tuple(str(row[8])),
        str(row[9]),
    )


def _loads_tuple(value: str) -> tuple[str, ...]:
    loaded = json.loads(value)
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise ValueError("conversation JSON arrays must contain strings")
    return tuple(loaded)


def _tuple_of_str(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("conversation payload list must contain strings")
    return tuple(value)


def _base_prompt(text: str) -> str:
    return (
        "You are Gaon, a calm Korean AI Engineering Partner for Youngha. "
        "Do not claim live trading, automatic approval, private repo access, or unavailable integrations. "
        f"User message: {text}"
    )


def _requires_manual_boundary(text: str) -> bool:
    normalized = text.casefold()
    blocked = ("approve", "approval", "buy", "sell", "order", "kis", "broker", "secret", "매수", "매도", "주문", "승인", "실거래")
    return any(token in normalized for token in blocked)


def _metric_route(route: str) -> str:
    return route.replace("+", "_").replace("-", "_")[:48] or "unknown"


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
