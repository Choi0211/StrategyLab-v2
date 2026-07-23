"""Gaon LLM conversation brain with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import sqlite3
from typing import Protocol
from uuid import uuid4

from gaon.runtime.assistant_provider import AssistantProvider, AssistantProviderResponse, AssistantRequest, AssistantToolResult, ProviderError, validate_provider_response
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import ConfigurationError
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.intents import Intent, parse_intent
from gaon.runtime.long_response import continuation_prompt, merge_response_parts
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.persona import RULE_BASED_ROUTE, persona_text, safety_warning
from gaon.runtime.provider_registry import build_assistant_provider
from gaon.runtime.research_grounding import contains_unverified_fixture_metrics, format_grounded_tool_response, grounded_system_policy, is_research_tool
from gaon.runtime.serialization import dumps_json, loads_json
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest

CONVERSATION_SCHEMA_VERSION = 1
MAX_CONVERSATION_INPUT_CHARS = 4096
TOOL_RESULT_TTL_SECONDS = {
    "runtime_status": 60,
    "champion_status": 900,
    "v5_pipeline_history": 900,
    "research_memory_search": 300,
    "strategy_critique": 300,
    "strategy_quality_score": 300,
    "data_quality_check": 300,
    "backtest_strategy": 300,
    "backtest_result": 300,
    "compare_backtests": 300,
}


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
    tool_calls: tuple[str, ...] = ()


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


@dataclass(frozen=True)
class ConversationToolResultRecord:
    result_id: str
    session_id: str
    tool_name: str
    status: str
    output: dict[str, object]
    created_at: str
    expires_at: str


class SQLiteConversationToolResultRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add(self, record: ConversationToolResultRecord) -> None:
        with self._connection:
            self._connection.execute(
                "INSERT INTO conversation_tool_results(result_id, session_id, tool_name, status, output_json, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record.result_id, record.session_id, record.tool_name, record.status, dumps_json(record.output), record.created_at, record.expires_at),
            )

    def latest(self, session_id: str) -> ConversationToolResultRecord | None:
        row = self._connection.execute(
            "SELECT result_id, session_id, tool_name, status, output_json, created_at, expires_at FROM conversation_tool_results WHERE session_id = ? ORDER BY created_at DESC, result_id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return ConversationToolResultRecord(str(row[0]), str(row[1]), str(row[2]), str(row[3]), loads_json(str(row[4])), str(row[5]), str(row[6]))

    def list_recent(self, session_id: str, *, limit: int = 10, tool_names: tuple[str, ...] | None = None) -> tuple[ConversationToolResultRecord, ...]:
        if limit < 1 or limit > 20:
            raise ValueError("conversation tool result limit must be between 1 and 20")
        if tool_names:
            placeholders = ",".join("?" for _ in tool_names)
            rows = self._connection.execute(
                f"""
                SELECT result_id, session_id, tool_name, status, output_json, created_at, expires_at
                FROM conversation_tool_results
                WHERE session_id = ? AND tool_name IN ({placeholders})
                ORDER BY created_at DESC, result_id DESC
                LIMIT ?
                """,
                (session_id, *tool_names, limit),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT result_id, session_id, tool_name, status, output_json, created_at, expires_at
                FROM conversation_tool_results
                WHERE session_id = ?
                ORDER BY created_at DESC, result_id DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return tuple(ConversationToolResultRecord(str(row[0]), str(row[1]), str(row[2]), str(row[3]), loads_json(str(row[4])), str(row[5]), str(row[6])) for row in rows)


class LLMConversationBrain:
    def __init__(
        self,
        config: GaonRuntimeConfig,
        repository: ConversationRepository,
        *,
        context_orchestrator=None,
        tool_executor: SafeToolExecutor | None = None,
        tool_result_repository: SQLiteConversationToolResultRepository | None = None,
        assistant_provider: AssistantProvider | None = None,
        event_store: SQLiteEventStore | None = None,
        metrics: MetricsCollector | None = None,
    ) -> None:
        self._config = config
        self._repository = repository
        self._context_orchestrator = context_orchestrator
        self._tool_executor = tool_executor
        self._tool_result_repository = tool_result_repository
        self._assistant_provider = assistant_provider
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
        context = self._context_orchestrator.build(request.session_id) if self._context_orchestrator is not None else None
        response_text, route, warnings, references, provider, tool_calls = self._generate(request, intent, approval_required, context)
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
            tool_calls=tool_calls,
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
                response.tool_calls,
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

    def _generate(self, request: LLMConversationRequest, intent: Intent, approval_required: bool, context) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]:
        warnings: tuple[str, ...] = ()
        references: tuple[str, ...] = tuple(context.references) if context is not None else ()
        if context is not None:
            warnings = (*warnings, *context.warnings)
        warning = safety_warning(request.text)
        if warning:
            approval_required = True
            warnings = (warning,)
        if not self._config.assistant_enabled or approval_required:
            if approval_required:
                warnings = (*warnings, "provider bypassed for approval boundary")
            return persona_text(intent), RULE_BASED_ROUTE, _dedupe(warnings), references, "deterministic", ()
        synthesis = self._try_multi_result_synthesis(request, warnings, references)
        if synthesis is not None:
            return synthesis
        if self._config.assistant_provider == "deterministic":
            tool_response = self._try_deterministic_tool(request, warnings, references)
            if tool_response is not None:
                return tool_response
            follow_up = self._try_follow_up_tool(request, warnings, references)
            if follow_up is not None:
                return follow_up
        try:
            self._metrics.increment("gaon_llm_provider_requests_total", provider=self._config.assistant_provider)
            self._append_provider_event("LLMProviderRequestStarted", request, {"provider": self._config.assistant_provider})
            provider = self._assistant_provider or build_assistant_provider(self._config)
            tools = self._tool_executor.assistant_tool_definitions() if self._tool_executor is not None else ()
            provider_response = validate_provider_response(
                provider.respond(
                    AssistantRequest(
                        text=request.text,
                        intent=intent,
                        user_id=request.user_ref,
                        conversation_id=request.session_id,
                        received_at=request.received_at,
                        prompt=_base_prompt(request.text, context),
                        references=references,
                        tools=tools,
                    )
                ),
                max_chars=self._config.assistant_max_output_tokens * 8,
            )
            self._append_provider_event(
                "LLMProviderRequestCompleted",
                request,
                {"provider": provider_response.provider_name, "tool_calls": len(provider_response.tool_calls), "finish_reason": provider_response.finish_reason or "unknown", "truncated": provider_response.truncated},
            )
            fallback_warning = next((warning for warning in provider_response.warnings if "provider error:" in warning or "provider fallback" in warning), None)
            if fallback_warning is not None:
                self._metrics.increment("gaon_llm_provider_fallbacks_total", reason="registry_fallback")
                self._append_provider_event("LLMProviderFallbackUsed", request, {"provider": provider_response.provider_name, "reason": fallback_warning})
            if provider_response.tool_calls and self._tool_executor is not None:
                return self._execute_provider_tool_calls(provider, request, intent, provider_response, warnings, references, tools)
            fallback = self._try_deterministic_tool(request, warnings, references)
            if fallback is not None:
                self._metrics.increment("gaon_llm_provider_fallbacks_total", reason="deterministic_safe_tool")
                return fallback
            follow_up = self._try_follow_up_tool(request, warnings, references)
            if follow_up is not None:
                return follow_up
            if provider_response.truncated:
                provider_response = self._continue_provider_response(provider, request, intent, provider_response, references)
            return (
                provider_response.text,
                provider_response.route,
                _dedupe((*warnings, *provider_response.warnings)),
                _dedupe((*references, *provider_response.references)),
                provider_response.provider_name,
                (),
            )
        except ProviderError as exc:
            reason = exc.__class__.__name__
            if "Timeout" in reason:
                self._metrics.increment("gaon_llm_provider_timeouts_total", provider=self._config.assistant_provider)
                self._append_provider_event("LLMProviderRequestTimedOut", request, {"provider": self._config.assistant_provider, "error_type": reason})
            else:
                self._metrics.increment("gaon_llm_provider_parse_failures_total", provider=self._config.assistant_provider)
                self._append_provider_event("LLMProviderRequestFailed", request, {"provider": self._config.assistant_provider, "error_type": reason})
            fallback = self._try_deterministic_tool(request, (*warnings, f"provider fallback: {reason}"), references)
            if fallback is not None:
                self._metrics.increment("gaon_llm_provider_fallbacks_total", reason=reason)
                return fallback
            return _provider_unavailable_message(), "fallback", _dedupe((*warnings, f"provider fallback: {reason}")), references, "deterministic", ()

    def _execute_provider_tool_calls(self, provider: AssistantProvider, request: LLMConversationRequest, intent: Intent, provider_response, warnings: tuple[str, ...], references: tuple[str, ...], tools) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]:
        assert self._tool_executor is not None
        max_calls = self._config.assistant_max_tool_calls_per_turn
        selected = provider_response.tool_calls[:max_calls]
        results: list[AssistantToolResult] = []
        executed: list[str] = []
        for call in selected:
            result = self._tool_executor.execute(ToolRequest(call.name, call.arguments, request.user_ref, request.received_at))
            self._record_tool_result(request.session_id, result, request.received_at)
            results.append(AssistantToolResult(call.call_id, call.name, {"status": result.status, "output": result.output, "warnings": list(result.warnings)}))
            if result.status == "success":
                executed.append(call.name)
        if len(provider_response.tool_calls) > max_calls:
            warnings = (*warnings, "tool call limit reached")
        self._metrics.increment("gaon_llm_tool_roundtrips_total", amount=len(results), provider=provider_response.provider_name)
        self._append_provider_event("LLMProviderToolRoundtripCompleted", request, {"provider": provider_response.provider_name, "tool_calls": len(results)})
        try:
            final = validate_provider_response(
                provider.respond(
                    AssistantRequest(
                        text=request.text,
                        intent=intent,
                        user_id=request.user_ref,
                        conversation_id=request.session_id,
                        received_at=request.received_at,
                        prompt=_base_prompt(request.text, None),
                        references=_dedupe((*references, *(f"tool:{name}" for name in executed))),
                        tools=tools,
                        tool_results=tuple(results),
                    )
                ),
                max_chars=self._config.assistant_max_output_tokens * 8,
            )
        except ProviderError as exc:
            reason = exc.__class__.__name__
            self._metrics.increment("gaon_llm_provider_fallbacks_total", reason=f"tool_roundtrip_{reason}")
            self._append_provider_event("LLMProviderToolRoundtripFailed", request, {"provider": provider_response.provider_name, "error_type": reason})
            text = _format_multi_tool_response(tuple(results))
            return text, "provider_tool_fallback", _dedupe((*warnings, f"provider fallback: {reason}")), _dedupe((*references, *(f"tool:{name}" for name in executed))), "deterministic", tuple(executed)
        if final.truncated:
            final = self._continue_provider_response(provider, request, intent, final, _dedupe((*references, *(f"tool:{name}" for name in executed))))
        text = final.text or _format_multi_tool_response(tuple(results))
        if any(is_research_tool(result.name) for result in results) and contains_unverified_fixture_metrics(text):
            text = _format_multi_tool_response(tuple(results))
            warnings = (*warnings, "provider research grounding fallback")
        return text, "provider_tool_call", _dedupe((*warnings, *final.warnings)), _dedupe((*references, *final.references, *(f"tool:{name}" for name in executed))), final.provider_name, tuple(executed)

    def _continue_provider_response(self, provider: AssistantProvider, request: LLMConversationRequest, intent: Intent, initial_response, references: tuple[str, ...]):
        parts = [initial_response.text]
        warnings = tuple(initial_response.warnings)
        current = initial_response
        count = 0
        while current.truncated and count < self._config.assistant_max_continuations:
            count += 1
            self._metrics.increment("gaon_llm_continuations_total", provider=initial_response.provider_name)
            self._append_provider_event("LLMProviderContinuationStarted", request, {"provider": initial_response.provider_name, "continuation": count})
            try:
                current = validate_provider_response(
                    provider.respond(
                        AssistantRequest(
                            text=request.text,
                            intent=intent,
                            user_id=request.user_ref,
                            conversation_id=request.session_id,
                            received_at=request.received_at,
                            prompt=continuation_prompt(request.text, merge_response_parts(tuple(parts))),
                            references=references,
                        )
                    ),
                    max_chars=self._config.assistant_max_output_tokens * 8,
                )
            except ProviderError as exc:
                reason = exc.__class__.__name__
                self._metrics.increment("gaon_llm_provider_fallbacks_total", reason=f"continuation_{reason}")
                self._append_provider_event("LLMProviderContinuationFailed", request, {"provider": initial_response.provider_name, "error_type": reason, "continuation": count})
                return _replace_provider_response(initial_response, merge_response_parts(tuple(parts)), (*warnings, f"continuation failed: {reason}"), truncated=True)
            parts.append(current.text)
            warnings = _dedupe((*warnings, *current.warnings))
            self._append_provider_event("LLMProviderContinuationCompleted", request, {"provider": current.provider_name, "finish_reason": current.finish_reason or "unknown", "truncated": current.truncated, "continuation": count})
        merged = merge_response_parts(tuple(parts))
        still_truncated = bool(current.truncated)
        if still_truncated:
            warnings = _dedupe((*warnings, "max continuations reached"))
            self._metrics.increment("gaon_llm_truncation_unresolved_total", provider=initial_response.provider_name)
        else:
            self._metrics.increment("gaon_llm_truncation_resolved_total", provider=initial_response.provider_name)
        return _replace_provider_response(initial_response, merged, warnings, truncated=still_truncated)

    def _try_deterministic_tool(self, request: LLMConversationRequest, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        if self._tool_executor is None:
            return None
        tool_name = route_read_only_tool(request.text)
        if tool_name is None:
            return None
        arguments = _default_tool_arguments(tool_name, request.text)
        result = self._tool_executor.execute(ToolRequest(tool_name, arguments, request.user_ref, request.received_at))
        self._record_tool_result(request.session_id, result, request.received_at)
        if result.status != "success":
            return persona_text(Intent.UNKNOWN), "tool_denied", _dedupe((*warnings, *result.warnings)), references, "deterministic", ()
        return _format_tool_response(tool_name, result.output), "tool_read_only", _dedupe(warnings), _dedupe((*references, f"tool:{tool_name}")), "deterministic", (tool_name,)

    def _try_follow_up_tool(self, request: LLMConversationRequest, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        if self._tool_result_repository is None or self._tool_executor is None:
            return None
        normalized = request.text.casefold()
        if not any(token in normalized for token in ("그", "그건", "그중", "최근", "언제", "자세히", "상세")):
            return None
        latest = self._tool_result_repository.latest(request.session_id)
        if latest is None:
            return None
        if latest.tool_name not in {"champion_status", "runtime_status", "v5_pipeline_history"}:
            return None
        arguments = _default_tool_arguments(latest.tool_name, request.text)
        result = self._tool_executor.execute(ToolRequest(latest.tool_name, arguments, request.user_ref, request.received_at))
        self._record_tool_result(request.session_id, result, request.received_at)
        if result.status != "success":
            return None
        return _format_follow_up_response(latest.tool_name, result.output), "tool_follow_up", _dedupe(warnings), _dedupe((*references, f"tool:{latest.tool_name}")), "deterministic", (latest.tool_name,)

    def _try_multi_result_synthesis(self, request: LLMConversationRequest, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        if self._tool_result_repository is None or self._tool_executor is None:
            return None
        if not _is_synthesis_request(request.text):
            return None
        required = _requested_synthesis_tools(request.text)
        recent_tools = self._tool_result_repository.list_recent(request.session_id, limit=10, tool_names=("champion_status", "runtime_status", "v5_pipeline_history"))
        if not required:
            required = tuple(dict.fromkeys(record.tool_name for record in recent_tools if record.status == "success"))
        if len(required) < 2 and not _is_explicit_reuse_request(request.text):
            return None
        if len(required) < 2:
            return _clarification_response(request, warnings, references)
        selected: dict[str, ConversationToolResultRecord] = {}
        executed: list[str] = []
        for tool_name in required[:3]:
            record = _latest_success(recent_tools, tool_name)
            if record is not None and _is_fresh(record, request.received_at):
                selected[tool_name] = record
                self._metrics.increment("gaon_llm_tool_result_reused_total", tool_name=tool_name)
                self._append_provider_event("LLMToolResultReused", request, {"tool_name": tool_name, "result_id": record.result_id})
                continue
            args: dict[str, object] = {"slot": "default"} if tool_name == "champion_status" else {"limit": 5} if tool_name == "v5_pipeline_history" else {}
            result = self._tool_executor.execute(ToolRequest(tool_name, args, request.user_ref, request.received_at))
            self._record_tool_result(request.session_id, result, request.received_at)
            if result.status != "success":
                continue
            executed.append(tool_name)
            selected[tool_name] = ConversationToolResultRecord(
                result_id=f"tool-result:live:{tool_name}",
                session_id=request.session_id,
                tool_name=tool_name,
                status=result.status,
                output=result.output,
                created_at=request.received_at,
                expires_at=_expires_at(tool_name, request.received_at),
            )
            self._metrics.increment("gaon_llm_tool_result_refreshed_total", tool_name=tool_name)
            self._append_provider_event("LLMToolResultRefreshed", request, {"tool_name": tool_name})
        if len(selected) < 2:
            return _clarification_response(request, warnings, references)
        ordered = tuple(selected[name] for name in required if name in selected)
        self._metrics.increment("gaon_llm_multi_result_contexts_total", amount=len(ordered))
        self._append_provider_event("LLMMultiResultContextBuilt", request, {"tools": [record.tool_name for record in ordered]})
        text, provider_name, provider_warnings = self._synthesize_tool_results(request, ordered)
        return (
            text,
            "tool_result_synthesis",
            _dedupe((*warnings, *provider_warnings)),
            _dedupe((*references, *(f"tool:{record.tool_name}" for record in ordered))),
            provider_name,
            tuple(executed),
        )

    def _synthesize_tool_results(self, request: LLMConversationRequest, records: tuple[ConversationToolResultRecord, ...]) -> tuple[str, str, tuple[str, ...]]:
        context = _synthesis_prompt(request.text, records)
        if self._config.assistant_provider == "deterministic":
            return _deterministic_synthesis(records), "deterministic", ()
        try:
            provider = self._assistant_provider or build_assistant_provider(self._config)
            self._metrics.increment("gaon_llm_synthesis_requests_total", provider=self._config.assistant_provider)
            self._append_provider_event("LLMSynthesisStarted", request, {"tools": [record.tool_name for record in records]})
            response = validate_provider_response(
                provider.respond(
                    AssistantRequest(
                        text=request.text,
                        intent=Intent.UNKNOWN,
                        user_id=request.user_ref,
                        conversation_id=request.session_id,
                        received_at=request.received_at,
                        prompt=context,
                        references=tuple(f"tool:{record.tool_name}" for record in records),
                    )
                ),
                max_chars=self._config.assistant_max_output_tokens * 8,
            )
            self._append_provider_event("LLMSynthesisCompleted", request, {"provider": response.provider_name})
            return response.text, response.provider_name, response.warnings
        except ProviderError as exc:
            reason = exc.__class__.__name__
            self._metrics.increment("gaon_llm_provider_fallbacks_total", reason=f"synthesis_{reason}")
            self._append_provider_event("LLMSynthesisFailed", request, {"error_type": reason})
            return _deterministic_synthesis(records), "deterministic", (f"provider fallback: {reason}",)

    def _record_tool_result(self, session_id: str, result, created_at: str) -> None:
        if self._tool_result_repository is None:
            return
        self._tool_result_repository.add(
            ConversationToolResultRecord(
                result_id=f"tool-result:{uuid4().hex}",
                session_id=session_id,
                tool_name=result.tool_name,
                status=result.status,
                output=result.output,
                created_at=created_at,
                expires_at=_expires_at(result.tool_name, created_at),
            )
        )

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

    def _append_provider_event(self, event_type: str, request: LLMConversationRequest, payload: dict[str, object]) -> None:
        if self._event_store is None:
            return
        self._event_store.append(
            DurableEvent(
                event_id=f"llm-provider:{uuid4().hex}",
                event_type=event_type,
                occurred_at=request.received_at,
                actor_ref="gaon:llm-provider",
                correlation_id=request.session_id,
                causation_id=request.message_id,
                scope="runtime",
                project="StrategyLab",
                strategy="N/A",
                market="N/A",
                payload=payload,
                evidence_refs=(),
                audit_refs=(),
                appended_at=request.received_at,
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


def _base_prompt(text: str, context=None) -> str:
    context_text = f"\n\n{context.to_prompt_context()}" if context is not None else ""
    return (
        "You are Gaon, a calm Korean AI Engineering Partner for Youngha. "
        "Do not claim live trading, automatic approval, private repo access, or unavailable integrations. "
        f"{grounded_system_policy()} "
        f"User message: {text}{context_text}"
    )


def _requires_manual_boundary(text: str) -> bool:
    normalized = text.casefold()
    blocked = (
        "approve",
        "approval",
        "buy",
        "sell",
        "order",
        "kis",
        "broker",
        "secret",
        "매수",
        "매도",
        "주문",
        "승인",
        "실거래",
        "자동 배포",
        "명령 실행",
        "shell",
        "powershell",
        "cmd",
        "sql",
    )
    return any(token in normalized for token in blocked)


def _metric_route(route: str) -> str:
    return route.replace("+", "_").replace("-", "_")[:48] or "unknown"


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _default_tool_arguments(tool_name: str, text: str) -> dict[str, object]:
    if tool_name == "champion_status":
        return {"slot": "default"}
    if tool_name == "v5_pipeline_history":
        return {"limit": 5}
    if tool_name == "strategy_critique":
        return {"scenario": "overfit"} if any(token in text for token in ("약점", "리스크", "위험", "과최적", "개선")) else {"scenario": "balanced"}
    if tool_name == "strategy_quality_score":
        return {"scenario": "balanced"}
    if tool_name == "research_memory_search":
        return {"query": text[:120]}
    if tool_name in {"data_quality_check", "backtest_strategy"}:
        return {"symbol": "005930"}
    return {}


def _format_tool_response(tool_name: str, output: dict[str, object]) -> str:
    grounded = format_grounded_tool_response(tool_name, output)
    if grounded is not None:
        return grounded
    if tool_name == "champion_status":
        if not output.get("active"):
            return "현재 등록된 활성 Champion은 없습니다, 영하님."
        strategy = output.get("strategy_ref") or "unknown"
        version = output.get("active_version_id") or "unknown"
        fingerprint = str(output.get("fingerprint") or "")
        short_fingerprint = fingerprint[:12] if fingerprint else "unknown"
        revision = output.get("revision") or "unknown"
        return f"현재 활성 Champion은 {strategy}이며 버전은 {version}입니다, 영하님.\n상태: active revision={revision}\nFingerprint: {short_fingerprint}"
    if tool_name == "runtime_status":
        schema = output.get("schema_version") or "unknown"
        ready = "정상 실행 중" if output.get("ready") else "확인 필요"
        return f"가온 Runtime은 {ready}입니다, 영하님.\nAssistant: enabled\nProvider: deterministic\nSchema: v{schema}"
    if tool_name == "v5_pipeline_history":
        runs = output.get("runs")
        if not isinstance(runs, list) or not runs:
            return "최근 v5 파이프라인 실행 이력이 없습니다, 영하님."
        lines = ["최근 v5 파이프라인 실행 이력입니다, 영하님."]
        for item in runs[:5]:
            if isinstance(item, dict):
                lines.append(f"- {item.get('run_id')} / {item.get('status')} / {item.get('current_stage')}")
        return "\n".join(lines)
    return "요청하신 읽기 전용 도구 결과를 확인했습니다, 영하님."


def _format_multi_tool_response(results: tuple[AssistantToolResult, ...]) -> str:
    grounded = [_format_tool_result_response(result) for result in results if result.result.get("status") == "success"]
    grounded = [item for item in grounded if item]
    if grounded:
        return "\n\n".join(grounded)
    successful = [result.name for result in results if result.result.get("status") == "success"]
    if successful:
        return f"요청하신 읽기 전용 도구 결과를 확인했습니다, 영하님.\n실행 도구: {', '.join(successful)}"
    return "요청하신 도구 호출은 안전 검증을 통과하지 못했습니다, 영하님."


def _format_tool_result_response(result: AssistantToolResult) -> str | None:
    output_wrapper = result.result.get("output")
    if not isinstance(output_wrapper, dict):
        return None
    return format_grounded_tool_response(result.name, output_wrapper)


def _provider_unavailable_message() -> str:
    return "현재 로컬 LLM 응답이 지연되고 있습니다, 영하님. 잠시 후 다시 시도해 주세요."


def _is_synthesis_request(text: str) -> bool:
    normalized = text.casefold()
    return any(
        token in normalized
        for token in (
            "종합",
            "비교",
            "정리",
            "설명",
            "방금",
            "내용",
            "아까",
            "앞에서",
            "醫낇빀",
            "媛숈씠",
            "鍮꾧탳",
            "諛⑷툑",
            "?댁슜",
            "?ㅻ챸",
        )
    )


def _is_explicit_reuse_request(text: str) -> bool:
    normalized = text.casefold()
    return any(token in normalized for token in ("그거", "그건", "방금", "아까", "내용", "諛⑷툑", "洹", "?댁슜"))


def _requested_synthesis_tools(text: str) -> tuple[str, ...]:
    normalized = text.casefold()
    tools: list[str] = []
    if any(token in normalized for token in ("챔피언", "champion", "梨뷀뵾")):
        tools.append("champion_status")
    if any(token in normalized for token in ("v5", "파이프라인", "pipeline", "?뚯씠?꾨씪")):
        tools.append("v5_pipeline_history")
    if any(token in normalized for token in ("가온", "runtime", "런타임", "서버", "媛??", "?고??")):
        tools.append("runtime_status")
    return tuple(dict.fromkeys(tools))


def _latest_success(records: tuple[ConversationToolResultRecord, ...], tool_name: str) -> ConversationToolResultRecord | None:
    for record in records:
        if record.tool_name == tool_name and record.status == "success":
            return record
    return None


def _is_fresh(record: ConversationToolResultRecord, now: str) -> bool:
    try:
        return _parse_utc(record.expires_at) >= _parse_utc(now)
    except ValueError:
        return False


def _expires_at(tool_name: str, created_at: str) -> str:
    ttl = TOOL_RESULT_TTL_SECONDS.get(tool_name, 300)
    return (_parse_utc(created_at) + timedelta(seconds=ttl)).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clarification_response(request: LLMConversationRequest, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]:
    return (
        "영하님, 어떤 결과들을 함께 종합할지 조금 더 구체적으로 말씀해 주세요. 예를 들어 '챔피언과 v5 파이프라인을 같이 설명해줘'처럼 요청하시면 됩니다.",
        "tool_result_clarification",
        _dedupe(warnings),
        references,
        "deterministic",
        (),
    )


def _synthesis_prompt(user_text: str, records: tuple[ConversationToolResultRecord, ...]) -> str:
    lines = [
        "You are Gaon, Youngha's Korean AI Engineering Partner.",
        "Use only the verified tool facts below.",
        grounded_system_policy(),
        "Do not expose hidden reasoning, raw JSON, secrets, or unsupported claims.",
        "Explain concisely in natural Korean.",
        "Distinguish active Champion state from v5 pipeline or pending promotion state.",
        "",
        "Recent verified tool results:",
    ]
    for record in records:
        lines.append(f"[{record.tool_name}] created_at={record.created_at} expires_at={record.expires_at}")
        lines.append(dumps_json(record.output))
    lines.extend(("", f"User request: {user_text}"))
    return "\n".join(lines)


def _deterministic_synthesis(records: tuple[ConversationToolResultRecord, ...]) -> str:
    by_tool = {record.tool_name: record.output for record in records}
    lines = ["영하님, 방금 확인한 결과를 종합하면 다음과 같습니다."]
    champion = by_tool.get("champion_status")
    if champion:
        if champion.get("active"):
            lines.append(f"현재 활성 Champion은 {champion.get('strategy_ref') or 'unknown'}이며 버전은 {champion.get('active_version_id') or 'unknown'}입니다.")
        else:
            lines.append("현재 등록된 활성 Champion은 없습니다.")
    pipeline = by_tool.get("v5_pipeline_history")
    if pipeline:
        runs = pipeline.get("runs")
        if isinstance(runs, list) and runs:
            first = runs[0]
            if isinstance(first, dict):
                lines.append(f"최근 v5 파이프라인은 {first.get('run_id')} 실행이 {first.get('status')} 상태이며 현재 단계는 {first.get('current_stage')}입니다.")
        else:
            lines.append("최근 v5 파이프라인 실행 이력은 없습니다.")
    runtime = by_tool.get("runtime_status")
    if runtime:
        ready = "정상 실행 중" if runtime.get("ready") else "확인 필요"
        lines.append(f"가온 Runtime은 {ready}이며 schema는 v{runtime.get('schema_version') or 'unknown'}입니다.")
    lines.append("즉, 위 내용은 저장된 기억이 아니라 방금 검증된 읽기 전용 도구 결과를 기준으로 정리한 것입니다.")
    return "\n".join(lines)


def _format_follow_up_response(tool_name: str, output: dict[str, object]) -> str:
    if tool_name == "champion_status":
        if not output.get("active"):
            return "그 Champion 상태를 다시 확인했지만 현재 활성 Champion은 없습니다, 영하님."
        return f"그 Champion은 {output.get('updated_at', 'unknown')} 기준으로 확인된 최신 활성 상태입니다, 영하님.\n{_format_tool_response(tool_name, output)}"
    if tool_name == "v5_pipeline_history":
        runs = output.get("runs")
        if isinstance(runs, list) and runs:
            first = runs[0]
            if isinstance(first, dict):
                return f"그중 가장 최근 실행은 {first.get('run_id')}이며 상태는 {first.get('status')}, 단계는 {first.get('current_stage')}입니다, 영하님."
        return _format_tool_response(tool_name, output)
    if tool_name == "runtime_status":
        return f"방금 다시 확인한 Runtime 상태입니다, 영하님.\n{_format_tool_response(tool_name, output)}"
    return _format_tool_response(tool_name, output)


def _replace_provider_response(response: AssistantProviderResponse, text: str, warnings: tuple[str, ...], *, truncated: bool) -> AssistantProviderResponse:
    return AssistantProviderResponse(
        text=text,
        route=response.route,
        references=response.references,
        warnings=_dedupe(warnings),
        provider_name=response.provider_name,
        model=response.model,
        latency_ms=response.latency_ms,
        usage=response.usage,
        tool_calls=response.tool_calls,
        finish_reason=response.finish_reason,
        truncated=truncated,
    )
