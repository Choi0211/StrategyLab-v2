"""Gaon LLM conversation brain with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
import re
import sqlite3
from typing import Protocol
from uuid import uuid4

from gaon.runtime.assistant_provider import AssistantProvider, AssistantProviderResponse, AssistantRequest, AssistantToolResult, ProviderError, validate_provider_response
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.conversational_mvp import (
    ConversationalMVPContext,
    ConversationalMVPIntent,
    ConversationalRoute,
    ExplanationLevel,
    PresentationPreference,
    classify_conversational_route,
    explanation_level_for_text,
    presentation_preference_for_text,
    render_presentation_from_payloads,
    render_reasoning_from_payloads,
    render_rerun_boundary,
    render_follow_up,
    render_greeting,
    render_help,
    render_missing_context,
    render_single_symbol_summary,
    render_status,
    render_symbol_comparison,
    render_unknown,
)
from gaon.runtime.conversational_research_execution import (
    ConversationalResearchExecutionResult,
    build_conversational_research_execution_request,
    previous_request_text,
    render_data_quality_details_from_payloads,
    render_conversational_research_execution_result,
    render_research_execution_clarification,
)
from gaon.runtime.errors import ConfigurationError
from gaon.runtime.event_store import DurableEvent, SQLiteEventStore
from gaon.runtime.intents import Intent, parse_intent
from gaon.runtime.long_response import continuation_prompt, merge_response_parts
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.persona import RULE_BASED_ROUTE, persona_text, safety_warning
from gaon.runtime.provider_registry import build_assistant_provider
from gaon.runtime.research_grounding import contains_fixture_leakage, contains_ungrounded_real_research_claim, contains_unverified_fixture_metrics, contains_wrapper_tags, format_grounded_tool_response, grounded_system_policy, is_korean_request, is_research_tool, is_strict_real_research_tool, looks_like_english_final, normalize_final_response, sanitize_research_tool_output, strict_real_research_grounding_violations
from gaon.runtime.research_failures import classify_tool_failure, warning_for_failure
from gaon.runtime.serialization import dumps_json, loads_json
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest

CONVERSATION_SCHEMA_VERSION = 1
CONVERSATION_MVP_CONTEXT_VERSION = 1
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
    "krx_real_research": 300,
    "autonomous_research_cycle": 300,
    "autonomous_learning_research": 300,
    "multi_symbol_research": 300,
    "multi_symbol_research_status": 300,
    "multi_symbol_research_history": 300,
}
_AUTONOMOUS_CONTEXT_KINDS = frozenset(
    {
        "autonomous_research_cycle",
        "autonomous_continuation",
        "autonomous_learning_v2",
        "autonomous_learning_memory_summary",
        "autonomous_critique",
    }
)

logger = logging.getLogger(__name__)


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
        self._mvp_contexts: dict[str, ConversationalMVPContext] = {}

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
        response_text = normalize_final_response(response_text, request.text)
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
        session = self._repository.get_session(session.session_id)
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
        if approval_required and _is_autonomous_learning_boundary_request(request.text):
            mvp = self._try_conversational_mvp(request, (*warnings, "human approval boundary preserved"), references)
            if mvp is not None:
                return mvp
        if approval_required:
            if approval_required:
                warnings = (*warnings, "provider bypassed for approval boundary")
            return persona_text(intent), RULE_BASED_ROUTE, _dedupe(warnings), references, "deterministic", ()
        mvp = self._try_conversational_mvp(request, warnings, references)
        if mvp is not None:
            return mvp
        if not self._config.assistant_enabled:
            return persona_text(intent), RULE_BASED_ROUTE, _dedupe(warnings), references, "deterministic", ()
        authoritative = self._try_authoritative_research_tool(request, warnings, references)
        if authoritative is not None:
            return authoritative
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
            text = normalize_final_response(provider_response.text, request.text)
            if is_korean_request(request.text) and provider_response.text != text:
                warnings = (*warnings, "provider response normalized for Korean final answer")
            return (
                text,
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
            output = sanitize_research_tool_output(call.name, result.output, request.text) if result.status == "success" and is_research_tool(call.name) else result.output
            results.append(AssistantToolResult(call.call_id, call.name, {"status": result.status, "output": output, "warnings": list(result.warnings)}))
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
        raw_text = final.text or _format_multi_tool_response(tuple(results))
        text = raw_text
        strict_real_results = tuple(result for result in results if is_strict_real_research_tool(result.name))
        if strict_real_results:
            text = _format_multi_tool_response(tuple(results))
            if any(isinstance(result.result.get("output"), dict) and strict_real_research_grounding_violations(raw_text, result.result["output"]) for result in strict_real_results):
                warnings = (*warnings, "provider strict real research grounding fallback")
            else:
                warnings = (*warnings, "structured real research report preferred")
        elif any(is_research_tool(result.name) for result in results) and (
            contains_unverified_fixture_metrics(text)
            or contains_fixture_leakage(text)
            or (is_korean_request(request.text) and looks_like_english_final(text))
        ):
            text = _format_multi_tool_response(tuple(results))
            warnings = (*warnings, "provider research grounding fallback")
        elif contains_wrapper_tags(text):
            text = normalize_final_response(text, request.text)
        if any(is_research_tool(result.name) for result in results) and is_korean_request(request.text) and text != raw_text:
            warnings = (*warnings, "provider response normalized for Korean final answer")
        return text, "provider_tool_call", _dedupe((*warnings, *final.warnings)), _dedupe((*references, *final.references, *(f"tool:{name}" for name in executed))), final.provider_name, tuple(executed)

    def _try_authoritative_research_tool(self, request: LLMConversationRequest, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        if self._tool_executor is None:
            return None
        tool_name = route_read_only_tool(request.text)
        if tool_name is None or not is_strict_real_research_tool(tool_name):
            return None
        arguments = _default_tool_arguments(tool_name, request.text)
        result = self._tool_executor.execute(ToolRequest(tool_name, arguments, request.user_ref, request.received_at))
        self._record_tool_result(request.session_id, result, request.received_at)
        if result.status != "success":
            failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
            return (
                failure.user_message,
                f"research_failure_{failure.stage}",
                _dedupe((*warnings, *result.warnings, warning_for_failure(failure))),
                references,
                "deterministic",
                (tool_name,),
            )
        text = _format_tool_response(tool_name, result.output, request.text)
        violations = strict_real_research_grounding_violations(text, result.output)
        if violations:
            raise ConfigurationError("authoritative real research renderer violated grounding policy: " + ",".join(violations))
        return (
            text,
            "tool_read_only_authoritative",
            _dedupe((*warnings, "strict real research authoritative tool route")),
            _dedupe((*references, f"tool:{tool_name}")),
            "deterministic",
            (tool_name,),
        )

    def _try_conversational_mvp(self, request: LLMConversationRequest, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        if not _is_conversational_mvp_source(request):
            return None
        route = classify_conversational_route(request.text)
        if route.intent is ConversationalMVPIntent.UNKNOWN and _is_stored_research_explanation_followup(request.text):
            context = self._mvp_context_for(request.session_id)
            if context is not None:
                route = ConversationalRoute(ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, route.symbols)
        autonomous = self._try_autonomous_research_conversation(request, route, warnings, references)
        if autonomous is not None:
            return autonomous
        reasoning_followup_intents = {
            ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT,
            ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT,
            ConversationalMVPIntent.PROFESSIONAL_EXPLANATION,
            ConversationalMVPIntent.SHOW_DETAILS,
            ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION,
            ConversationalMVPIntent.RISK_QUESTION,
            ConversationalMVPIntent.STRATEGY_QUESTION,
            ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST,
            ConversationalMVPIntent.RERUN_REQUEST,
            ConversationalMVPIntent.RECOMMENDATION_REQUEST,
            ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP,
        }
        if not _contains_supported_conversational_mvp_token(request.text) and route.intent not in {
            ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT,
            ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT,
            ConversationalMVPIntent.PROFESSIONAL_EXPLANATION,
            ConversationalMVPIntent.SHOW_DETAILS,
            ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION,
            ConversationalMVPIntent.RISK_QUESTION,
            ConversationalMVPIntent.STRATEGY_QUESTION,
            ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST,
            ConversationalMVPIntent.RERUN_REQUEST,
            ConversationalMVPIntent.RECOMMENDATION_REQUEST,
            ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP,
        }:
            return None
        existing_tool = route_read_only_tool(request.text)
        if existing_tool in {"research_retest", "multi_symbol_research", "multi_symbol_research_status", "multi_symbol_research_history", "champion_status", "runtime_status", "v5_pipeline_history"}:
            if not (
                route.intent in {ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST, ConversationalMVPIntent.RERUN_REQUEST}
                and self._mvp_context_for(request.session_id) is not None
            ):
                return None
        if route.intent in {ConversationalMVPIntent.SINGLE_SYMBOL_ANALYSIS, ConversationalMVPIntent.COMPARE_SYMBOLS} and not _is_simple_conversational_research_request(request.text):
            return None
        if route.intent is ConversationalMVPIntent.GREETING:
            self._remember_mvp_response_context(request, route.intent, "conversation_mvp_greeting")
            return render_greeting(), "conversation_mvp_greeting", _dedupe(warnings), references, "deterministic", ()
        if route.intent is ConversationalMVPIntent.HELP:
            self._remember_mvp_response_context(request, route.intent, "conversation_mvp_help")
            return render_help(), "conversation_mvp_help", _dedupe(warnings), references, "deterministic", ()
        if route.intent is ConversationalMVPIntent.STATUS_QUERY and _is_simple_conversational_status_request(request.text):
            self._remember_mvp_response_context(request, route.intent, "conversation_mvp_status")
            return render_status(), "conversation_mvp_status", _dedupe(warnings), references, "deterministic", ()
        if route.intent in reasoning_followup_intents:
            context = self._mvp_context_for(request.session_id)
            if context is None:
                if route.symbols and route.intent in {ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, ConversationalMVPIntent.RECOMMENDATION_REQUEST, ConversationalMVPIntent.RISK_QUESTION, ConversationalMVPIntent.STRATEGY_QUESTION} and self._tool_executor is not None:
                    result = self._execute_mvp_real_research(request, route.symbols[0].symbol)
                    if result.status != "success":
                        failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
                        return failure.user_message, f"research_failure_{failure.stage}", _dedupe((*warnings, *result.warnings, warning_for_failure(failure))), references, "deterministic", ("krx_real_research",)
                    preference = presentation_preference_for_text(request.text, self._presentation_preference_for(request.session_id))
                    text = render_presentation_from_payloads((result.output,), intent=route.intent, user_text=request.text, preference=preference)
                    self._remember_mvp_context(request, route.intent, (result.output,), text)
                    self._store_presentation_preference(request.session_id, preference, request)
                    return text, f"conversation_presentation_{route.intent.value}", _dedupe((*warnings, "evidence-bound natural presentation")), _dedupe((*references, "tool:krx_real_research")), "deterministic", ("krx_real_research",)
                if self._tool_result_repository is not None and self._tool_result_repository.latest(request.session_id) is not None and _is_explicit_tool_result_synthesis_request(request.text):
                    return None
                self._remember_mvp_response_context(request, route.intent, "conversation_mvp_missing_context")
                return render_missing_context(), "conversation_mvp_missing_context", _dedupe(warnings), references, "deterministic", ()
            preference = presentation_preference_for_text(request.text, self._presentation_preference_for(request.session_id))
            self._store_presentation_preference(request.session_id, preference, request)
            self._remember_mvp_response_context(request, route.intent, f"conversation_mvp_{route.intent.value}")
            if route.intent in {ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST, ConversationalMVPIntent.RERUN_REQUEST}:
                execution = self._try_conversational_research_execution(request, context, warnings, references)
                if execution is not None:
                    return execution
                return render_rerun_boundary(context, route.intent), f"conversation_mvp_{route.intent.value}", _dedupe((*warnings, "rerun request requires explicit authoritative rerun")), references, "deterministic", ()
            if _is_data_quality_detail_request(request.text):
                payloads = context.last_structured_results or context.last_payloads
                return render_data_quality_details_from_payloads(payloads), "conversation_research_quality_detail", _dedupe((*warnings, "stored research quality detail")), references, "deterministic", ()
            if context.last_result_kind in _AUTONOMOUS_CONTEXT_KINDS and _is_autonomous_presentation_intent(route.intent):
                response_route = f"conversation_autonomous_presentation_{route.intent.value}"
                self._remember_mvp_response_context(request, route.intent, response_route)
                return _render_autonomous_context_followup(context, route.intent, request.text), response_route, _dedupe((*warnings, "autonomous semantic context preserved")), references, "deterministic", ()
            if route.intent in {
                ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION,
                ConversationalMVPIntent.RISK_QUESTION,
                ConversationalMVPIntent.STRATEGY_QUESTION,
                ConversationalMVPIntent.RECOMMENDATION_REQUEST,
                ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP,
                ConversationalMVPIntent.PROFESSIONAL_EXPLANATION,
            }:
                if route.intent not in {ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, ConversationalMVPIntent.RECOMMENDATION_REQUEST} and not _is_natural_presentation_request(request.text):
                    level = explanation_level_for_text(request.text, route.intent)
                    return render_reasoning_from_payloads(context.last_structured_results or context.last_payloads, intent=route.intent, level=level, user_text=request.text), f"conversation_mvp_{route.intent.value}", _dedupe(warnings), references, "deterministic", ()
                return render_presentation_from_payloads(context.last_structured_results or context.last_payloads, intent=route.intent, user_text=request.text, preference=preference), f"conversation_presentation_{route.intent.value}", _dedupe((*warnings, "evidence-bound natural presentation")), references, "deterministic", ()
            return render_follow_up(context, route.intent, user_text=request.text, preference=preference), f"conversation_mvp_{route.intent.value}", _dedupe(warnings), references, "deterministic", ()
        if route.intent is ConversationalMVPIntent.SINGLE_SYMBOL_ANALYSIS:
            if self._tool_executor is None:
                return None
            if not route.symbols:
                return render_unknown(route.symbols), "conversation_mvp_invalid_symbol", _dedupe(warnings), references, "deterministic", ()
            result = self._execute_mvp_real_research(request, route.symbols[0].symbol)
            if result.status != "success":
                failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
                return failure.user_message, f"research_failure_{failure.stage}", _dedupe((*warnings, *result.warnings, warning_for_failure(failure))), references, "deterministic", ("krx_real_research",)
            text = render_single_symbol_summary(result.output, user_text=request.text)
            self._remember_mvp_context(request, route.intent, (result.output,), text)
            return text, "conversation_mvp_single_symbol", _dedupe((*warnings, "human readable deterministic research response")), _dedupe((*references, "tool:krx_real_research")), "deterministic", ("krx_real_research",)
        if route.intent is ConversationalMVPIntent.COMPARE_SYMBOLS:
            if self._tool_executor is None:
                return None
            if len(route.symbols) < 2:
                return render_unknown(route.symbols), "conversation_mvp_invalid_symbol", _dedupe(warnings), references, "deterministic", ()
            outputs: list[dict[str, object]] = []
            for symbol in route.symbols:
                result = self._execute_mvp_real_research(request, symbol.symbol)
                if result.status != "success":
                    outputs.append({"status": "failure", "symbol": symbol.symbol, "message": result.output.get("message")})
                    continue
                outputs.append(result.output)
            text = render_symbol_comparison(tuple(outputs), user_text=request.text)
            if any(output.get("status") == "failure" for output in outputs):
                route_name = "conversation_mvp_compare_partial_failure"
            else:
                self._remember_mvp_context(request, route.intent, tuple(outputs), text)
                route_name = "conversation_mvp_compare_symbols"
            return text, route_name, _dedupe((*warnings, "same-assumption symbol comparison")), _dedupe((*references, "tool:krx_real_research")), "deterministic", ("krx_real_research",)
        if route.intent is ConversationalMVPIntent.UNKNOWN and route.symbols:
            self._remember_mvp_response_context(request, route.intent, "conversation_mvp_unknown")
            return render_unknown(route.symbols), "conversation_mvp_unknown", _dedupe(warnings), references, "deterministic", ()
        return None

    def _try_autonomous_research_conversation(self, request: LLMConversationRequest, route, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        if self._tool_executor is None:
            return None
        context = self._mvp_context_for(request.session_id)
        if (
            context is not None
            and context.last_result_kind == "autonomous_learning_v2"
            and _is_promotion_candidate_presentation_request(request.text)
        ):
            response_route = f"conversation_autonomous_presentation_{route.intent.value}"
            self._remember_mvp_response_context(request, route.intent, response_route)
            return (
                _render_autonomous_context_followup(context, route.intent, request.text),
                response_route,
                _dedupe((*warnings, "promotion candidate context preserved")),
                references,
                "deterministic",
                (),
            )
        mode = _autonomous_request_mode(request.text)
        learning_mode = _autonomous_learning_request_mode(request.text)
        if learning_mode is not None:
            explicit_v2 = _has_explicit_autonomous_learning_v2_intent(request.text)
            active_v2_context = context is not None and context.last_result_kind == "autonomous_learning_v2"
            legacy_cycle_context = (
                context is not None
                and context.last_result_kind in _AUTONOMOUS_CONTEXT_KINDS
                and context.last_result_kind != "autonomous_learning_v2"
            )
            legacy_cycle_request = not explicit_v2 and mode in {"validate", "critique", "compare"} and context is not None
            legacy_cycle_continuation = mode == "continue" and legacy_cycle_context
            if learning_mode == "continue" and context is not None and not active_v2_context:
                pass
            elif not (
                legacy_cycle_request
                or legacy_cycle_continuation
            ):
                return self._try_autonomous_learning_v2_conversation(request, route, context, learning_mode, warnings, references)
        if mode is None:
            return None
        if mode == "learning_query":
            if context is None or context.last_result_kind not in _AUTONOMOUS_CONTEXT_KINDS:
                return "영하님, 현재 저장된 검증된 학습 기록은 없습니다. 먼저 종목이나 전략을 분석한 뒤 자율 연구를 실행해 주세요.", "conversation_autonomous_learning_empty", _dedupe(warnings), references, "deterministic", ()
            text = _render_autonomous_learning_query(context.last_detail_payload)
            self._remember_autonomous_learning_context(request, context, text)
            return text, "conversation_autonomous_learning_query", _dedupe((*warnings, "learning memory context read")), references, "deterministic", ()
        if context is None and not route.symbols:
            return "영하님, 직전 연구나 전략 맥락이 없습니다. 먼저 분석할 종목이나 전략을 말씀해 주세요.", "conversation_autonomous_missing_context", _dedupe((*warnings, "autonomous research requires structured context")), references, "deterministic", ()
        if context is None:
            return None
        if mode == "compare" and context.last_result_kind in _AUTONOMOUS_CONTEXT_KINDS:
            text = _render_autonomous_progress_comparison(context)
            self._remember_mvp_response_context(request, ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, "conversation_autonomous_progress_comparison")
            return text, "conversation_autonomous_progress_comparison", _dedupe((*warnings, "autonomous progression comparison grounded")), references, "deterministic", ()
        if mode == "compare" and len(route.symbols) >= 2:
            result = self._execute_mvp_multi_symbol_research(request, tuple(symbol.symbol for symbol in route.symbols), request.text, None, None)
            self._record_tool_result(request.session_id, result, request.received_at)
            if result.status != "success":
                failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
                return failure.user_message, f"research_failure_{failure.stage}", _dedupe((*warnings, *result.warnings, warning_for_failure(failure))), references, "deterministic", ("multi_symbol_research",)
            text = _format_tool_response("multi_symbol_research", result.output, request.text)
            self._remember_mvp_context(request, ConversationalMVPIntent.COMPARE_SYMBOLS, self._payloads_from_multi_symbol_result(result.output), text)
            return text, "conversation_autonomous_compare", _dedupe((*warnings, "autonomous compare routed to multi-symbol research")), _dedupe((*references, "tool:multi_symbol_research")), "deterministic", ("multi_symbol_research",)
        symbol = _resolve_autonomous_symbol(route, context)
        original_text = previous_request_text(context, request.text) if context is not None else request.text
        tool_args: dict[str, object] = {"request_text": original_text, "symbol": symbol, "mode": mode}
        continuation_state = _autonomous_continuation_state(context) if context is not None else {}
        if mode == "continue" and continuation_state:
            tool_args["continuation_state"] = continuation_state
        result = self._tool_executor.execute(ToolRequest("autonomous_research_cycle", tool_args, request.user_ref, request.received_at))
        self._record_tool_result(request.session_id, result, request.received_at)
        if result.status != "success":
            failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
            return failure.user_message, f"research_failure_{failure.stage}", _dedupe((*warnings, *result.warnings, warning_for_failure(failure))), references, "deterministic", ("autonomous_research_cycle",)
        result_output = _with_autonomous_progression(result.output, context, mode)
        text = _format_tool_response("autonomous_research_cycle", result_output, request.text)
        self._remember_autonomous_context(request, result_output, text, mode)
        audit = _as_dict(result_output.get("audit"))
        audit_warnings = (
            f"autonomous_intent={audit.get('resolved_intent', mode)}",
            f"autonomous_terminal={audit.get('terminal_state', 'unknown')}",
            f"candidate_count={audit.get('candidate_count', 0)}",
            f"retest_count={audit.get('retest_count', 0)}",
            "autonomous research cycle invoked",
        )
        return text, "conversation_autonomous_research_cycle", _dedupe((*warnings, *result.warnings, *audit_warnings)), _dedupe((*references, "tool:autonomous_research_cycle")), "deterministic", ("autonomous_research_cycle",)

    def _try_autonomous_learning_v2_conversation(self, request: LLMConversationRequest, route, context: ConversationalMVPContext | None, mode: str, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]:
        if context is None and not route.symbols:
            return "영하님, 직전 연구나 전략 맥락이 없습니다. 이어서 자율 연구할 종목을 먼저 삼성전자처럼 말씀해 주세요.", "conversation_autonomous_learning_missing_target", _dedupe((*warnings, "autonomous learning requires target")), references, "deterministic", ()
        symbol = _resolve_autonomous_symbol(route, context)
        original_text = previous_request_text(context, request.text) if context is not None else request.text
        result = self._tool_executor.execute(
            ToolRequest(
                "autonomous_learning_research",
                {"request_text": original_text, "symbol": symbol, "mode": mode},
                request.user_ref,
                request.received_at,
            )
        )
        self._record_tool_result(request.session_id, result, request.received_at)
        if result.status != "success":
            failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
            return failure.user_message, f"research_failure_{failure.stage}", _dedupe((*warnings, *result.warnings, warning_for_failure(failure))), references, "deterministic", ("autonomous_learning_research",)
        text = _format_tool_response("autonomous_learning_research", result.output, request.text)
        self._remember_autonomous_learning_v2_context(request, result.output, text)
        audit = _as_dict(result.output.get("autonomous_learning_v2"))
        audit_warnings = (
            "autonomous_learning_v2_invoked",
            f"promotion_status={result.output.get('promotion_status', 'unknown')}",
            f"human_gate_status={result.output.get('human_gate_status', 'unknown')}",
            f"external_research_state={audit.get('external_research_state', 'unknown')}",
        )
        return text, "conversation_autonomous_learning_v2", _dedupe((*warnings, *result.warnings, *audit_warnings)), _dedupe((*references, "tool:autonomous_learning_research")), "deterministic", ("autonomous_learning_research",)

    def _try_conversational_research_execution(self, request: LLMConversationRequest, context: ConversationalMVPContext, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        if self._tool_executor is None:
            return None
        execution_request = build_conversational_research_execution_request(request.text, context, received_at=request.received_at)
        if execution_request.requires_confirmation:
            return (
                render_research_execution_clarification(context, request.text),
                "conversation_research_execution_clarification",
                _dedupe((*warnings, "research execution requires explicit period")),
                references,
                "deterministic",
                (),
            )
        original_text = previous_request_text(context, request.text)
        if execution_request.comparison_requested or len(execution_request.symbols) > 1:
            result = self._execute_mvp_multi_symbol_research(request, tuple(execution_request.symbols), original_text, execution_request.start_date, execution_request.end_date)
            tool_calls = ("multi_symbol_research",)
            outputs = self._payloads_from_multi_symbol_result(result.output) if result.status == "success" else ()
        else:
            result = self._execute_mvp_real_research(request, execution_request.symbols[0], request_text=original_text, start_date=execution_request.start_date, end_date=execution_request.end_date)
            tool_calls = ("krx_real_research",)
            outputs = (result.output,) if result.status == "success" else ()
        if result.status != "success":
            failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
            return failure.user_message, f"research_failure_{failure.stage}", _dedupe((*warnings, *result.warnings, warning_for_failure(failure))), references, "deterministic", tool_calls
        if not outputs or any(not self._is_valid_research_payload(output) for output in outputs):
            invalid_result = ConversationalResearchExecutionResult(
                execution_status="invalid_result",
                symbols=execution_request.symbols,
                resolved_start_date=execution_request.start_date,
                resolved_end_date=execution_request.end_date,
                research_results=(),
                previous_results=context.last_structured_results or context.last_payloads,
                comparison={},
                data_quality=(),
                limitations=(),
                execution_evidence=("invalid_structured_tool_result",),
            )
            return (
                render_conversational_research_execution_result(invalid_result),
                "conversation_research_execution_invalid_result",
                _dedupe((*warnings, "invalid structured research result blocked")),
                references,
                "deterministic",
                tool_calls,
            )
        execution_result = ConversationalResearchExecutionResult(
            execution_status="success",
            symbols=execution_request.symbols,
            resolved_start_date=execution_request.start_date,
            resolved_end_date=execution_request.end_date,
            research_results=outputs,
            previous_results=context.last_structured_results or context.last_payloads,
            comparison=self._comparison_from_execution_output(result.output),
            data_quality=tuple(dict(output.get("quality")) for output in outputs if isinstance(output.get("quality"), dict)),
            limitations=self._limitations_from_execution_outputs(outputs),
            execution_evidence=("safe_tool_execution", "structured_authoritative_result", "previous_strategy_reused"),
        )
        text = render_conversational_research_execution_result(execution_result)
        self._remember_mvp_context(
            request,
            ConversationalMVPIntent.COMPARE_SYMBOLS if len(outputs) > 1 else ConversationalMVPIntent.SINGLE_SYMBOL_ANALYSIS,
            outputs,
            text,
        )
        return (
            text,
            "conversation_research_execution",
            _dedupe((*warnings, "authoritative conversational research re-execution")),
            _dedupe((*references, *[f"tool:{tool}" for tool in tool_calls])),
            "deterministic",
            tool_calls,
        )

    def _execute_mvp_real_research(self, request: LLMConversationRequest, symbol: str, *, request_text: str | None = None, start_date: str | None = None, end_date: str | None = None):
        arguments = {"request_text": request_text or request.text, "symbol": symbol}
        if start_date is not None:
            arguments["start_date"] = start_date
        if end_date is not None:
            arguments["end_date"] = end_date
        result = self._tool_executor.execute(ToolRequest("krx_real_research", arguments, request.user_ref, request.received_at))
        self._record_tool_result(request.session_id, result, request.received_at)
        return result

    def _execute_mvp_multi_symbol_research(self, request: LLMConversationRequest, symbols: tuple[str, ...], request_text: str, start_date: str | None, end_date: str | None):
        arguments: dict[str, object] = {"request_text": request_text, "symbols": symbols, "universe_type": "explicit"}
        if start_date is not None:
            arguments["start_date"] = start_date
        if end_date is not None:
            arguments["end_date"] = end_date
        result = self._tool_executor.execute(ToolRequest("multi_symbol_research", arguments, request.user_ref, request.received_at))
        self._record_tool_result(request.session_id, result, request.received_at)
        return result

    def _payloads_from_multi_symbol_result(self, output: dict[str, object]) -> tuple[dict[str, object], ...]:
        evidence = output.get("evidence")
        if isinstance(evidence, list):
            request_payload = output.get("request") if isinstance(output.get("request"), dict) else {}
            payloads: list[dict[str, object]] = []
            for item in evidence:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol") or "").strip()
                metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
                quality = item.get("quality") if isinstance(item.get("quality"), dict) else {
                    "status": item.get("quality_status", "unknown"),
                    "provider_gap_dates": list(item.get("provider_gap_dates", ())) if isinstance(item.get("provider_gap_dates", ()), list) else [],
                    "provider_ohlc_anomaly_dates": list(item.get("provider_ohlc_anomaly_dates", ())) if isinstance(item.get("provider_ohlc_anomaly_dates", ()), list) else [],
                    "provider_zero_volume_anomaly_dates": list(item.get("provider_zero_volume_anomaly_dates", ())) if isinstance(item.get("provider_zero_volume_anomaly_dates", ()), list) else [],
                    "blocking_findings": list(item.get("blocking_findings", ())) if isinstance(item.get("blocking_findings", ()), list) else [],
                    "findings": list(item.get("blocking_findings", ())) if isinstance(item.get("blocking_findings", ()), list) else [],
                }
                metadata = {
                    "source": item.get("source", request_payload.get("source", output.get("source", "unknown"))),
                    "start_date": item.get("start_date", request_payload.get("start_date", output.get("start_date"))),
                    "end_date": item.get("end_date", request_payload.get("end_date", output.get("end_date"))),
                    "fixture_backed": item.get("fixture_backed", request_payload.get("fixture_backed", output.get("fixture_backed"))),
                }
                payloads.append(
                    {
                        "dataset": {"symbols": [{"symbol": symbol, "name": symbol}], "metadata": metadata},
                        "quality": quality,
                        "backtest": {"metrics": metrics},
                        "request_text": output.get("request_text") or request_payload.get("request_text"),
                    }
                )
            return tuple(payloads)
        symbols = output.get("symbols")
        if isinstance(symbols, list):
            payloads: list[dict[str, object]] = []
            for item in symbols:
                if not isinstance(item, dict):
                    continue
                symbol = str(item.get("symbol", "unknown"))
                metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
                payloads.append(
                    {
                        "dataset": {
                            "symbols": [{"symbol": symbol, "name": symbol}],
                            "metadata": {
                                "source": output.get("source", "unknown"),
                                "start_date": output.get("start_date"),
                                "end_date": output.get("end_date"),
                                "fixture_backed": output.get("fixture_backed"),
                            },
                        },
                        "quality": {"status": item.get("quality_status", output.get("quality_status", "unknown"))},
                        "backtest": {"metrics": metrics},
                        "request_text": output.get("request_text"),
                    }
                )
            return tuple(payloads)
        return (output,)

    def _is_valid_research_payload(self, output: dict[str, object]) -> bool:
        dataset = output.get("dataset")
        if not isinstance(dataset, dict):
            return False
        symbols = dataset.get("symbols")
        if not isinstance(symbols, list) or not symbols or not isinstance(symbols[0], dict):
            return False
        symbol = str(symbols[0].get("symbol", "")).strip()
        if not symbol or symbol == "unknown":
            return False
        backtest = output.get("backtest")
        if not isinstance(backtest, dict) or not isinstance(backtest.get("metrics"), dict):
            return False
        metrics = backtest["metrics"]
        return any(key in metrics for key in ("trade_count", "total_return", "mdd", "win_rate", "profit_factor"))

    def _comparison_from_execution_output(self, output: dict[str, object]) -> dict[str, object]:
        if isinstance(output.get("aggregate"), dict):
            return dict(output["aggregate"])
        comparison: dict[str, object] = {}
        for key in ("aggregate_trade_count", "sample_confidence", "recommendation"):
            if key in output:
                comparison[key] = output[key]
        return comparison

    def _limitations_from_execution_outputs(self, outputs: tuple[dict[str, object], ...]) -> tuple[str, ...]:
        limitations: list[str] = []
        for output in outputs:
            quality = output.get("quality")
            if isinstance(quality, dict):
                for key in ("provider_gap_dates", "provider_ohlc_anomaly_dates", "provider_zero_volume_anomaly_dates", "unknown_missing_trading_dates", "zero_volume_dates"):
                    values = quality.get(key)
                    if isinstance(values, list) and values:
                        limitations.append(f"{key}: {', '.join(str(item) for item in values[:10])}")
                findings = quality.get("findings")
                if isinstance(findings, list):
                    for finding in findings:
                        if isinstance(finding, dict) and finding.get("message") is not None:
                            limitations.append(str(finding["message"]))
        return tuple(dict.fromkeys(limitations))

    def _presentation_preference_for(self, session_id: str) -> PresentationPreference:
        try:
            session = self._repository.get_session(session_id)
        except KeyError:
            return PresentationPreference()
        root = session.metadata.get("conversation_mvp")
        if not isinstance(root, dict):
            return PresentationPreference()
        raw = root.get("presentation_preference")
        if not isinstance(raw, dict):
            return PresentationPreference()
        return PresentationPreference.from_json(raw)

    def _store_presentation_preference(self, session_id: str, preference: PresentationPreference, request: LLMConversationRequest) -> None:
        try:
            session = self._repository.get_session(session_id)
        except KeyError:
            return
        metadata = dict(session.metadata)
        payload = _mvp_metadata_root(metadata)
        payload["presentation_preference"] = {
            **preference.to_json(),
            "updated_at": request.received_at,
        }
        metadata["conversation_mvp"] = payload
        self._repository.upsert_session(LLMConversationSession(session.session_id, session.user_ref, session.source, session.status, session.created_at, request.received_at, metadata))

    def _remember_mvp_context(self, request: LLMConversationRequest, intent: ConversationalMVPIntent, payloads: tuple[dict[str, object], ...], text: str) -> None:
        result_ids: list[str] = []
        symbols: list[str] = []
        sources: list[str] = []
        quality_statuses: list[str] = []
        fixture_backed = False
        for payload in payloads:
            backtest = payload.get("backtest")
            if isinstance(backtest, dict):
                result_id = backtest.get("result_id")
                if result_id is not None:
                    result_ids.append(str(result_id))
            dataset = payload.get("dataset")
            if isinstance(dataset, dict):
                raw_symbols = dataset.get("symbols")
                if isinstance(raw_symbols, list):
                    for item in raw_symbols:
                        if isinstance(item, dict) and item.get("symbol") is not None:
                            symbols.append(str(item["symbol"]))
                metadata = dataset.get("metadata")
                if isinstance(metadata, dict):
                    if metadata.get("source") is not None:
                        sources.append(str(metadata["source"]))
                    fixture_backed = fixture_backed or metadata.get("fixture_backed") is True
            quality = payload.get("quality")
            if isinstance(quality, dict) and quality.get("status") is not None:
                quality_statuses.append(str(quality["status"]))
        result_kind = "symbol_comparison" if intent is ConversationalMVPIntent.COMPARE_SYMBOLS or len(payloads) > 1 else "single_symbol_research"
        detail_payload: dict[str, object]
        if len(payloads) == 1:
            detail_payload = dict(payloads[0])
        else:
            detail_payload = {"results": [dict(payload) for payload in payloads]}
        self._mvp_contexts[request.session_id] = ConversationalMVPContext(
            last_intent=intent.value,
            last_symbols=tuple(dict.fromkeys(symbols)),
            last_result_kind=result_kind,
            last_research_result_ids=tuple(dict.fromkeys(result_ids)),
            last_rendered_result=text,
            last_payloads=payloads,
            last_structured_results=payloads,
            last_summary=text,
            last_detail_payload=detail_payload,
            last_source=",".join(dict.fromkeys(sources)) if sources else "unknown",
            last_fixture_backed=fixture_backed,
            last_quality_status=",".join(dict.fromkeys(quality_statuses)) if quality_statuses else "unknown",
            detail_level="summary",
            created_at=request.received_at,
            updated_at=request.received_at,
        )
        self._store_mvp_context(request.session_id, self._mvp_contexts[request.session_id], request, route=f"conversation_mvp_{intent.value}")

    def _remember_autonomous_context(self, request: LLMConversationRequest, payload: dict[str, object], text: str, mode: str) -> None:
        baseline = _as_dict(payload.get("baseline"))
        dataset = _as_dict(baseline.get("dataset"))
        metadata = _as_dict(dataset.get("metadata"))
        quality = _as_dict(baseline.get("quality"))
        symbol = str(payload.get("symbol") or _symbol_from_autonomous_payload(payload))
        source = str(payload.get("source") or metadata.get("source") or "unknown")
        result_kind = "autonomous_research_cycle"
        if mode == "continue":
            result_kind = "autonomous_continuation"
        elif mode == "critique":
            result_kind = "autonomous_critique"
        self._mvp_contexts[request.session_id] = ConversationalMVPContext(
            last_intent=f"autonomous_{mode}",
            last_symbols=(symbol,),
            last_result_kind=result_kind,
            last_research_result_ids=(str(payload.get("run_id", "autonomous-cycle")),),
            last_rendered_result=text,
            last_payloads=(payload,),
            last_structured_results=(payload,),
            last_summary=text,
            last_detail_payload=dict(payload),
            last_source=source,
            last_fixture_backed=bool(payload.get("fixture_backed", metadata.get("fixture_backed", False))),
            last_quality_status=str(payload.get("quality_status") or quality.get("status") or "unknown"),
            detail_level="summary",
            created_at=request.received_at,
            updated_at=request.received_at,
        )
        self._store_mvp_context(request.session_id, self._mvp_contexts[request.session_id], request, route="conversation_autonomous_research_cycle")

    def _remember_autonomous_learning_v2_context(self, request: LLMConversationRequest, payload: dict[str, object], text: str) -> None:
        baseline = _as_dict(payload.get("baseline"))
        dataset = _as_dict(baseline.get("dataset"))
        metadata = _as_dict(dataset.get("metadata"))
        quality = _as_dict(baseline.get("quality"))
        symbol = str(payload.get("symbol") or "005930")
        source = str(payload.get("source") or metadata.get("source") or "unknown")
        self._mvp_contexts[request.session_id] = ConversationalMVPContext(
            last_intent="autonomous_learning_v2",
            last_symbols=(symbol,),
            last_result_kind="autonomous_learning_v2",
            last_research_result_ids=(str(payload.get("run_id") or payload.get("selected_orchestration") or "autonomous-learning-v2"),),
            last_rendered_result=text,
            last_payloads=(payload,),
            last_structured_results=(payload,),
            last_summary=text,
            last_detail_payload=dict(payload),
            last_source=source,
            last_fixture_backed=bool(payload.get("fixture_backed", metadata.get("fixture_backed", False))),
            last_quality_status=str(payload.get("quality_status") or quality.get("status") or "unknown"),
            detail_level="summary",
            created_at=request.received_at,
            updated_at=request.received_at,
        )
        self._store_mvp_context(request.session_id, self._mvp_contexts[request.session_id], request, route="conversation_autonomous_learning_v2")

    def _remember_autonomous_learning_context(self, request: LLMConversationRequest, context: ConversationalMVPContext, text: str) -> None:
        self._mvp_contexts[request.session_id] = ConversationalMVPContext(
            last_intent="autonomous_learning_query",
            last_symbols=context.last_symbols,
            last_result_kind="autonomous_learning_memory_summary",
            last_research_result_ids=context.last_research_result_ids,
            last_rendered_result=text,
            last_payloads=context.last_payloads,
            last_structured_results=context.last_structured_results,
            last_summary=text,
            last_detail_payload=dict(context.last_detail_payload),
            last_source=context.last_source,
            last_fixture_backed=context.last_fixture_backed,
            last_quality_status=context.last_quality_status,
            detail_level=context.detail_level,
            created_at=context.created_at,
            updated_at=request.received_at,
        )
        self._store_mvp_context(request.session_id, self._mvp_contexts[request.session_id], request, route="conversation_autonomous_learning_query")

    def _mvp_context_for(self, session_id: str) -> ConversationalMVPContext | None:
        context = self._mvp_contexts.get(session_id)
        if context is not None:
            return context
        try:
            session = self._repository.get_session(session_id)
        except KeyError:
            return None
        context = _mvp_context_from_metadata(session.metadata)
        if context is not None:
            self._mvp_contexts[session_id] = context
        return context

    def _remember_mvp_response_context(self, request: LLMConversationRequest, intent: ConversationalMVPIntent, route: str) -> None:
        try:
            session = self._repository.get_session(request.session_id)
        except KeyError:
            return
        metadata = dict(session.metadata)
        payload = _mvp_metadata_root(metadata)
        payload["last_response_context"] = {
            "last_intent": intent.value,
            "last_text": _bounded_context_text(request.text),
            "detail_level": "detail" if intent is ConversationalMVPIntent.SHOW_DETAILS else "summary",
            "route": route,
            "updated_at": request.received_at,
        }
        metadata["conversation_mvp"] = payload
        self._repository.upsert_session(LLMConversationSession(session.session_id, session.user_ref, session.source, session.status, session.created_at, request.received_at, metadata))

    def _store_mvp_context(self, session_id: str, context: ConversationalMVPContext, request: LLMConversationRequest, *, route: str) -> None:
        try:
            session = self._repository.get_session(session_id)
        except KeyError:
            return
        metadata = dict(session.metadata)
        payload = _mvp_metadata_root(metadata)
        payload["last_research_context"] = _mvp_context_to_json(context)
        payload["last_response_context"] = {
            "last_intent": context.last_intent,
            "last_text": _bounded_context_text(request.text),
            "detail_level": context.detail_level,
            "route": route,
            "updated_at": request.received_at,
        }
        metadata["conversation_mvp"] = payload
        self._repository.upsert_session(LLMConversationSession(session.session_id, session.user_ref, session.source, session.status, session.created_at, request.received_at, metadata))
        logger.debug(
            "conversation mvp context updated",
            extra={
                "context_key_hash": _context_key_hash(session_id),
                "last_result_kind": context.last_result_kind,
                "context_updated": True,
                "renderer_selected": route,
            },
        )

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
        return _format_tool_response(tool_name, result.output, request.text), "tool_read_only", _dedupe(warnings), _dedupe((*references, f"tool:{tool_name}")), "deterministic", (tool_name,)

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
    compact = "".join(normalized.split())
    if _safe_boundary_negation(compact):
        return False
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


def _is_autonomous_learning_boundary_request(text: str) -> bool:
    normalized = text.casefold()
    if any(token in normalized for token in ("매수", "매도", "주문", "buy", "sell", "order", "broker", "kis", "shell", "powershell", "cmd", "sql", "secret")):
        return False
    return _autonomous_learning_request_mode(text) is not None


def _safe_boundary_negation(value: str) -> bool:
    safety_terms = ("자동주문", "champion자동승격", "승인없는config변경", "승인없는", "nolivetrading", "noapprovalbypass", "nobroker", "nokis")
    negation_terms = ("하지마", "하지말", "하지말고", "하지않", "금지", "없는", "no", "not", "without")
    return any(term in value for term in safety_terms) and any(term in value for term in negation_terms)


def _is_conversational_mvp_source(request: LLMConversationRequest) -> bool:
    return (
        (request.source == "telegram" and str(request.message_id or "").startswith("telegram:"))
        or request.session_id.startswith("gaon-conversation-release-check:")
        or request.session_id.startswith("gaon-conversation-context-release-check:")
        or request.session_id.startswith("gaon-conversational-reasoning-release-check:")
        or request.session_id.startswith("gaon-natural-conversation-release-check:")
        or request.session_id.startswith("gaon-presentation-integrity-release-check:")
        or request.session_id.startswith("gaon-conversational-research-execution-release-check:")
        or request.session_id.startswith("gaon-conversational-reexecution-integrity-release-check:")
    )


def _contains_supported_conversational_mvp_token(text: str) -> bool:
    tokens = (
        "\uc548\ub155",
        "\uc548\ub155\ud558\uc138\uc694",
        "\uac00\uc628\uc544",
        "\ub3c4\uc6c0\ub9d0",
        "\uc0bc\uc131\uc804\uc790",
        "SK\ud558\uc774\ub2c9\uc2a4",
        "SK \ud558\uc774\ub2c9\uc2a4",
        "\ud604\ub300\ucc28",
        "\ub124\uc774\ubc84",
        "LG\ud654\ud559",
        "\ubd84\uc11d\ud574\uc918",
        "\ube44\uad50\ud574\uc918",
        "\ube44\uaca8",
        "sk\ud558\uc774\ub2cf\uc2a4",
        "\ub370\uc774\ud130 \ubb38\uc81c",
        "\ub204\ub77d \ub0a0\uc9dc",
        "\ud488\uc9c8 \ubb38\uc81c",
        "\uc65c \uadf8\ub807\uac8c",
        "\uc65c \uadf8\uc808",
        "\ud310\uac04",
        "\uc774\uc720\uac00 \ubb50\uc57c",
        "\uc27d\uac8c",
        "\uc27d\uac1c",
        "\uac04\ub2e8\ud558\uac8c",
        "\uc790\uc138\ud788",
        "\uc790\uc138\ud558\uac8c",
        "\uc0c1\uc138\ud788",
        "\uc6d0\ubcf8",
        "\uc804\uccb4 \uacb0\uacfc",
        "\uc9c0\uae08 \uc0ac\ub3c4",
        "\ub9e4\uc218\ud574\ub3c4",
        "\ucd94\ucc9c",
        "\uc704\ud5d8",
        "\ub9ac\uc2a4\ud06c",
        "\uc804\ub7b5",
        "\uc804\ubb38\uc801\uc73c\ub85c",
        "\ub2e4\uc2dc \ubd84\uc11d",
        "\ub2e4\uc2dc \uac80\uc99d",
        "\ub2e4\uc2dc \ud574\ubd10",
        "\ub354 \uae34 \uae30\uac04",
        "\ub354 \uae38\uac8c",
        "\uae30\uac04 \ub298\ub824",
        "\uae30\uac04\ub9cc \ubc14\uafd4",
        "\uac19\uc740 \uc870\uac74",
        "\ucd5c\uadfc 5\ub144",
        "3\ub144",
        "5\ub144",
        "\uae30\uac04",
        "\ud55c \uc904",
        "\uc9e7\uac8c",
        "\ube44\uc720",
        "\uc608\ub97c \ub4e4\uc5b4",
        "\uc804\ubb38\uc6a9\uc5b4 \ube7c",
        "\ubcf4\uace0\uc11c",
        "\ud45c\ub85c",
        "\uc870\uae08 \ub354 \uc790\uc138",
    )
    normalized = text.casefold()
    return any(token.casefold() in normalized for token in tokens)


def _is_data_quality_detail_request(text: str) -> bool:
    normalized = text.casefold()
    return any(
        token in normalized
        for token in (
            "\ub370\uc774\ud130 \ubb38\uc81c",
            "\ub370\uc774\ud130 \ud488\uc9c8",
            "\ud488\uc9c8 \ubb38\uc81c",
            "\ub204\ub77d \ub0a0\uc9dc",
            "\ub204\ub77d\ub41c \ub0a0\uc9dc",
            "quality detail",
            "data quality",
            "missing date",
        )
    )


def _is_natural_presentation_request(text: str) -> bool:
    tokens = (
        "\ud55c \uc904",
        "1\uc904",
        "\uc9e7\uac8c",
        "\uac04\ub2e8\ud788",
        "\ub300\ud654\ucc98\ub7fc",
        "\uc790\uc5f0\uc2a4\ub7fd\uac8c",
        "\ube44\uc720",
        "\uc608\ub97c \ub4e4\uc5b4",
        "\uc804\ubb38\uc6a9\uc5b4 \ube7c",
        "\uc26c\uc6b4 \ud45c\ud604",
        "\ud45c\ub85c",
        "\uc870\uae08 \ub354 \uc9e7\uac8c",
        "\uc790\uc138\ud788 \ubcf4\uc5ec\uc918",
    )
    normalized = text.casefold()
    return any(token.casefold() in normalized for token in tokens)


def _is_stored_research_explanation_followup(text: str) -> bool:
    normalized = re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
    if not normalized:
        return False
    topics = (
        "oos",
        "outofsample",
        "walkforward",
        "\uc6cc\ud06c\ud3ec\uc6cc\ub4dc",
        "\uac70\ub798\ube44\uc6a9",
        "transactioncost",
        "\ubaac\ud14c\uce74\ub97c\ub85c",
        "montecarlo",
        "\uc2dc\uc7a5\uad6d\uba74",
        "\ub808\uc9d0",
        "regime",
        "\ud30c\ub77c\ubbf8\ud130\ubbfc\uac10\ub3c4",
        "\ub2e4\ub978\uc885\ubaa9",
        "\uc678\ubd80\uadfc\uac70",
        "\uc678\ubd80\uc5f0\uad6c",
    )
    explainers = (
        "\ubb50\uc57c",
        "\uc65c",
        "\ubb34\uc2a8\ub73b",
        "\uc124\uba85",
        "\ubb38\uc81c",
        "\uc57d\ud574",
        "\ubcf4\uc5ec\uc918",
        "why",
        "what",
        "explain",
    )
    return any(token in normalized for token in topics) and (
        any(token in normalized for token in explainers) or len(normalized) <= 32
    )


def _mvp_metadata_root(metadata: dict[str, object]) -> dict[str, object]:
    existing = metadata.get("conversation_mvp")
    if isinstance(existing, dict) and existing.get("schema_version") == CONVERSATION_MVP_CONTEXT_VERSION:
        return dict(existing)
    return {"schema_version": CONVERSATION_MVP_CONTEXT_VERSION}


def _mvp_context_to_json(context: ConversationalMVPContext) -> dict[str, object]:
    return {
        "last_intent": context.last_intent,
        "last_symbols": list(context.last_symbols),
        "last_result_kind": context.last_result_kind,
        "last_research_result_ids": list(context.last_research_result_ids),
        "last_rendered_result": _bounded_context_text(context.last_rendered_result),
        "last_payloads": list(context.last_payloads),
        "last_structured_results": list(context.last_structured_results),
        "last_summary": _bounded_context_text(context.last_summary),
        "last_detail_payload": dict(context.last_detail_payload),
        "last_source": context.last_source,
        "last_fixture_backed": context.last_fixture_backed,
        "last_quality_status": context.last_quality_status,
        "detail_level": context.detail_level,
        "created_at": context.created_at,
        "updated_at": context.updated_at,
    }


def _mvp_context_from_metadata(metadata: dict[str, object]) -> ConversationalMVPContext | None:
    root = metadata.get("conversation_mvp")
    if not isinstance(root, dict) or root.get("schema_version") != CONVERSATION_MVP_CONTEXT_VERSION:
        return None
    raw = root.get("last_research_context")
    if not isinstance(raw, dict):
        return None
    try:
        return ConversationalMVPContext(
            last_intent=str(raw["last_intent"]),
            last_symbols=_tuple_of_str(raw.get("last_symbols")),
            last_result_kind=str(raw["last_result_kind"]),
            last_research_result_ids=_tuple_of_str(raw.get("last_research_result_ids")),
            last_rendered_result=str(raw.get("last_rendered_result", "")),
            last_payloads=_tuple_of_dict(raw.get("last_payloads")),
            last_structured_results=_tuple_of_dict(raw.get("last_structured_results")),
            last_summary=str(raw.get("last_summary", "")),
            last_detail_payload=dict(raw.get("last_detail_payload")) if isinstance(raw.get("last_detail_payload"), dict) else {},
            last_source=str(raw.get("last_source", "unknown")),
            last_fixture_backed=bool(raw.get("last_fixture_backed", False)),
            last_quality_status=str(raw.get("last_quality_status", "unknown")),
            detail_level=str(raw.get("detail_level", "summary")),
            created_at=str(raw.get("created_at", "")),
            updated_at=str(raw.get("updated_at", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _tuple_of_dict(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, dict))


def _tuple_of_str(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item) for item in value)


def _bounded_context_text(text: str) -> str:
    return text[:4000]


def _context_key_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:12]


def _is_explicit_tool_result_synthesis_request(text: str) -> bool:
    normalized = text.casefold()
    return any(token in normalized for token in ("방금", "앞에서", "이전", "최근", "종합", "summary", "previous"))


def _is_simple_conversational_research_request(text: str) -> bool:
    if "\n" in text or len(text.strip()) > 80:
        return False
    blocked_detail_terms = ("아래 전략", "손절", "청산", "충분한 표본", "기간을 확장", "TESTED", "Champion", "자동 재검증")
    return not any(token.casefold() in text.casefold() for token in blocked_detail_terms)


def _is_simple_conversational_status_request(text: str) -> bool:
    normalized = text.strip().casefold()
    if len(normalized) > 40:
        return False
    tool = route_read_only_tool(text)
    return tool is None


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
    if tool_name == "krx_real_research":
        return {"request_text": text, "symbol": "005930"}
    if tool_name == "research_retest":
        return {"request_text": text, "symbol": "005930"}
    if tool_name == "autonomous_research_cycle":
        return {"request_text": text, "symbol": "005930", "mode": _autonomous_request_mode(text) or "validate"}
    if tool_name == "autonomous_learning_research":
        return {"request_text": text, "symbol": "005930", "mode": _autonomous_learning_request_mode(text) or "research"}
    if tool_name == "multi_symbol_research":
        start_date, end_date = _extract_date_range(text)
        return {
            "request_text": text,
            "symbols": _extract_krx_symbols(text),
            "universe_type": "explicit",
            "start_date": start_date,
            "end_date": end_date,
        }
    if tool_name in {"multi_symbol_research_status", "multi_symbol_research_history"}:
        return {"limit": 5}
    if tool_name in {"data_quality_check", "backtest_strategy"}:
        return {"symbol": "005930"}
    return {}


def _extract_krx_symbols(text: str) -> tuple[str, ...]:
    known = {"005930", "000660", "005380", "035420", "051910"}
    symbols: list[str] = []
    for token in re.findall(r"(?<!\d)(\d{6})(?!\d)", text):
        if token in known and token not in symbols:
            symbols.append(token)
    return tuple(symbols) if symbols else ("005930", "000660", "005380", "035420", "051910")


def _extract_date_range(text: str) -> tuple[str, str]:
    dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
    if len(dates) >= 2:
        return dates[0], dates[1]
    return "2021-07-25", "2026-07-24"


def _autonomous_request_mode(text: str) -> str | None:
    normalized = re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
    if not normalized:
        return None
    learning = ("지금까지무엇을배웠", "지금까지뭘배웠", "무엇을배웠", "뭘배웠", "학습기록", "learningmemory", "whatlearned")
    critique = ("문제점을찾아", "문제점을찾아줘", "약점을분석", "약점", "취약", "개선해", "보완", "critic", "critique")
    compare = ("어느종목", "어떤종목", "더잘맞", "비교", "compare", "whichsymbol")
    continue_terms = ("계속연구", "더연구", "다음검증", "계속검증", "continue")
    validate = ("전략을검증", "전략검증", "검증해봐", "검증해줘", "추가검증", "표본이부족", "충분한표본", "근거가충분", "validate", "researchcycle")
    if any(token in normalized for token in learning):
        return "learning_query"
    if any(token in normalized for token in critique):
        return "critique"
    if any(token in normalized for token in compare) and any(token in normalized for token in ("전략", "연구", "검증", "strategy", "research")):
        return "compare"
    if any(token in normalized for token in continue_terms):
        return "continue"
    if any(token in normalized for token in validate) and any(token in normalized for token in ("전략", "연구", "분석", "백테스트", "삼성전자", "005930", "strategy", "research")):
        return "validate"
    return None


def _autonomous_learning_request_mode(text: str) -> str | None:
    normalized = re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
    if not normalized:
        return None
    if any(token in normalized for token in ("다중종목", "여러종목", "복수종목", "모든종목", "crosssymbol", "multisymbol", "multi-symbol")):
        return None
    if any(token in normalized for token in ("품질점수", "연구품질점수", "퀄리티", "quality", "score", "점수")):
        return None
    explicit_v2 = _has_explicit_autonomous_learning_v2_intent(text)
    memory_only = any(token in normalized for token in ("비슷한", "유사", "지난연구", "이전연구", "연구했", "기억", "메모리", "저장된", "memory"))
    if memory_only and not explicit_v2:
        return None
    approval = ("승인요청", "승격승인", "좋은전략후보", "가장좋은후보", "좋으면알아서적용", "좋으면적용", "알아서적용", "bestcandidate", "promotioncandidate")
    continuation = ("계속연구", "더연구", "추가연구", "자료를더", "근거를더", "continueresearch", "continuelearning")
    external = ("자료를찾아", "자료찾아", "연구자료", "연구자료를찾아", "외부연구자료", "외부자료", "근거자료", "evidence", "externalresearch", "findevidence")
    improvement = ("문제점을찾", "약점을찾", "후보를만", "다시연구", "처음부터다시연구", "처음부터다시연구해")
    learning = ("지금까지배운", "배운내용", "학습내용", "learningmemory")
    robustness = ("oos", "outofsample", "워크포워드", "walkforward", "walk-forward", "시장국면", "레짐", "regime", "파라미터민감도", "거래비용", "transactioncost", "몬테카를로", "montecarlo", "monte-carlo", "robustness")
    plain_start = ("전략연구", "전략을연구", "전략연구해", "autonomousresearch", "autonomouslearning")
    subject = ("삼성전자", "005930", "전략", "연구", "검증", "백테스트", "실제", "시장데이터", "strategy", "research", "validate")
    if any(token in normalized for token in approval):
        return "approval_review"
    if any(token in normalized for token in learning) and any(token in normalized for token in ("바탕", "기반", "개선", "검증", "전략", "research", "strategy")):
        return "research"
    if any(token in normalized for token in external) and any(token in normalized for token in subject):
        return "external_research"
    if any(token in normalized for token in continuation):
        return "continue"
    if any(token in normalized for token in improvement) and any(token in normalized for token in subject):
        return "research"
    if any(token in normalized for token in robustness) and any(token in normalized for token in subject):
        return "research"
    if any(token in normalized for token in plain_start) and not any(token in normalized for token in ("백테스트", "실제데이터", "실제시장데이터", "다중종목", "여러종목", "재검증", "검증해봐")):
        return "research"
    return None


def _has_explicit_autonomous_learning_v2_intent(text: str) -> bool:
    normalized = re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
    if not normalized:
        return False
    signals = (
        "처음부터다시연구",
        "외부자료",
        "외부연구",
        "외부연구자료",
        "자료를찾아",
        "자료를찾아서연구",
        "연구자료를찾아",
        "지금까지의연구기억",
        "연구기억",
        "지금까지배운내용",
        "지금까지배운",
        "배운내용",
        "개선전략후보",
        "전략후보",
        "후보전략",
        "가장좋은후보",
        "좋은전략후보",
        "승격승인",
        "승인요청",
        "전략을만들어서검증",
        "전략을만들어검증",
        "후보를만들고",
        "후보를만들어",
        "승인직전",
        "oos",
        "outofsample",
        "워크포워드",
        "walkforward",
        "walk-forward",
        "시장국면",
        "레짐",
        "regime",
        "파라미터민감도",
        "거래비용",
        "transactioncost",
        "몬테카를로",
        "montecarlo",
        "monte-carlo",
        "autonomouslearning",
        "externalresearch",
        "promotioncandidate",
    )
    if any(token in normalized for token in signals):
        return True
    return "개선" in normalized and "후보" in normalized and "검증" in normalized and "연구" in normalized


def _resolve_autonomous_symbol(route, context: ConversationalMVPContext | None) -> str:
    if route.symbols:
        return route.symbols[0].symbol
    if context is not None and context.last_symbols:
        return context.last_symbols[0]
    return "005930"


def _render_autonomous_learning_query(payload: dict[str, object]) -> str:
    learning = _as_dict(_as_dict(payload.get("autonomous_cycle")).get("learning_report") or payload.get("learning_report"))
    stored = _as_list(learning.get("stored_records"))
    duplicates = _as_list(learning.get("duplicate_candidates"))
    if not stored and not duplicates:
        return "영하님, 현재 저장된 검증된 학습 기록은 없습니다. 임의의 학습 내용을 만들지 않겠습니다."
    return "\n".join(
        [
            "영하님, 지금까지의 자율 연구에서 확인한 학습 내용입니다.",
            f"- 저장된 evidence-backed 기록: {len(stored)}건",
            f"- 중복으로 병합하지 않은 후보: {len(duplicates)}건",
            "- 이 기록은 검증 근거가 붙은 연구 메모리이며, Knowledge Validated나 정책 적용 상태가 아닙니다.",
            "- 자동 주문, Champion 자동 승격, 승인 없는 config 변경은 수행하지 않았습니다.",
        ]
    )


def _autonomous_continuation_state(context: ConversationalMVPContext) -> dict[str, object]:
    payload = dict(context.last_detail_payload)
    progression = _as_dict(payload.get("progression"))
    critic = _as_dict(payload.get("critic_report"))
    if not critic:
        critic = _as_dict(_as_dict(payload.get("autonomous_cycle")).get("critic_report"))
    retests = _as_list(critic.get("retests"))
    tested_keys = set(str(item) for item in progression.get("tested_candidate_keys", ()) if item)
    tested_keys.update(_candidate_dedupe_key(item) for item in retests if _as_dict(item).get("status") in {"tested", "TESTED"})
    historical_candidates = {_identity_from_dedupe_key(item) for item in progression.get("historical_candidates", ()) if item}
    historical_tested = {_identity_from_dedupe_key(item) for item in progression.get("historical_tested_candidates", ()) if item}
    historical_candidates.update(_identity_from_dedupe_key(item) for item in tested_keys)
    historical_tested.update(_identity_from_dedupe_key(item) for item in tested_keys)
    proposals = _as_list(critic.get("proposals"))
    historical_candidates.update(_candidate_identity_key(item) for item in (proposals or retests))
    historical_tested.update(_candidate_identity_key(item) for item in retests if _as_dict(item).get("status") in {"tested", "TESTED"})
    return {
        "schema_version": 1,
        "root_cycle_id": progression.get("root_cycle_id") or payload.get("run_id"),
        "current_cycle_id": payload.get("run_id"),
        "terminal_state": payload.get("terminal_state"),
        "continuation_count": int(progression.get("continuation_count", 0) or 0),
        "historical_candidates": sorted(historical_candidates),
        "historical_tested_candidates": sorted(historical_tested),
        "current_cycle_candidates": tuple(str(item) for item in progression.get("current_cycle_candidates", ()) if item),
        "current_cycle_tested_candidates": tuple(str(item) for item in progression.get("current_cycle_tested_candidates", ()) if item),
        "duplicate_candidates": tuple(str(item) for item in progression.get("duplicate_candidates", ()) if item),
        "tested_candidate_keys": sorted(tested_keys),
        "completed_steps": tuple(str(item) for item in progression.get("completed_steps", ()) if item),
        "assumptions_fingerprint": _autonomous_assumptions_fingerprint(payload),
        "strategy_fingerprint": _autonomous_strategy_fingerprint(payload),
    }


def _with_autonomous_progression(output: dict[str, object], previous: ConversationalMVPContext | None, mode: str) -> dict[str, object]:
    payload = dict(output)
    prior_payload = dict(previous.last_detail_payload) if previous is not None else {}
    prior_progression = _as_dict(prior_payload.get("progression"))
    critic = _as_dict(payload.get("critic_report"))
    retests = _as_list(critic.get("retests"))
    proposals = _as_list(critic.get("proposals"))
    prior_tested = {str(item) for item in prior_progression.get("tested_candidate_keys", ()) if item}
    prior_historical_candidates = {_identity_from_dedupe_key(item) for item in prior_progression.get("historical_candidates", ()) if item}
    prior_historical_tested = {_identity_from_dedupe_key(item) for item in prior_progression.get("historical_tested_candidates", ()) if item}
    prior_historical_candidates.update(_identity_from_dedupe_key(item) for item in prior_tested)
    prior_historical_tested.update(_identity_from_dedupe_key(item) for item in prior_tested)
    current_tested = {_candidate_dedupe_key(item) for item in retests if _as_dict(item).get("status") in {"tested", "TESTED"}}
    duplicate = sorted(prior_tested.intersection(current_tested))
    continuation_count = int(prior_progression.get("continuation_count", 0) or 0) + (1 if mode == "continue" else 0)
    terminal = str(payload.get("terminal_state") or _as_dict(payload.get("autonomous_cycle")).get("terminal_state") or "unknown")
    if mode == "continue" and prior_tested and current_tested and current_tested.issubset(prior_tested):
        terminal = "no_new_research_path"
        payload["terminal_state"] = terminal
        critic = dict(critic)
        critic["retests"] = []
        critic["proposals"] = []
        payload["critic_report"] = critic
        cycle = dict(_as_dict(payload.get("autonomous_cycle")))
        if cycle:
            cycle_critic = dict(_as_dict(cycle.get("critic_report")))
            cycle_critic["retests"] = []
            cycle_critic["proposals"] = []
            cycle["critic_report"] = cycle_critic
            cycle["terminal_state"] = terminal
            payload["autonomous_cycle"] = cycle
        proposals = []
        retests = []
    current_candidates = {_candidate_identity_key(item) for item in proposals} if proposals else {_candidate_identity_key(item) for item in retests}
    current_tested_candidates = {_candidate_identity_key(item) for item in retests if _as_dict(item).get("status") in {"tested", "TESTED"}}
    original_retests = _as_list(_as_dict(output.get("critic_report")).get("retests"))
    duplicate_candidates = sorted(_candidate_identity_key(item) for item in original_retests if _candidate_dedupe_key(item) in duplicate)
    progression = {
        "schema_version": 1,
        "root_cycle_id": prior_progression.get("root_cycle_id") or prior_payload.get("run_id") or payload.get("run_id"),
        "parent_cycle_id": prior_payload.get("run_id") if previous is not None and previous.last_result_kind in _AUTONOMOUS_CONTEXT_KINDS else None,
        "current_cycle_id": payload.get("run_id"),
        "continuation_count": continuation_count,
        "historical_candidates": sorted(prior_historical_candidates | current_candidates),
        "historical_tested_candidates": sorted(prior_historical_tested | current_tested_candidates),
        "current_cycle_candidates": sorted(current_candidates),
        "current_cycle_tested_candidates": sorted(current_tested_candidates),
        "duplicate_candidates": duplicate_candidates,
        "tested_candidate_keys": sorted(prior_tested | current_tested),
        "duplicate_candidate_keys": duplicate,
        "terminal_state": terminal,
        "progression_state": "NO_NEW_RESEARCH_PATH" if terminal == "no_new_research_path" else ("CONTINUED" if mode == "continue" else terminal.upper()),
        "assumptions_immutable": _autonomous_assumptions_fingerprint(payload) == (prior_progression.get("assumptions_fingerprint") or _autonomous_assumptions_fingerprint(payload)),
        "assumptions_fingerprint": _autonomous_assumptions_fingerprint(payload),
        "strategy_fingerprint": _autonomous_strategy_fingerprint(payload),
        "unsupported_claims_blocked": ["cost_assumptions", "fabricated_metric_delta", "unsupported_assumption_change"],
    }
    payload["progression"] = progression
    audit = dict(_as_dict(payload.get("audit")))
    audit["continuation_count"] = continuation_count
    audit["duplicate_candidate_count"] = len(duplicate)
    audit["terminal_state"] = terminal
    payload["audit"] = audit
    return payload


def _render_autonomous_progress_comparison(context: ConversationalMVPContext) -> str:
    payload = dict(context.last_detail_payload)
    progression = _as_dict(payload.get("progression"))
    critic = _as_dict(payload.get("critic_report"))
    findings = _as_list(critic.get("findings"))
    proposals = _as_list(critic.get("proposals"))
    retests = _as_list(critic.get("retests"))
    learning = _as_dict(payload.get("learning_report"))
    stored = _as_list(learning.get("stored_records"))
    terminal = progression.get("terminal_state") or payload.get("terminal_state") or "unknown"
    historical_candidates = _as_list(progression.get("historical_candidates"))
    historical_tested = _as_list(progression.get("historical_tested_candidates"))
    current_candidates = _as_list(progression.get("current_cycle_candidates"))
    duplicate_candidates = _as_list(progression.get("duplicate_candidates"))
    candidate_history_label = ", ".join(_candidate_history_label(item) for item in historical_candidates) or "없음"
    return "\n".join(
        [
            "영하님, 처음 연구와 지금까지의 자율 연구 진행 차이를 구조화된 기록 기준으로만 비교하면 다음과 같습니다.",
            f"- 처음에는 baseline 분석을 기준으로 표본/근거 부족 여부를 확인했습니다.",
            f"- 이후 확인된 critic finding은 {len(findings)}건입니다.",
            f"- 전체 history 기준 생성된 개선 후보는 {len(historical_candidates)}건이고, TESTED 후보 기록은 {len(historical_tested)}건입니다.",
            f"- 이번 continuation에서 새로 생성된 후보는 {len(current_candidates)}건입니다.",
            f"- 중복으로 차단한 후보는 {len(duplicate_candidates)}건입니다.",
            f"- 후보 history: {candidate_history_label}",
            f"- Learning Memory에 연결된 evidence-backed 기록은 {len(stored)}건입니다.",
            f"- continuation_count={progression.get('continuation_count', 0)}",
            f"- 현재 terminal_state={terminal}",
            "- 성과 수치 변화는 양쪽 authoritative 결과에 같은 metric이 있을 때만 계산합니다. 현재는 근거 없는 성과 delta를 만들지 않겠습니다.",
            "- 비용 가정, slippage, tax, position sizing, execution timing이 바뀌었다는 기록은 없습니다.",
            "- 자동 주문, Champion 자동 승격, 승인 없는 config 변경은 수행하지 않았습니다.",
        ]
    )


def _candidate_dedupe_key(value: object) -> str:
    item = _as_dict(value)
    candidate = _as_dict(item.get("candidate"))
    changed_rules = candidate.get("changed_rules")
    if not isinstance(changed_rules, list):
        changed_rules = item.get("changed_rules") if isinstance(item.get("changed_rules"), list) else []
    basis = {
        "candidate_kind": _candidate_kind(str(item.get("candidate_id") or candidate.get("candidate_id") or item.get("proposal_id") or "")),
        "hypothesis": str(candidate.get("hypothesis") or item.get("hypothesis") or ""),
        "changed_rules": sorted(str(rule) for rule in changed_rules),
        "status": str(item.get("status") or candidate.get("status") or ""),
    }
    return "|".join(f"{key}={basis[key]}" for key in sorted(basis))


def _candidate_identity_key(value: object) -> str:
    item = _as_dict(value)
    candidate = _as_dict(item.get("candidate"))
    kind = _candidate_kind(str(item.get("candidate_id") or candidate.get("candidate_id") or item.get("proposal_id") or ""))
    return f"candidate_kind={kind or 'unknown'}"


def _identity_from_dedupe_key(value: object) -> str:
    text = str(value)
    for part in text.split("|"):
        if part.startswith("candidate_kind="):
            kind = part.split("=", 1)[1] or "unknown"
            return f"candidate_kind={kind}"
    return text or "candidate_kind=unknown"


def _candidate_history_label(value: object) -> str:
    text = str(value)
    for part in text.split("|"):
        if part.startswith("candidate_kind="):
            return part.split("=", 1)[1] or "unknown"
    return text or "unknown"


def _candidate_kind(candidate_id: str) -> str:
    if "robust-breakout" in candidate_id:
        return "robust-breakout"
    if "regime-filter" in candidate_id:
        return "regime-filter"
    if "no-change" in candidate_id:
        return "no-change"
    if ":candidate:" in candidate_id:
        return candidate_id.rsplit(":candidate:", 1)[-1]
    return candidate_id


def _autonomous_assumptions_fingerprint(payload: dict[str, object]) -> str:
    baseline = _as_dict(payload.get("baseline"))
    assumptions = _as_dict(baseline.get("assumptions"))
    return hashlib.sha256(dumps_json(assumptions).encode("utf-8")).hexdigest()[:16]


def _autonomous_strategy_fingerprint(payload: dict[str, object]) -> str:
    baseline = _as_dict(payload.get("baseline"))
    strategy = _as_dict(baseline.get("strategy"))
    return str(strategy.get("fingerprint") or strategy.get("strategy_id") or "strategy:unknown")


def _is_autonomous_presentation_intent(intent: ConversationalMVPIntent) -> bool:
    return intent in {
        ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT,
        ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT,
        ConversationalMVPIntent.PROFESSIONAL_EXPLANATION,
        ConversationalMVPIntent.SHOW_DETAILS,
        ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP,
    }


def _is_promotion_candidate_presentation_request(text: str) -> bool:
    normalized = re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
    if not normalized:
        return False
    tokens = (
        "승격후보",
        "후보를자세히",
        "후보자세히",
        "후보id",
        "fingerprint",
        "근거를보여",
        "근거를알려",
        "참고자료",
        "출처",
        "외부자료",
        "백테스트결과",
        "검증결과",
        "랭킹근거",
        "주요위험",
        "리스크",
        "무엇이바뀌",
        "뭐가바뀌",
        "아직승인하지않",
    )
    return any(token in normalized for token in tokens)


def _render_autonomous_context_followup(context: ConversationalMVPContext, intent: ConversationalMVPIntent, user_text: str) -> str:
    payload = dict(context.last_detail_payload)
    if not payload and context.last_structured_results:
        payload = _as_dict(context.last_structured_results[0])
    if context.last_result_kind == "autonomous_learning_memory_summary":
        return _render_autonomous_learning_presentation(payload, intent, user_text)
    if context.last_result_kind == "autonomous_learning_v2":
        grounded_v2 = format_grounded_tool_response("autonomous_learning_research", payload, user_text)
        if grounded_v2 is not None:
            return grounded_v2
    if intent is ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT:
        assessment = _as_dict(payload.get("assessment"))
        plan = _as_dict(payload.get("plan"))
        critic = _as_dict(payload.get("critic_report"))
        learning = _as_dict(payload.get("learning_report"))
        steps = _as_list(plan.get("steps"))
        findings = _as_list(critic.get("findings"))
        proposals = _as_list(critic.get("proposals"))
        stored = _as_list(learning.get("stored_records"))
        progression = _as_dict(payload.get("progression"))
        candidate_count = len(proposals) or len(_as_list(progression.get("historical_candidates"))) or len(_as_list(progression.get("tested_candidate_keys")))
        status = str(progression.get("progression_state") or progression.get("terminal_state") or payload.get("terminal_state") or assessment.get("status") or "검증 계속 필요")
        return "\n".join(
            [
                f"영하님, 쉽게 말하면 방금 결과는 일반 백테스트 요약이 아니라 자율 연구 진행 상태입니다. 현재 판단은 {status}입니다.",
                f"- 검증/계획 단계: {len(steps)}개",
                f"- 발견한 문제: {len(findings)}건",
                f"- 개선 후보: {candidate_count}건",
                f"- evidence-backed 학습 기록: {len(stored)}건",
                "- 이 답변은 저장된 자율 연구 context만 다시 설명한 것이며, 연구 도구를 다시 실행하지 않았습니다.",
                "- 자동 주문, Champion 자동 승격, 승인 없는 config 변경은 수행하지 않았습니다.",
            ]
        )
    grounded = format_grounded_tool_response("autonomous_research_cycle", payload, user_text)
    if grounded is not None:
        return grounded
    return context.last_summary or context.last_rendered_result


def _render_autonomous_learning_presentation(payload: dict[str, object], intent: ConversationalMVPIntent, user_text: str) -> str:
    learning = _as_dict(_as_dict(payload.get("autonomous_cycle")).get("learning_report") or payload.get("learning_report"))
    stored = _as_list(learning.get("stored_records"))
    duplicates = _as_list(learning.get("duplicate_candidates"))
    if intent is ConversationalMVPIntent.SHOW_DETAILS or "표" in user_text:
        return "\n".join(
            [
                "영하님, 직전 learning-memory 요약을 같은 의미로 자세히 풀어드리겠습니다.",
                "",
                "| 항목 | 값 |",
                "| --- | --- |",
                f"| evidence-backed 기록 | {len(stored)}건 |",
                f"| 자동 병합하지 않은 중복 후보 | {len(duplicates)}건 |",
                "| Knowledge Validated | 아님 |",
                "| 정책 적용 | 아님 |",
                "| 자동 주문/승격/config 변경 | 수행하지 않음 |",
            ]
        )
    if intent is ConversationalMVPIntent.PROFESSIONAL_EXPLANATION:
        return "\n".join(
            [
                "영하님, 직전 답변은 Learning Memory 조회 결과입니다.",
                f"- 저장된 evidence-backed 연구 기록은 {len(stored)}건입니다.",
                f"- 중복 후보는 {len(duplicates)}건이며 자동 병합하지 않았습니다.",
                "- 이 기록은 검증 근거가 붙은 연구 메모리이지만, Knowledge Validated 또는 정책 적용 상태는 아닙니다.",
                "- 따라서 성과 수치, 기간, 거래 수를 새로 계산하거나 일반 BacktestResult로 해석하지 않습니다.",
            ]
        )
    return "\n".join(
        [
            "영하님, 쉽게 말하면 방금 답변은 백테스트 성과표가 아니라 가온이 연구 과정에서 남긴 검증 근거 있는 메모리 요약입니다.",
            f"- 저장된 기록: {len(stored)}건",
            f"- 자동으로 합치지 않은 중복 후보: {len(duplicates)}건",
            "- 아직 확정 지식이나 실제 전략 변경은 아닙니다.",
            "- 그래서 기간, 거래 수, 수익률을 새로 만들어 설명하지 않겠습니다.",
        ]
    )


def _symbol_from_autonomous_payload(payload: dict[str, object]) -> str:
    baseline = _as_dict(payload.get("baseline"))
    dataset = _as_dict(baseline.get("dataset"))
    metadata = _as_dict(dataset.get("metadata"))
    return str(payload.get("symbol") or metadata.get("symbol") or "005930")


def _as_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def _format_tool_response(tool_name: str, output: dict[str, object], user_text: str = "") -> str:
    grounded = format_grounded_tool_response(tool_name, output, user_text)
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
