"""Gaon LLM conversation brain with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
import re
import sqlite3
from typing import Mapping, Protocol
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
    extract_symbol_entities,
    is_availability_question,
    presentation_preference_for_text,
    render_presentation_from_payloads,
    render_reasoning_from_payloads,
    render_rerun_boundary,
    render_follow_up,
    render_general_conversation,
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
from gaon.runtime.llm_tool_routing import has_explicit_research_execution_intent, route_read_only_tool
from gaon.research.global_market import extract_market_symbols, resolve_market_scope
from gaon.runtime.llm_tools import SafeToolExecutor, ToolRequest
from gaon.knowledge.research_mission import (
    MissionStatus,
    MissionUniverseScope,
    ResearchMission,
    add_candidate,
    candidate_records,
    clear_focus_symbol,
    distinct_promotion_ready_strategy_count,
    extract_candidate_id,
    extract_or_update_mission,
    get_active_candidate,
    get_candidate,
    is_best_candidate_query,
    is_candidate_robustness_continuation_request,
    is_cycle_budget_exhausted,
    is_diversity_request,
    is_generic_continuation_request,
    is_mission_candidate_read_request,
    is_research_progress_status_question,
    is_stop_or_negation_request,
    is_provider_acquisition_blocker,
    mission_awaiting_approval_message,
    mission_blocked_message,
    mission_budget_exhausted_message,
    mission_candidate_read_focus,
    mission_cycle_request_text,
    mission_status_block,
    render_candidate_score_status,
    render_mission_candidate_detailed_status,
    render_mission_candidates_overview,
    next_candidate_sequence,
    next_unexplored_symbols,
    record_blocked,
    record_cycle_result,
    record_focus_symbol,
    record_promotion_candidate,
    render_robustness_cycle_response,
    set_active_candidate,
    update_candidate,
)
from gaon.knowledge.strategy_candidate import (
    EconomicViabilityStatus,
    StrategyCandidateStatus,
    candidate_remaining_blockers,
    candidate_sample_exhausted,
    evaluate_economic_viability,
    expand_strategy_space_candidate,
    is_stagnant,
    mark_promotion_ready,
    mark_rejected,
    mark_stagnant,
    new_candidate,
    next_blocker_driven_research_action,
    next_robustness_evidence_symbol,
    next_untried_family,
    record_breadth_progress,
    record_robustness_progress,
    render_candidate_block,
    render_candidate_cumulative_evidence_block,
    render_candidate_request_text,
    render_candidate_status_summary,
    render_candidate_strategy_explanation,
)

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

# ULTRAREVIEW H3 fix: the Research Mission continuation hook must defer to
# the existing conversational intent classifier whenever it already
# recognized this message as an explain/detail/risk/recommendation/rerun/
# timeframe/status follow-up about a PRIOR result, rather than deciding
# purely from continuation-phrase keyword matching - otherwise a message
# like "이어서 설명해주세요" (please continue *explaining*) can be
# misread as "continue researching" merely because it shares a word with a
# real continuation phrase.
_MISSION_HOOK_EXCLUDED_INTENTS = frozenset(
    {
        ConversationalMVPIntent.GREETING,
        ConversationalMVPIntent.HELP,
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
        ConversationalMVPIntent.STATUS_QUERY,
        ConversationalMVPIntent.RESOURCE_NEEDS_QUERY,
    }
)

# ULTRAREVIEW High #1 fix: the deep single-symbol validation pipeline
# (gaon.research.krx_real_pipeline.RealAutonomousResearchPipeline, invoked
# via the autonomous_learning_research tool) never accepts a
# CanonicalStrategySpec directly - it always re-parses the request text
# through UserStrategyParser. A candidate's fingerprint may only be
# recorded as promotion-ready when that re-parse demonstrably produces the
# SAME effective strategy rules the candidate's own fingerprint claims -
# never on trust that the request text was a faithful approximation.
def _deep_validation_effective_fingerprint(request_text: str, *, symbol: str) -> str:
    """Reuses the EXACT parser (gaon.research.krx_real_pipeline.
    UserStrategyParser) the deep-validation pipeline itself uses on
    ``request_text`` - never a second/parallel implementation - to compute
    what that pipeline actually validated, so it can be compared against
    the candidate's own ``strategy_fingerprint`` before recording a
    promotion-ready strategy."""
    from gaon.research.krx_real_pipeline import UserStrategyParser

    parsed = UserStrategyParser().parse(request_text, symbol=symbol)
    return parsed.strategy_family_fingerprint


# Patch 8.3 production bug fix: these are the read-only tools
# route_read_only_tool can resolve a message to that ALL resolve their
# research target from a single symbol pulled out of conversational
# context (never from a ResearchMission) - the exact tools whose stale-
# context symbol resolution reproduced the "resumed an old Samsung
# Electronics session" defect when a market-wide mission's candidate
# continuation message did not happen to match the deterministic router's
# multi_symbol_research heuristics either.
_LEGACY_SINGLE_SYMBOL_RESEARCH_TOOLS = frozenset({"autonomous_learning_research", "autonomous_research_cycle", "research_retest"})

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
    structured_context: Mapping[str, object] | None = None
    # Production hotfix: True only for a synthetic, system/background-
    # originated continuation turn (see
    # gaon.runtime.autonomous_research_runtime), never for a real Telegram/
    # web user message. Routing (_is_conversational_mvp_source and the
    # real mission-driven research cycle) is unaffected - this only
    # suppresses provenance-sensitive side effects that must never be
    # attributed to a human: the turn is not persisted as a "user"/
    # "assistant" conversation_messages row, and it never feeds cognitive
    # feedback/preference learning or creates/mutates a cognitive Goal
    # record. ResearchMission state itself is unaffected: it is persisted
    # separately (conversation_sessions.metadata) regardless of this flag.
    is_system_turn: bool = False


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
        self._cognitive = None
        connection = getattr(repository, "_connection", None)
        if connection is not None and connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='cognitive_records'"
        ).fetchone():
            from gaon.cognitive.orchestrator import CognitiveOrchestrator
            from gaon.cognitive.sustainability import ensure_sustainability_objective

            self._cognitive = CognitiveOrchestrator(connection)
            # Durable, restart/new-conversation-independent system objective
            # (Hotfix #166) - idempotent (a no-op after the first call ever
            # made against this database), reserved-namespace, never a
            # per-user goal/preference write. See gaon.cognitive.
            # sustainability module docstring for the full contract.
            ensure_sustainability_objective(connection, now=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

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
        if not request.is_system_turn:
            self._repository.add_message(
                LLMConversationMessage(user_message_id, session.session_id, "user", text, intent.value, "input", (), (), (), now)
            )
        context = None
        if self._context_orchestrator is not None and text.casefold().rstrip(".!?") not in {
            "안녕", "안녕하세요", "가온아 안녕", "hello", "hi",
        }:
            contextual_build = getattr(self._context_orchestrator, "build_for_query", None)
            context = (contextual_build(request.session_id, text) if contextual_build
                       else self._context_orchestrator.build(request.session_id))
        response_text, route, warnings, references, provider, tool_calls = self._generate(
            replace(request, message_id=user_message_id), intent, approval_required, context,
        )
        if self._cognitive is not None and not approval_required and not request.is_system_turn:
            response_text = self._cognitive.render_with_preferences(
                namespace=request.user_ref, query=request.text, text=response_text, now=now,
            )
            mission = self._mission_for(request.session_id)
            if mission is not None and tool_calls:
                goal = self._cognitive.create_goal(
                    namespace=request.session_id, title=f"Research mission {mission.mission_id}",
                    description=mission.originating_request, reason="user research instruction",
                    success_criteria=("existing ResearchMission acceptance and human approval boundary",),
                    next_action="연구를 계속해주세요", source_ref=mission.mission_id, now=now,
                )
                from gaon.cognitive.models import GoalStatus
                state = {
                    "blocked": GoalStatus.BLOCKED,
                    "awaiting_human_approval": GoalStatus.BLOCKED,
                    "completed": GoalStatus.COMPLETED,
                    "cancelled": GoalStatus.ABANDONED,
                }.get(mission.status.value, GoalStatus.ACTIVE)
                self._cognitive.transition_goal(goal.record_id, namespace=request.session_id, status=state, now=now)
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
        if not request.is_system_turn:
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
        if not approval_required and request.structured_context:
            from gaon.cognitive.presentation import binance_snapshot_reply
            snapshot = binance_snapshot_reply(request.text, request.structured_context)
            if snapshot is not None:
                return snapshot, "conversation_binance_snapshot", (), ("dashboard_state_snapshot",), "deterministic", ()
        # Pure greetings never inherit stale research intent or execute tools.
        if not approval_required and request.text.strip().casefold().rstrip(".!?") in {
            "안녕", "안녕하세요", "가온아 안녕", "hello", "hi"
        }:
            return render_greeting(), "conversation_greeting", (), (), "deterministic", ()
        if self._cognitive is not None and not approval_required and not request.is_system_turn:
            observed = self._cognitive.observe_user_message(
                namespace=request.user_ref, message=request.text,
                source_ref=request.message_id or f"feedback:{uuid4().hex}", now=request.received_at,
            )
            if observed:
                return ("같은 상태 설명을 반복하지 않도록 선호를 저장했습니다. 이후 진행상황은 변경점을 중심으로 알려드리겠습니다.",
                        "cognitive_feedback", (), observed, "deterministic", ())
            if request.text.strip().rstrip(".!?") in {"계속해주세요", "계속해줘", "그 방향으로 해주세요"}:
                goals = self._cognitive.retrieve(namespace=request.session_id, query=request.text).active_goals
                if goals and self._mission_for(request.session_id) is not None:
                    request = replace(request, text="연구를 계속해주세요")
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
            tools = self._tool_executor.assistant_tool_definitions(request.text) if self._tool_executor is not None else ()
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

    def _format_multi_tool_response_for_session(self, results: tuple[AssistantToolResult, ...], request: LLMConversationRequest) -> str:
        """Same rendering as ``_format_multi_tool_response``, except that when
        every tool call in this turn failed (the opaque "safety validation"
        fallback), the explanation is grounded in the actual structured
        failure evidence each result carries (see
        ``_classify_multi_tool_failure``) instead of asserting a specific
        cause - such as budget exhaustion - the evidence does not establish.
        If a mission is active, its status is appended for context, never as
        the stated cause of the failure. The safety gate that blocked every
        call is unchanged; only the explanation improves."""
        text = _format_multi_tool_response(results)
        if text != _OPAQUE_TOOL_SAFETY_FALLBACK_TEXT:
            return text
        explanation = _classify_multi_tool_failure(results)
        mission = self._mission_for(request.session_id)
        if mission is None:
            return explanation
        if mission.status is MissionStatus.BLOCKED:
            return mission_blocked_message(mission)
        return f"{explanation}\n\n{mission_status_block(mission)}\n\n연구 Mission은 종료되지 않았습니다, 영하님."

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
            text = self._format_multi_tool_response_for_session(tuple(results), request)
            return text, "provider_tool_fallback", _dedupe((*warnings, f"provider fallback: {reason}")), _dedupe((*references, *(f"tool:{name}" for name in executed))), "deterministic", tuple(executed)
        if final.truncated:
            final = self._continue_provider_response(provider, request, intent, final, _dedupe((*references, *(f"tool:{name}" for name in executed))))
        raw_text = final.text or self._format_multi_tool_response_for_session(tuple(results), request)
        text = raw_text
        strict_real_results = tuple(result for result in results if is_strict_real_research_tool(result.name))
        if strict_real_results:
            text = self._format_multi_tool_response_for_session(tuple(results), request)
            if any(isinstance(result.result.get("output"), dict) and strict_real_research_grounding_violations(raw_text, result.result["output"]) for result in strict_real_results):
                warnings = (*warnings, "provider strict real research grounding fallback")
            else:
                warnings = (*warnings, "structured real research report preferred")
        elif any(is_research_tool(result.name) for result in results) and (
            contains_unverified_fixture_metrics(text)
            or contains_fixture_leakage(text)
            or (is_korean_request(request.text) and looks_like_english_final(text))
        ):
            text = self._format_multi_tool_response_for_session(tuple(results), request)
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
        # Conversation-layer safety boundary: route_read_only_tool matches on
        # research TOPIC (a symbol, "전략", "연구"), not on an execution
        # verb. A status/read question like "삼성전자 연구 상태 알려줘" would
        # otherwise satisfy this same tool_name and run real research
        # synchronously before any LLM/mission-aware reasoning ever sees the
        # message. Only an explicit execution-intent message may proceed.
        if not has_explicit_research_execution_intent(request.text):
            return None
        # hotfix/conversation-layer-subject-intent-continuity: an execution
        # request that names no concrete subject at all - only a bare
        # backward-reference pronoun ("그거 다시 연구해줘") - must never
        # silently resolve to _default_tool_arguments' hardcoded "005930"
        # placeholder symbol when there is no mission/candidate this can
        # actually resolve "그거" against. See
        # ``_omitted_subject_clarification``'s module note - the same
        # guard is applied at every path that could otherwise silently
        # default a bare pronoun reference to a hardcoded/stale subject.
        omitted_subject = self._omitted_subject_clarification(request, warnings, references)
        if omitted_subject is not None:
            return omitted_subject
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
        # KR-ST-008 production bug fix: STOP/negation ("연구 계속하지
        # 마세요", "연구 중단해주세요") has absolute priority over every
        # other routing path here - typo-tolerant continuation, read-only,
        # legacy autonomous research, everything. Checked first,
        # unconditionally, before route classification or mission
        # extraction/update even happen, so a stop request can never be
        # reinterpreted as any kind of research-execution request and
        # never mutates mission state. A pure read
        # (self._mission_for, not extract_or_update_mission) so this turn
        # itself changes nothing.
        if is_stop_or_negation_request(request.text):
            mission = self._mission_for(request.session_id)
            status = f"\n\n{mission_status_block(mission)}" if mission is not None else ""
            return (
                f"영하님, 알겠습니다. 추가 연구를 실행하지 않았습니다.{status}",
                "conversation_research_stopped",
                _dedupe((*warnings, "explicit stop/negation request; zero research tool calls, no state mutation")),
                references,
                "deterministic",
                (),
            )
        route = classify_conversational_route(request.text)
        if route.intent in {ConversationalMVPIntent.UNKNOWN, ConversationalMVPIntent.GENERAL_CONVERSATION} and _is_stored_research_explanation_followup(request.text):
            context = self._mvp_context_for(request.session_id)
            if context is not None:
                route = ConversationalRoute(ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, route.symbols)
        existing_mission = self._mission_for(request.session_id)
        # hotfix/conversation-layer-safe-web-parity: extract_or_update_
        # mission recognizes a research-shaped SUBJECT (e.g. "단타") and
        # unconditionally returns/persists a brand-new ACTIVE
        # ResearchMission for it - it does not itself distinguish a status
        # QUESTION ("단타 연구는 잘되가고 있나요?") from an execution
        # REQUEST. Without this guard, a pure read-only status question
        # about a mission that does not exist yet would silently manufacture
        # one (mission would no longer be None below, so the "no active
        # Research Mission" read-model a few lines down could never fire),
        # in direct violation of "새 ResearchMission 생성 금지" for a
        # STATUS_READ message. Only short-circuit when there is truly no
        # existing mission AND the message carries no explicit execution
        # verb AND it is shaped like a status/read question - a real
        # execution/continuation request still reaches extract_or_update_
        # mission exactly as before.
        # Deliberately checks only is_research_progress_status_question
        # here, NOT is_mission_candidate_read_request: that function's
        # explicit-read-only-marker branch (is_explicit_read_only_query)
        # satisfies its subject requirement on its own, so a general,
        # non-research status question tagged read-only by the web
        # dashboard's read_only flag (e.g. "가온 상태 알려줘" + the web
        # read-only marker) would otherwise be misrouted here as a
        # RESEARCH mission status question. is_research_progress_status_
        # question always requires an actual research-domain subject
        # token, so it does not have this false-positive.
        if (
            existing_mission is None
            and not has_explicit_research_execution_intent(request.text)
            and is_research_progress_status_question(request.text)
        ):
            return (
                "영하님, 현재 진행 중인 Research Mission이 없습니다. 연구를 시작하시려면 "
                "원하시는 종목이나 전략, 시장 범위를 말씀해 주세요.",
                "conversation_research_status_no_mission",
                _dedupe((*warnings, "no active research mission; zero research tool calls")),
                references,
                "deterministic",
                (),
            )
        mission = extract_or_update_mission(request.text, existing=existing_mission, now=request.received_at)
        if mission is not None:
            self._remember_mission(request, mission)

        # Explicit whole-market / multi-market research is an authoritative
        # execution request and must not be reinterpreted as a contextual
        # autonomous comparison against an earlier single-symbol run.
        existing_tool = route_read_only_tool(
            request.text
        )

        # Patch 8.1 scope-regression guard: once a mission has an
        # established non-single-symbol scope (market-wide KR / an
        # explicitly selected symbol set), a generic continuation message
        # ("증거가 충분할 때까지 연구해주세요") must keep researching within
        # that scope instead of falling through to the single-symbol
        # autonomous research path, which would resolve to
        # ``context.last_symbols[0]`` (or the "005930" default) and silently
        # narrow a market-wide mission back down to one symbol.
        #
        # Patch 8.3 production bug fix: even with a broadened
        # is_generic_continuation_request, a token-based predicate can never
        # enumerate every real phrasing. As defense-in-depth, this hook ALSO
        # takes precedence whenever the deterministic router would
        # otherwise send this message to one of the LEGACY single-symbol-
        # shaped research tools (which resolve their target symbol from
        # stale conversational context, never from the mission) while this
        # mission already has real persisted candidate work in progress -
        # that combination is never a coincidence, it is always a
        # continuation of the active candidate's validation. An explicit
        # symbol mention (route.symbols) or an excluded conversational
        # intent still bypasses this entirely, same as the token-based path.
        candidate_continuation_precedence = (
            existing_tool in _LEGACY_SINGLE_SYMBOL_RESEARCH_TOOLS
            and mission is not None
            and get_active_candidate(mission) is not None
        )
        # Patch 8.5 production bug fix: once a candidate's breadth
        # evaluation has already gathered sufficient cross-symbol evidence
        # (mission.pending_promotion_symbol is set - see
        # _try_candidate_breadth_cycle), a message that explicitly asks to
        # continue that candidate's robustness validation (OOS/walk-
        # forward/cost-stress/regime/etc - is_candidate_robustness_
        # continuation_request) can coincidentally also trip the
        # deterministic multi_symbol_research tool heuristic (e.g.
        # mentioning "cross-symbol" as one of the validation stages to
        # run) or the STATUS_QUERY intent classifier (e.g. "유지한
        # 상태에서" - "while KEEPING it [unchanged]" - contains the bare
        # substring "상태" with no status-query meaning at all). Neither
        # collision is something a hand-enumerated token list can fully
        # prevent. When the mission has already reached "ready for
        # robustness validation" AND the message unambiguously asks to
        # continue that validation, this precedence signal overrides BOTH
        # false-positive gates - exactly as candidate_continuation_
        # precedence above already does for the legacy-single-symbol-tool
        # case. It never fires for a genuine status query or a genuine
        # fresh multi-symbol research request, since those never match
        # is_candidate_robustness_continuation_request's required
        # candidate/topic-reference-plus-continuation-verb shape.
        # Patch 8.7 production bug fix (root cause): the check above used to
        # require ``mission.pending_promotion_symbol is not None`` - i.e. the
        # active candidate had ALREADY reached "ready for robustness"
        # before this override could ever fire. Real production showed a
        # persisted candidate can legitimately still be in its BREADTH
        # stage (not yet promotion-eligible) when the user asks to
        # "continue the current active candidate's validation" - that
        # message still unambiguously names the active candidate (or a
        # robustness-stage keyword) plus a continuation verb, and must
        # still resolve to THAT candidate (continuing whichever stage -
        # breadth or robustness - it is actually in; see
        # ``_try_mission_driven_research_cycle``'s own
        # ``mission.pending_promotion_symbol`` dispatch, which already
        # picks the right stage) rather than falling through to a
        # mission-unaware raw tool call that never touches candidate
        # bookkeeping at all. Narrowed instead to require only that a
        # candidate actually exists to continue - same "an active
        # candidate must already exist" gate ``candidate_continuation_
        # precedence`` above already uses for the legacy-single-symbol-tool
        # case - so this still never fires for a genuine fresh request
        # before any candidate has been created.
        robustness_continuation_precedence = (
            mission is not None
            and get_active_candidate(mission) is not None
            and is_candidate_robustness_continuation_request(request.text)
        )
        # Patch 8.7 production bug fix (root cause): a genuine cross-symbol
        # BREADTH research request naturally names several real symbols
        # (production's own worked example -
        # ``gaon.research.multi_symbol.PRODUCTION_MULTI_SYMBOL_REQUEST_TEXT``
        # - lists all five target tickers). ``classify_conversational_route``
        # then returns those tickers as ``route.symbols`` - which the
        # ``not route.symbols`` guard below (correctly) reads as "the user
        # named ONE explicit symbol to narrow research down to" for
        # messages like "삼성전자만 연구해줘". For a genuine multi-symbol
        # breadth request this reads backwards: it disqualified the message
        # from ever reaching the mission-driven candidate cycle, so the
        # request fell through to ``_try_authoritative_research_tool``,
        # which executes the raw ``multi_symbol_research`` tool directly -
        # never creating or updating a ``StrategyCandidateRecord``. The
        # resulting report's "후보 A/B/C" (see
        # ``gaon.research.krx_real_pipeline.ImprovementCandidateGenerator``)
        # therefore had no persisted canonical identity, and the NEXT plain
        # continuation ("계속 연구해주세요", now with no symbols so it DID
        # pass the old gate) found no active candidate and minted a new one
        # (KR-ST-002) - silently discarding the breadth work just done.
        # Two or more explicit symbols under an active, non-single-symbol
        # mission, already classified as a ``multi_symbol_research``-shaped
        # request, is never a narrowing override - it is evidence FOR the
        # mission's own candidate, exactly like an unnamed generic breadth
        # continuation. Excludes ``COMPARE_SYMBOLS`` (a deliberate, bounded
        # same-assumption comparison of exactly the named symbols - see
        # ``ConversationalMVPIntent.COMPARE_SYMBOLS`` handling further
        # below) so that request keeps its own, separate path.
        multi_symbol_breadth_request = (
            existing_tool == "multi_symbol_research"
            and len(route.symbols) >= 2
            and route.intent is not ConversationalMVPIntent.COMPARE_SYMBOLS
        )
        # ULTRAREVIEW note: a bare "후보"+continuation-verb combination
        # that ALSO happens to be STATUS_QUERY-shaped (e.g. "후보 상태
        # 계속해주세요") still overrides this exclusion below, same as a
        # named-stage message - deliberately, NOT narrowed to require
        # is_named_robustness_stage_request. Narrowing this override was
        # tried and reverted: without it, such a message does not fall
        # back to the (safe, bounded) STATUS_QUERY branch as hoped - it
        # falls through EARLIER, into _try_autonomous_research_conversation
        # (called unconditionally further down in this same function,
        # BEFORE the STATUS_QUERY branch is ever reached), reproducing the
        # exact stale-single-symbol-context defect this patch closes for
        # the reported production message. Routing this ambiguous edge
        # case into the real, bounded, mission-aware robustness cycle
        # (this override's current behavior) is the safer of the two
        # available outcomes - it never fabricates state, never mutates
        # anything, and stays bounded to one tool call - even though it
        # may occasionally spend a cycle a user meant as a free status
        # read. Fixing the ambiguous case properly requires reordering
        # _try_conversational_mvp so STATUS_QUERY is handled before
        # _try_autonomous_research_conversation, which is a larger,
        # separately-scoped change - see the Patch 8.5 completion report.
        if (
            (existing_tool != "multi_symbol_research" or robustness_continuation_precedence or multi_symbol_breadth_request)
            and mission is not None
            and mission.universe_scope is not MissionUniverseScope.SINGLE_SYMBOL
            and (not route.symbols or multi_symbol_breadth_request)
            and (route.intent not in _MISSION_HOOK_EXCLUDED_INTENTS or robustness_continuation_precedence or multi_symbol_breadth_request)
            and (is_generic_continuation_request(request.text) or candidate_continuation_precedence or robustness_continuation_precedence or multi_symbol_breadth_request)
        ):
            if mission.status is MissionStatus.AWAITING_HUMAN_APPROVAL:
                # The target promotion-ready candidate count was already
                # reached; a generic continuation message must not start
                # further research behind the human's back - it re-surfaces
                # the existing approval request instead.
                self._remember_mission(request, mission)
                return (
                    mission_awaiting_approval_message(mission),
                    "conversation_mission_awaiting_approval",
                    _dedupe((*warnings, "mission awaiting human approval; no further research started")),
                    references,
                    "deterministic",
                    (),
                )
            if mission.status in (MissionStatus.ACTIVE, MissionStatus.BLOCKED):
                mission_result = self._try_mission_driven_research_cycle(
                    request,
                    mission,
                    warnings,
                    references,
                    preferred_breadth_symbols=tuple(symbol.symbol for symbol in route.symbols) if multi_symbol_breadth_request else (),
                )
                if mission_result is not None:
                    return mission_result

        # Patch 8.8 production bug fix: a read-only question about the
        # ACTIVE mission/candidate itself ("현재 활성 후보의 fingerprint와
        # 지금까지 검증한 종목 수, 누적 거래 수를 알려주세요", "현재 단타
        # 전략을 설명해주세요", "현재 단타 전략은 몇 점인가요?") never
        # matched the continuation-precedence block above (correctly - it
        # is not a continuation request) and had no other mission-aware
        # route, so it fell through into reasoning-followup/autonomous-
        # research machinery that only ever reads the per-session
        # ConversationalMVPContext - a single most-recent-tool-result
        # cache, completely independent of the mission's own persisted
        # candidate progress. Real production reproduced a validated-
        # symbols/cumulative-trades regression from 5/25 back down to 0
        # this way. ``is_mission_candidate_read_request`` explicitly
        # excludes anything already shaped like a continuation/execution
        # request, so this can never intercept a genuine "continue
        # validating the current candidate" message - those are already
        # handled (and returned from) by the block directly above.
        # KR-ST-008 production bug fix: a message explicitly naming a
        # candidate id ("KR-ST-008") and explicitly saying not to execute
        # any research ("연구 실행 없이 read-only로만 알려주세요") used to
        # never match ``is_mission_candidate_read_request`` at all (its
        # subject-token list only recognized generic phrases like
        # "활성후보", never an explicit id or an explicit "read-only"
        # marker) - it fell through into ``_try_autonomous_research_
        # conversation`` below, where ``_autonomous_learning_request_mode``
        # classified it as "external_research" purely because the message
        # happened to contain the bare substring "evidence" (from the
        # user's own request to see "performance evidence"), with no
        # awareness that the sentence explicitly forbade execution. That
        # path then resolved its target symbol from STALE per-session
        # conversational context, running a full research/OOS/walk-
        # forward/cost-stress cycle on an unrelated old symbol - the exact
        # opposite of what was asked. See ``is_mission_candidate_read_
        # request``/``extract_candidate_id`` in research_mission.py for the
        # fix; this block additionally resolves an EXPLICITLY named
        # candidate id from the mission's own persisted candidate map
        # (never the "active" one, never a stale conversational symbol),
        # and fails closed with an honest not-found message rather than
        # ever falling back to single-symbol research when that id does
        # not exist.
        # Hotfix #166 production bug fix: a research-status question
        # ("단타 전략은 잘 연구되고 있나요?") is real, honest-answerable
        # read-only vocabulary (is_mission_candidate_read_request already
        # recognizes it - confirmed for both spacing variants and the
        # "있나요"/"잇나요" typo) - it must never depend on a mission
        # already existing to be recognized as a research-status question
        # in the first place. Before this fix, the check below only ran
        # when ``mission is not None``, so the exact same question asked
        # before any mission existed fell all the way through to the
        # generic natural-language GENERAL_CONVERSATION fallback
        # ("말씀해 주신 불편을 확인했습니다...") - a feedback response to
        # what was actually a research-status question.
        if mission is None and is_mission_candidate_read_request(request.text):
            return (
                "영하님, 현재 진행 중인 Research Mission이 없습니다. 연구를 시작하시려면 "
                "원하시는 종목이나 전략, 시장 범위를 말씀해 주세요.",
                "conversation_research_status_no_mission",
                _dedupe((*warnings, "no active research mission; zero research tool calls")),
                references,
                "deterministic",
                (),
            )
        if (
            mission is not None
            and mission.universe_scope is not MissionUniverseScope.SINGLE_SYMBOL
            and is_mission_candidate_read_request(request.text)
        ):
            explicit_candidate_id = extract_candidate_id(request.text)
            if explicit_candidate_id is not None:
                read_candidate = get_candidate(mission, explicit_candidate_id)
                self._remember_mission(request, mission)
                if read_candidate is None:
                    return (
                        f"영하님, {explicit_candidate_id} 후보를 현재 Research Mission에서 찾을 수 없습니다. "
                        "존재하지 않거나 아직 생성되지 않은 후보 id이며, 다른 종목이나 후보를 임의로 "
                        "대신 연구하지 않습니다.\n\n"
                        f"{mission_status_block(mission)}",
                        "conversation_mission_candidate_read_not_found",
                        _dedupe((*warnings, f"candidate_not_found={explicit_candidate_id}", "read-only; no research tool executed")),
                        references,
                        "deterministic",
                        (),
                    )
                text = self._render_mission_candidate_read_response(request.text, mission, read_candidate)
                self._remember_read_subject(request, mission, kind="candidate", candidate_id=read_candidate.candidate_id)
                return (
                    text,
                    "conversation_mission_candidate_read",
                    _dedupe((*warnings, f"candidate_read={read_candidate.candidate_id}", "read-only; no research tool executed")),
                    references,
                    "deterministic",
                    (),
                )
            active_candidate = get_active_candidate(mission)
            if active_candidate is not None:
                self._remember_mission(request, mission)
                text = self._render_mission_candidate_read_response(request.text, mission, active_candidate)
                self._remember_read_subject(request, mission, kind="candidate", candidate_id=active_candidate.candidate_id)
                return (
                    text,
                    "conversation_mission_candidate_read",
                    _dedupe((*warnings, "mission-aware canonical candidate read model; no research tool executed")),
                    references,
                    "deterministic",
                    (),
                )
            # Hotfix #167 production bug fix: a read-only research-status
            # question about a mission that HAS no active candidate (e.g.
            # blocked_reason="strategy_hypothesis_space_exhausted..." -
            # which, by construction, only ever fires when there is no
            # active candidate - see record_blocked's call site in
            # _try_mission_driven_research_cycle) used to have no branch
            # here at all: falling through silently past this whole `if`
            # block, eventually landing on the GENERAL_CONVERSATION
            # feedback fallback ("말씀해 주신 불편을 확인했습니다...") -
            # a feedback response to what was actually an honestly-
            # answerable research-status question about a mission that
            # DOES exist. Reuses the exact same mission_blocked_message
            # the BLOCKED-mission continuation path
            # (_try_mission_driven_research_cycle) and _render_resource_
            # needs already render for this state - no new blocked-state
            # text is introduced.
            self._remember_mission(request, mission)
            if mission.status is MissionStatus.BLOCKED:
                return (
                    mission_blocked_message(mission),
                    "conversation_mission_blocked",
                    _dedupe((*warnings, "mission blocked; no active candidate; read-only; no research tool executed")),
                    references,
                    "deterministic",
                    (),
                )
            return (
                f"영하님, 현재 Research Mission은 진행 중이지만 아직 생성된 전략 후보가 없습니다.\n\n"
                f"{mission_status_block(mission)}",
                "conversation_mission_no_active_candidate",
                _dedupe((*warnings, "mission has no active candidate yet; read-only; no research tool executed")),
                references,
                "deterministic",
                (),
            )

        # hotfix/conversation-layer-safe-web-parity CASE C: "그중 제일 좋은
        # 건 뭐야?" asks Gaon to compare the mission's WHOLE candidate
        # portfolio - a different question from is_mission_candidate_read_
        # request above, which only ever answers about the single CURRENT/
        # ACTIVE candidate. See is_best_candidate_query/render_mission_
        # candidates_overview in research_mission.py: this never fabricates
        # a performance ranking, only reports each candidate's real
        # persisted stage/evidence.
        if mission is None and is_best_candidate_query(request.text):
            return (
                "영하님, 현재 진행 중인 Research Mission이 없습니다. 연구를 시작하시려면 "
                "원하시는 종목이나 전략, 시장 범위를 말씀해 주세요.",
                "conversation_research_status_no_mission",
                _dedupe((*warnings, "no active research mission; zero research tool calls")),
                references,
                "deterministic",
                (),
            )
        if mission is not None and is_best_candidate_query(request.text):
            self._remember_mission(request, mission)
            self._remember_read_subject(request, mission, kind="candidates_overview")
            return (
                render_mission_candidates_overview(mission),
                "conversation_mission_candidates_overview",
                _dedupe((*warnings, "read-only candidate comparison; no fabricated ranking; no research tool executed")),
                references,
                "deterministic",
                (),
            )

        if (
            existing_tool == "multi_symbol_research"
            and not (
                (context := self._mvp_context_for(request.session_id))
                is not None
                and context.last_result_kind == "autonomous_learning_v2"
                and _is_symbol_generalization_request(request.text)
            )
        ):
            return None

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
            # Patch 8.5 fix: this gate used to block the STATUS_QUERY
            # branch below (mission/candidate status, including the exact
            # "지금 뭐 연구하고 있어?" example that branch's own docstring
            # names) from ever being reached, because none of its natural
            # phrasings happen to contain one of the hand-enumerated
            # supported tokens above - classify_conversational_route's own
            # STATUS_TOKENS-based classification, plus
            # _is_simple_conversational_status_request below, are already
            # a more precise gate for this intent than the blanket token
            # list.
            ConversationalMVPIntent.STATUS_QUERY,
            # Production hotfix: this same blanket-token gate was blocking
            # capability ("뭘 할 수 있나요?" - HELP matches on "뭘 할 수",
            # not the literal "도움말" this gate's token list hard-codes),
            # feedback/general conversation (GENERAL_CONVERSATION), and
            # resource/blocker questions (RESOURCE_NEEDS_QUERY) from ever
            # reaching their own dedicated, already-narrow structural
            # classifiers below - falling through to the legacy
            # UNKNOWN persona fallback instead. Each of these three
            # already has its own precise route classifier in
            # classify_conversational_route; growing the token list above
            # is not the fix (see routing precedence note in
            # gaon.runtime.conversational_mvp).
            ConversationalMVPIntent.HELP,
            ConversationalMVPIntent.GENERAL_CONVERSATION,
            ConversationalMVPIntent.RESOURCE_NEEDS_QUERY,
        }:
            return None
        existing_tool = route_read_only_tool(request.text)
        # Runtime deployment questions require structured runtime evidence.
        # Do not let an assistant provider infer VPS/service state from the
        # wording alone; the existing read-only tool is the authority.
        if existing_tool == "runtime_status":
            return self._try_deterministic_tool(request, warnings, references)
        if existing_tool in {"research_retest", "multi_symbol_research", "multi_symbol_research_status", "multi_symbol_research_history", "champion_status", "v5_pipeline_history"}:
            context = self._mvp_context_for(request.session_id)
            contextual_generalization = (
                existing_tool == "multi_symbol_research"
                and context is not None
                and context.last_result_kind == "autonomous_learning_v2"
                and _is_symbol_generalization_request(request.text)
            )
            if not contextual_generalization and not (
                route.intent in {ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST, ConversationalMVPIntent.RERUN_REQUEST}
                and context is not None
            ):
                return None
        if route.intent in {ConversationalMVPIntent.SINGLE_SYMBOL_ANALYSIS, ConversationalMVPIntent.COMPARE_SYMBOLS} and not (
            _is_simple_conversational_research_request(request.text) and has_explicit_research_execution_intent(request.text)
        ):
            return None
        if route.intent is ConversationalMVPIntent.GREETING:
            self._remember_mvp_response_context(request, route.intent, "conversation_mvp_greeting")
            return render_greeting(), "conversation_mvp_greeting", _dedupe(warnings), references, "deterministic", ()
        if route.intent is ConversationalMVPIntent.HELP:
            self._remember_mvp_response_context(request, route.intent, "conversation_mvp_help")
            return render_help(), "conversation_mvp_help", _dedupe(warnings), references, "deterministic", ()
        if (
            route.intent is ConversationalMVPIntent.STATUS_QUERY
            and _is_simple_conversational_status_request(request.text)
            and mission is not None
            and mission.candidates
            # Hotfix #166: research status vs. runtime status must be
            # distinguished (e.g. "현재 동작 하고 있나요?" is a runtime/
            # availability question, not "지금 뭐 연구하고 있어?" style
            # research status) - an availability-shaped question must
            # always fall through to the grounded runtime/conversational
            # status render below, never be reinterpreted as a mission/
            # candidate status question just because a mission happens to
            # exist. Only excluded when the text carries NO research
            # subject word either - "상태" alone is genuinely ambiguous
            # ("동작 상태" vs "연구 상태"), so a message naming a research
            # subject ("연구 상태 보여줘", "지금 뭐 연구하고 있어?") must
            # still reach this branch even though it also satisfies
            # is_availability_question's broader "상태" match.
            and not (
                is_availability_question(request.text.strip().casefold())
                and not any(token in request.text for token in ("연구", "전략", "미션", "mission", "후보", "candidate"))
            )
        ):
            # "지금 뭐 연구하고 있어?" with an active Research Mission answers
            # from the actual strategy candidate portfolio (Patch 8.2)
            # instead of the generic runtime-status renderer.
            self._remember_mission(request, mission)
            summary_text = render_candidate_status_summary(
                candidate_records(mission),
                current=distinct_promotion_ready_strategy_count(mission),
                target=mission.target_promotion_ready_candidates,
            )
            # Patch 8.5: the detailed per-stage status footer is appended
            # here (not a replacement) so the existing portfolio-summary
            # text/tests above are unchanged.
            detailed_status = render_mission_candidate_detailed_status(mission, get_active_candidate(mission))
            text = f"{summary_text}\n\n{detailed_status}"
            return text, "conversation_mission_candidate_status", _dedupe((*warnings, "mission candidate status")), references, "deterministic", ()
        if route.intent is ConversationalMVPIntent.STATUS_QUERY and _is_simple_conversational_status_request(request.text):
            self._remember_mvp_response_context(request, route.intent, "conversation_mvp_status")
            return render_status(), "conversation_mvp_status", _dedupe(warnings), references, "deterministic", ()
        if route.intent is ConversationalMVPIntent.GENERAL_CONVERSATION:
            # hotfix/conversation-layer-safe-web-parity: render_general_
            # conversation()'s feedback-style apology ("말씀해 주신 불편을
            # 확인했습니다...") is the right honest answer for genuinely
            # uninterpretable input ("맨날 없네요") but the wrong one for an
            # ambiguous research-topic noun phrase ("단타 연구") that merely
            # lacks a clear question/verb shape - that deserves a real,
            # contextual answer (which the recent-history-aware LLM path
            # below can give), not a canned complaint-handling response.
            # Only defer when a real LLM is actually available
            # (assistant_enabled) so a degraded/deterministic-only config
            # keeps today's honest, non-fabricating apology text instead of
            # silently going quiet.
            if self._config.assistant_enabled and (
                route.symbols or any(token in request.text.casefold() for token in _AMBIGUOUS_RESEARCH_TOPIC_TOKENS)
            ):
                return None
            self._remember_mvp_response_context(request, route.intent, "conversation_mvp_general")
            return (
                render_general_conversation(),
                "conversation_mvp_general",
                _dedupe((*warnings, "general conversation; zero research tool calls")),
                references,
                "deterministic",
                (),
            )
        if route.intent is ConversationalMVPIntent.RESOURCE_NEEDS_QUERY:
            text = self._render_resource_needs(self._mission_for(request.session_id))
            self._remember_mvp_response_context(request, route.intent, "conversation_resource_needs")
            return (
                text,
                "conversation_resource_needs",
                _dedupe((*warnings, "resource needs answered from mission/runtime state; zero research tool calls")),
                references,
                "deterministic",
                (),
            )
        if route.intent in reasoning_followup_intents:
            subject_explanation = self._try_mission_subject_explanation(request, route, warnings, references)
            if subject_explanation is not None:
                return subject_explanation
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

    def _try_mission_subject_explanation(
        self,
        request: LLMConversationRequest,
        route: ConversationalRoute,
        warnings: tuple[str, ...],
        references: tuple[str, ...],
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        """hotfix/conversation-layer-subject-intent-continuity production bug
        fix: real production showed "왜 그게 좋은데?" (an EXPLAIN_PREVIOUS_
        RESULT follow-up immediately after a mission candidate-portfolio
        read) answered from the stale, unrelated ConversationalMVPContext -
        a single-slot cache of the last real TOOL result, entirely
        decoupled from which mission/candidate subject the conversation
        was actually just discussing - and rendered a description of a
        much older, unrelated candidate in a way that read exactly like
        Gaon had just re-run research on it.

        ``_remember_read_subject`` tracks WHICH mission/candidate subject a
        read-only mission-aware answer was actually about; this checks
        that tracked subject FIRST, before ``ConversationalMVPContext`` is
        ever consulted, whenever it is at least as recent as that context.
        Returns None (deferring to the caller's existing
        ConversationalMVPContext-based handling) when there is no tracked
        subject, its mission no longer exists, the tracked candidate was
        since removed, or the ConversationalMVPContext is strictly more
        recent (a genuinely later single-symbol/autonomous research turn
        took over as the real subject).

        Only ever reads already-persisted mission/candidate state - zero
        research tool calls in every branch - and never returns a
        fabricated performance ranking (mirrors the same
        score_status=insufficient_evidence precedent
        ``render_mission_candidates_overview`` already establishes)."""
        if route.intent not in {ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT, ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP}:
            return None
        subject = self._read_subject_for(request.session_id)
        if subject is None:
            return None
        mvp_context = self._mvp_context_for(request.session_id)
        if mvp_context is not None and str(mvp_context.updated_at) > str(subject.get("updated_at", "")):
            return None
        mission = self._mission_for(request.session_id)
        if mission is None or mission.mission_id != subject.get("mission_id"):
            return None
        kind = subject.get("kind")
        if kind == "candidates_overview":
            self._remember_mission(request, mission)
            text = (
                "영하님, 아직 후보들을 성능으로 서열화할 신뢰할 수 있는 deterministic 기준이 없어 "
                "특정 후보가 다른 후보보다 '더 좋다'고 단정해서 설명드릴 수는 없습니다.\n\n"
                + render_mission_candidates_overview(mission)
            )
            return (
                text,
                "conversation_mission_subject_explanation",
                _dedupe((*warnings, "mission candidate subject continuity; no fabricated ranking; no research tool executed")),
                references,
                "deterministic",
                (),
            )
        if kind == "candidate":
            candidate_id = subject.get("candidate_id")
            candidate = get_candidate(mission, str(candidate_id)) if candidate_id else None
            if candidate is None:
                return None
            self._remember_mission(request, mission)
            text = f"{render_candidate_strategy_explanation(candidate)}\n\n{render_mission_candidate_detailed_status(mission, candidate)}"
            return (
                text,
                "conversation_mission_subject_explanation",
                _dedupe((*warnings, f"candidate_subject={candidate.candidate_id}", "mission candidate subject continuity; no research tool executed")),
                references,
                "deterministic",
                (),
            )
        return None

    @staticmethod
    def _render_mission_candidate_read_response(text: str, mission: ResearchMission, candidate: "StrategyCandidateRecord") -> str:
        """Patch 8.8: canonical, evidence-bound answer for a read-only
        mission/candidate question - the active ``StrategyCandidateRecord``
        and its owning ``ResearchMission`` are the ONLY source read here,
        never ``ConversationalMVPContext.last_payloads``/
        ``last_structured_results`` (which may be stale or describe an
        unrelated earlier single-symbol run).

        KR-ST-008 production bug fix: the default "status" focus now also
        includes the canonical CUMULATIVE performance evidence
        (breadth sample vs the real performance sample, median return/MDD,
        profitable ratio, economic-viability status/reason, the policy's
        own required performance-sample floor) and the candidate's current
        unresolved blockers - a read-only status question about economic
        viability used to have nowhere to read those fields from at all.
        """
        focus = mission_candidate_read_focus(text)
        if focus == "score":
            return render_candidate_score_status(mission, candidate)
        if focus == "explain":
            return f"{render_candidate_strategy_explanation(candidate)}\n\n{render_mission_candidate_detailed_status(mission, candidate)}"
        summary = render_candidate_status_summary(
            candidate_records(mission),
            current=distinct_promotion_ready_strategy_count(mission),
            target=mission.target_promotion_ready_candidates,
        )
        detailed = render_mission_candidate_detailed_status(mission, candidate)
        evidence = render_candidate_cumulative_evidence_block(candidate)
        blockers = candidate_remaining_blockers(candidate)
        blockers_line = "[현재 blocker]\n- " + (", ".join(blockers) if blockers else "없음 (모든 검증 단계 충족)")
        return f"{summary}\n\n{detailed}\n\n{evidence}\n\n{blockers_line}"

    def _try_mission_driven_research_cycle(
        self,
        request: LLMConversationRequest,
        mission: ResearchMission,
        warnings: tuple[str, ...],
        references: tuple[str, ...],
        *,
        preferred_breadth_symbols: tuple[str, ...] = (),
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        """Continues an active market-wide / selected-symbols mission with one
        bounded research cycle for its ACTIVE STRATEGY CANDIDATE, instead of
        ever collapsing a generic continuation message down to a single
        symbol's identity (Patch 8.2: the primary research object is a
        strategy candidate - see gaon.knowledge.strategy_candidate - a
        symbol is evaluation evidence recorded ON a candidate, never a
        candidate's identity).

        Generates the next untried strategy family as a new candidate when
        none is active. Budget exhaustion within one cycle does not mark
        the mission complete: the mission stays ``active`` and the next
        cycle continues. A hard blocker (provider/data acquisition failure
        across the whole cycle) is recorded explicitly on the mission
        rather than being misread as a negative strategy result.
        """
        if self._tool_executor is None:
            return None
        if mission.status is MissionStatus.BLOCKED:
            self._remember_mission(request, mission)
            text = mission_blocked_message(mission)
            return text, "conversation_mission_blocked", _dedupe((*warnings, "mission blocked; safe explanation only")), references, "deterministic", ()

        active = get_active_candidate(mission)
        if active is not None and is_diversity_request(request.text):
            # "다른 방식도 찾아봐": an explicit user request to bias the next
            # hypothesis cycle toward a different strategy family - treated
            # the same as natural stagnation-driven rotation (never
            # discards accumulated candidate history, just stops actively
            # pursuing this one).
            stagnant = mark_stagnant(active, now=request.received_at, reason="user_requested_different_strategy_family")
            mission = update_candidate(mission, stagnant, now=request.received_at)
            mission = set_active_candidate(mission, None, now=request.received_at)
            mission = clear_focus_symbol(mission, now=request.received_at)
            warnings = (*warnings, f"user_requested_diversity_rotation={stagnant.candidate_id}")
            active = None

        if active is None:
            family = next_untried_family(candidate_records(mission))
            if family is None:
                expansion = expand_strategy_space_candidate(
                    candidate_records(mission),
                    sequence=next_candidate_sequence(mission),
                    now=request.received_at,
                )
                if expansion.candidate is None:
                    updated = record_blocked(
                        mission,
                        reason="strategy_hypothesis_space_exhausted: bounded declarative strategy expansion budget exhausted",
                        now=request.received_at,
                    )
                    self._remember_mission(request, updated)
                    return (
                        mission_blocked_message(updated),
                        "conversation_mission_blocked",
                        _dedupe((*warnings, "strategy hypothesis space exhausted")),
                        references,
                        "deterministic",
                        (),
                    )
                active = expansion.candidate
                mission = add_candidate(mission, active, now=request.received_at)
                warnings = _dedupe(
                    (
                        *warnings,
                        "research_action=EXPAND_STRATEGY_SPACE",
                        f"strategy_space_reason={expansion.reason}",
                        f"strategy_space_evidence={','.join(expansion.evidence_signals)}",
                        f"expanded_candidate={active.candidate_id}",
                    )
                )
                references = _dedupe((*references, "strategy-space:bounded-grammar"))
            else:
                active = new_candidate(family, sequence=next_candidate_sequence(mission), now=request.received_at)
                mission = add_candidate(mission, active, now=request.received_at)

        # Cross-symbol breadth evaluation (multi_symbol_research) and deep
        # single-candidate robustness validation (the full Research
        # Director pipeline) alternate across turns rather than both
        # running inside one request: a research_budget_exhausted signal
        # from either still bounds this turn to a single tool call.
        if not mission.pending_promotion_symbol and active is not None and candidate_sample_exhausted(active):
            planned_action, planned_reason = next_blocker_driven_research_action(active)
            if planned_action == "ROTATE_CANDIDATE":
                return self._rotate_stagnant_candidate(
                    request,
                    mission,
                    active,
                    _dedupe((*warnings, f"sample_exhaustion_decision={planned_reason}")),
                    references,
                    tool_calls=(),
                    extra_warnings=("candidate_pool_exhausted_not_repeated",),
                    reason=planned_reason,
                )
            if planned_action != "EXPAND_SAMPLE":
                next_symbol = next_robustness_evidence_symbol(active)
                if next_symbol is not None:
                    mission = record_focus_symbol(mission, symbol=next_symbol, now=request.received_at)
                    return self._try_candidate_robustness_cycle(
                        request,
                        mission,
                        active,
                        _dedupe((*warnings, f"sample_exhaustion_next_action={planned_action}", f"sample_exhaustion_reason={planned_reason}")),
                        references,
                    )
        if mission.pending_promotion_symbol:
            return self._try_candidate_robustness_cycle(request, mission, active, warnings, references)
        return self._try_candidate_breadth_cycle(
            request,
            mission,
            active,
            warnings,
            references,
            preferred_symbols=preferred_breadth_symbols,
        )

    def _try_candidate_breadth_cycle(
        self,
        request: LLMConversationRequest,
        mission: ResearchMission,
        candidate,
        warnings: tuple[str, ...],
        references: tuple[str, ...],
        *,
        preferred_symbols: tuple[str, ...] = (),
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]:
        """Evaluates ONE strategy candidate's exact rules
        (``candidate.spec_rules``, passed through to ``multi_symbol_research``
        as ``candidate_spec`` - see ``AutonomousMultiSymbolResearchOrchestrator.run``)
        across the mission's symbol universe - the SAME rules on every
        symbol, never a different candidate per symbol."""
        # Root cause fix (KR-ST-008, production 2026-08): this used to run
        # an unconditional new EXPAND_SAMPLE-shaped batch every time it was
        # entered, regardless of whether the candidate's OWN accumulated
        # evidence already called for something else (most importantly: a
        # decisive economic-viability FAIL - see evaluate_economic_viability
        # in gaon.knowledge.strategy_candidate). A candidate could reach
        # this function repeatedly (via any of its several call sites/
        # routing paths) and keep expanding its cross-symbol sample toward
        # the whole candidate pool even after its own cumulative evidence
        # had already decisively shown it loses money. Consulting the same
        # blocker-driven decision every other entry point already uses
        # closes that gap here too, independent of which path led in.
        planned_action, planned_reason = next_blocker_driven_research_action(candidate)
        if planned_action == "ROTATE_CANDIDATE":
            return self._rotate_stagnant_candidate(
                request,
                mission,
                candidate,
                _dedupe((*warnings, f"breadth_cycle_decision={planned_reason}")),
                references,
                tool_calls=(),
                reason=planned_reason,
            )
        if preferred_symbols:
            result = self._execute_mvp_multi_symbol_research(
                request,
                preferred_symbols[:5],
                request.text,
                None,
                None,
                candidate_spec=candidate.spec_rules,
            )
        elif mission.universe_scope is MissionUniverseScope.SELECTED_SYMBOLS:
            batch = next_unexplored_symbols(mission, batch_size=5)
            if not batch:
                updated = record_blocked(mission, reason="selected_symbol_universe_exhausted", now=request.received_at)
                self._remember_mission(request, updated)
                return mission_blocked_message(updated), "conversation_mission_blocked", _dedupe((*warnings, "mission selected-symbol universe exhausted")), references, "deterministic", ()
            result = self._execute_mvp_multi_symbol_research(request, batch, request.text, None, None, candidate_spec=candidate.spec_rules)
        else:
            cycle_text = mission_cycle_request_text(mission)
            # Bounded avoidance: do not spend the next continuation turn on
            # evidence already counted for this same candidate unless a
            # caller supplies an explicit retest reason. This keeps
            # blocker-driven progression from endlessly rediscovering the
            # same symbol set while preserving the existing capped storage
            # model.
            avoid_symbols = tuple(
                dict.fromkeys(
                    (
                        *candidate.excluded_symbols,
                        *candidate.evidence_symbols,
                        *candidate.robustness_evidence_symbols,
                    )
                )
            )
            result = self._execute_mvp_multi_symbol_research(
                request, (), cycle_text, None, None, candidate_spec=candidate.spec_rules, avoid_symbols=avoid_symbols
            )

        if result.status != "success":
            failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
            updated = record_blocked(mission, reason=f"{failure.stage}:{failure.error_type}", now=request.received_at)
            self._remember_mission(request, updated)
            return (
                f"{render_candidate_block(candidate)}\n\n{mission_blocked_message(updated)}\n\n({failure.user_message})",
                f"research_failure_{failure.stage}",
                _dedupe((*warnings, *result.warnings, warning_for_failure(failure))),
                references,
                "deterministic",
                ("multi_symbol_research",),
            )

        output = result.output
        evidence_items = [item for item in _as_list(output.get("evidence")) if isinstance(item, dict)]
        adaptive_sampling = _as_dict(output.get("adaptive_sampling"))
        stop_reason = str(adaptive_sampling.get("stop_reason") or "")
        sample_exhaustion_reason = (
            stop_reason
            if stop_reason in {"candidate_pool_exhausted", "configured_sample_budget_exhausted", "no_new_independent_symbols_available"}
            else None
        )
        attempted = len(evidence_items)
        valid_items = [item for item in evidence_items if item.get("eligible")]
        valid = len(valid_items)
        trade_count = int(_as_dict(output.get("summary")).get("aggregate_trade_count", 0) or 0)
        evidence_symbols = tuple(str(item.get("symbol")) for item in valid_items if item.get("symbol"))
        excluded_symbols = tuple(str(item.get("symbol")) for item in evidence_items if not item.get("eligible") and item.get("symbol"))
        evidence_details = {
            str(item.get("symbol")): {
                "symbol": str(item.get("symbol")),
                "eligible": bool(item.get("eligible")),
                "trade_count": int(
                    item.get("trade_count")
                    or _as_dict(item.get("metrics")).get("trade_count", 0)
                    or 0
                ),
                "metrics": _as_dict(item.get("metrics")),
                "evidence_id": str(item.get("evidence_id") or ""),
                "quality_status": str(item.get("quality_status") or ""),
                "source": str(item.get("source") or ""),
                "fixture_backed": bool(item.get("fixture_backed", False)),
            }
            for item in evidence_items
            if item.get("symbol")
        }
        exclusion = _as_dict(output.get("exclusion_diagnostics"))
        provider_blocked = is_provider_acquisition_blocker(exclusion)

        updated_candidate = record_breadth_progress(
            candidate,
            attempted=attempted,
            valid=valid,
            trade_count=trade_count,
            evidence_symbols=evidence_symbols,
            excluded_symbols=excluded_symbols,
            provider_blocked=provider_blocked,
            now=request.received_at,
            evidence_details=evidence_details,
            sample_exhaustion_reason=sample_exhaustion_reason,
            breadth_summary=_as_dict(output.get("summary")),
        )
        updated_mission = record_cycle_result(
            mission,
            researched_symbols=tuple(str(item.get("symbol")) for item in evidence_items if item.get("symbol")),
            now=request.received_at,
        )
        updated_mission = update_candidate(updated_mission, updated_candidate, now=request.received_at)

        if attempted and valid == 0 and provider_blocked:
            # Every sample in this cycle failed for provider/data-
            # acquisition reasons - a real evidence-acquisition blocker,
            # not a negative validation result for this strategy. The
            # candidate is not penalized (provider_blocked=True above), the
            # mission pauses explicitly instead of silently retrying.
            by_category = _as_dict(exclusion.get("by_category"))
            reason = "provider_acquisition_blocker: " + ",".join(f"{key}={value}" for key, value in sorted(by_category.items()))
            updated_mission = record_blocked(updated_mission, reason=reason, now=request.received_at)
            self._remember_mission(request, updated_mission)
            return (
                f"{render_candidate_block(updated_candidate)}\n\n{mission_blocked_message(updated_mission)}",
                "conversation_mission_blocked",
                _dedupe((*warnings, "provider acquisition blocker; not a negative strategy result")),
                _dedupe((*references, "tool:multi_symbol_research")),
                "deterministic",
                ("multi_symbol_research",),
            )

        if is_stagnant(updated_candidate):
            return self._rotate_stagnant_candidate(request, updated_mission, updated_candidate, warnings, references, tool_calls=("multi_symbol_research",))

        if updated_candidate.has_sufficient_universe_evidence and updated_candidate.evidence_symbols:
            # Patch 8.6 independent-review fix: evidence_symbols[0] never
            # changes once populated (new entries are always appended after
            # older ones - see record_breadth_progress), so re-entering
            # robustness from breadth used to always re-select the FIRST
            # evidence symbol even after next_robustness_evidence_symbol had
            # already rotated through it (and others) in prior robustness
            # cycles - silently re-testing an already-tested symbol instead
            # of actually widening cross-symbol coverage. Prefer the next
            # untried evidence symbol. If none remains, keep the focus
            # clear so the next bounded turn expands the breadth sample
            # instead of re-counting old evidence as new progress.
            next_symbol = next_robustness_evidence_symbol(updated_candidate)
            if next_symbol is not None:
                updated_mission = record_focus_symbol(updated_mission, symbol=next_symbol, now=request.received_at)

        self._remember_mission(request, updated_mission)
        self._remember_mvp_context(request, ConversationalMVPIntent.COMPARE_SYMBOLS, self._payloads_from_multi_symbol_result(output), request.text)

        candidate_text = render_candidate_block(updated_candidate)
        # A within-one-call adaptive-sampling budget exhaustion is a cycle
        # checkpoint, never mission completion: the mission stays active and
        # the caller is told plainly that the mission continues, instead of
        # the opaque generic tool-safety fallback message.
        if is_cycle_budget_exhausted(output):
            text = f"{candidate_text}\n\n{_format_tool_response('multi_symbol_research', output, request.text)}\n\n{mission_budget_exhausted_message(updated_mission)}"
            return (
                text,
                "conversation_mission_cycle_budget_exhausted",
                _dedupe((*warnings, "mission cycle budget exhausted; mission remains active")),
                _dedupe((*references, "tool:multi_symbol_research")),
                "deterministic",
                ("multi_symbol_research",),
            )

        text = (
            f"{candidate_text}\n\n"
            f"[이번 batch]\n{_format_tool_response('multi_symbol_research', output, request.text)}\n\n"
            f"{render_candidate_cumulative_evidence_block(updated_candidate)}\n\n"
            f"{mission_status_block(updated_mission)}"
        )
        return (
            text,
            "conversation_mission_driven_multi_symbol_research",
            _dedupe((*warnings, "mission-driven scope preserved", f"mission_scope={updated_mission.universe_scope.value}", f"active_candidate={updated_candidate.candidate_id}")),
            _dedupe((*references, "tool:multi_symbol_research")),
            "deterministic",
            ("multi_symbol_research",),
        )

    def _try_candidate_robustness_cycle(
        self,
        request: LLMConversationRequest,
        mission: ResearchMission,
        candidate,
        warnings: tuple[str, ...],
        references: tuple[str, ...],
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]:
        """Runs the EXISTING single-candidate Autonomous Learning V2 /
        Research Director pipeline (OOS/walk-forward/regime/cost/Monte Carlo)
        using a symbol drawn from THIS candidate's own validated evidence
        (``candidate.evidence_symbols``) as the evaluation sample, and only
        records a promotion-ready STRATEGY (keyed by
        ``candidate.strategy_fingerprint``, never by the symbol) when that
        real pipeline's already-wired ``research_director_decision`` says
        ``request_human_promotion_review`` - this never invents or weakens
        promotion readiness, it only reads the existing gate's verdict.

        Reuses the SAME cross-turn budget mechanism the existing single-
        symbol Autonomous Learning V2 continuation path already uses
        (``_autonomous_learning_v2_steps_used``): as long as this candidate
        keeps being validated turn over turn, ``steps_used`` carries
        forward instead of resetting to 0 every call, so the Research
        Director can actually advance through its stages instead of
        restarting from scratch - without that, the mission could never
        converge on a promotion-ready candidate. The evaluation symbol is
        only released (and the candidate's status re-evaluated) once the
        Director reaches a terminal decision for it - not after every
        single call - while each turn still makes exactly one bounded tool
        call, so this cannot loop unboundedly within a single request.
        """
        planned_action, planned_reason = next_blocker_driven_research_action(candidate)
        if planned_action == "EXPAND_SAMPLE":
            widened = clear_focus_symbol(mission, now=request.received_at)
            return self._try_candidate_breadth_cycle(
                request,
                widened,
                candidate,
                _dedupe((*warnings, f"planned_action_consumed={planned_action}", f"planned_action_reason={planned_reason}")),
                references,
            )
        if planned_action == "ROTATE_CANDIDATE":
            return self._rotate_stagnant_candidate(
                request,
                mission,
                candidate,
                _dedupe((*warnings, f"planned_action_consumed={planned_action}", f"planned_action_reason={planned_reason}")),
                references,
                tool_calls=(),
                reason=planned_reason,
            )
        symbol = str(mission.pending_promotion_symbol)
        context = self._mvp_context_for(request.session_id)
        continuing_same_candidate = (
            context is not None
            and context.last_result_kind == "autonomous_learning_v2"
            and tuple(context.last_symbols) == (symbol,)
        )
        mode = "continue" if continuing_same_candidate else "research"
        steps_used = _autonomous_learning_v2_steps_used(context, mode)
        request_text = render_candidate_request_text(candidate, symbol)
        result = self._tool_executor.execute(
            ToolRequest(
                "autonomous_learning_research",
                {
                    "request_text": request_text,
                    "symbol": symbol,
                    "mode": mode,
                    "steps_used": steps_used,
                    "planned_action": planned_action,
                    "planned_action_reason": planned_reason,
                },
                request.user_ref,
                request.received_at,
            )
        )
        self._record_tool_result(request.session_id, result, request.received_at)
        if result.status != "success":
            failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
            cleared = clear_focus_symbol(mission, now=request.received_at)
            self._remember_mission(request, cleared)
            return (
                f"{render_candidate_block(candidate)}\n\n{failure.user_message}\n\n{mission_status_block(cleared)}",
                f"research_failure_{failure.stage}",
                _dedupe((*warnings, *result.warnings, warning_for_failure(failure))),
                references,
                "deterministic",
                ("autonomous_learning_research",),
            )
        output = result.output
        tool_text = _format_tool_response("autonomous_learning_research", output, request.text)
        self._remember_autonomous_learning_v2_context(request, output, tool_text)
        learning = _as_dict(output.get("autonomous_learning_v2"))
        director = _as_dict(learning.get("research_director_decision"))
        action = str(director.get("action", "unknown"))
        terminal = bool(director.get("terminal"))

        # Patch 8.5: persist the REAL per-stage status this cycle's
        # EXISTING production_grade_validation output reported (never
        # fabricated - a stage this cycle did not touch is simply absent
        # here, and record_robustness_progress leaves any previously
        # recorded status for it untouched rather than resetting it).
        partner = _as_dict(learning.get("autonomous_quant_partner"))
        grade = _as_dict(partner.get("production_grade_validation"))
        validation_stage_status = {
            key: str(_as_dict(grade[key]).get("status", "unavailable"))
            for key in (
                "multi_symbol_validation", "out_of_sample", "walk_forward",
                "regime_validation", "parameter_sensitivity", "transaction_cost_stress", "monte_carlo",
            )
            if isinstance(grade.get(key), dict)
        }
        planned_stage_key = _validation_stage_key_for_planned_action(planned_action)
        planned_stage_before = (
            str(candidate.validation_stage_status.get(planned_stage_key, "not_run"))
            if planned_stage_key
            else ""
        )
        planned_stage_after = (
            str(validation_stage_status.get(planned_stage_key, planned_stage_before))
            if planned_stage_key
            else ""
        )
        planned_stage_executed = bool(planned_stage_key and planned_stage_key in validation_stage_status)
        planned_action_progress = bool(planned_stage_key and planned_stage_after != planned_stage_before)
        evidence_reference = _planned_action_evidence_reference(
            planned_action,
            symbol=symbol,
            stage_key=planned_stage_key,
            stage_status=planned_stage_after,
        )
        identical_action_replay = bool(evidence_reference and evidence_reference == candidate.last_validation_reference)

        # Patch 8.6 requirement 4: verify identity on EVERY cycle, not only
        # the promotion-triggering one - see ULTRAREVIEW High #1's original
        # comment below, which this generalizes. A cycle whose deep-
        # validation pipeline ended up validating a DIFFERENT effective
        # rule set than this candidate's own fingerprint must never be
        # counted as this candidate's robustness evidence.
        validated_fingerprint = _deep_validation_effective_fingerprint(request_text, symbol=symbol)
        identity_verified = validated_fingerprint == candidate.strategy_fingerprint
        identity_unverified = not identity_verified

        updated_candidate = record_robustness_progress(
            candidate, director_action=action, terminal=terminal, now=request.received_at,
            validation_stage_status=validation_stage_status if identity_verified else None,
            symbol=symbol if identity_verified else None,
            reference=evidence_reference if identity_verified else None,
        )
        updated_mission = mission
        if terminal:
            if action == "request_human_promotion_review":
                updated_mission = clear_focus_symbol(updated_mission, now=request.received_at)
                if identity_verified:
                    # Root cause fix: the deep Research Director's own
                    # "request_human_promotion_review" verdict (see
                    # gaon.research.research_director.ResearchDirector.decide)
                    # only ever checks evidence strength/conflict/robustness
                    # stage completion - it has no notion of whether the
                    # candidate actually made money. Robustness alone must
                    # never reach PROMOTION_READY (item D): this candidate's
                    # own canonical cumulative economic-viability verdict is
                    # checked here, independently, before promotion-ready is
                    # ever recorded.
                    economic_viability = evaluate_economic_viability(updated_candidate)
                    if economic_viability.status is EconomicViabilityStatus.PASS:
                        updated_mission = record_promotion_candidate(
                            updated_mission,
                            strategy_fingerprint=candidate.strategy_fingerprint,
                            candidate_id=candidate.candidate_id,
                            now=request.received_at,
                        )
                        updated_candidate = mark_promotion_ready(updated_candidate, now=request.received_at)
                        updated_mission = set_active_candidate(updated_mission, None, now=request.received_at)
                    elif economic_viability.status is EconomicViabilityStatus.FAIL:
                        updated_candidate = mark_rejected(
                            updated_candidate,
                            reason=f"economic_viability_failed:{economic_viability.reason}",
                            now=request.received_at,
                        )
                        updated_mission = set_active_candidate(updated_mission, None, now=request.received_at)
                    # NEEDS_MORE_EVIDENCE: robustness is done but the
                    # candidate's own economic sample is still below the
                    # decision floor - stay active; the mission is left with
                    # no focus symbol so the next continuation returns to
                    # next_blocker_driven_research_action, which routes an
                    # economically-undecided, robustness-complete candidate
                    # back to EXPAND_SAMPLE rather than fabricating a verdict.
            elif action == "reject_candidate":
                updated_candidate = mark_rejected(updated_candidate, reason="research_director_rejected_candidate", now=request.received_at)
                updated_mission = clear_focus_symbol(updated_mission, now=request.received_at)
                updated_mission = set_active_candidate(updated_mission, None, now=request.received_at)
            else:
                # Patch 8.6 root cause: a HOLD (or any other non-promoting,
                # non-rejecting terminal Research Director decision, e.g.
                # research_budget_exhausted) used to unconditionally clear
                # mission.pending_promotion_symbol here while leaving the
                # candidate active - the candidate stayed "active" but the
                # NEXT turn lost robustness_continuation_precedence
                # eligibility (it requires pending_promotion_symbol to be
                # set), silently falling back to a fresh breadth cycle or,
                # worse, the legacy mission-unaware conversational path.
                # Instead: rotate to a DIFFERENT, not-yet-tried evidence
                # symbol from this candidate's own breadth-validated pool
                # (next_robustness_evidence_symbol already excludes the
                # symbol this cycle just used via updated_candidate's
                # robustness_evidence_symbols) so the SAME strategy
                # fingerprint keeps accumulating robustness evidence across
                # multiple symbols. Only once every known evidence symbol
                # has already been tried does this fall back to clearing
                # the focus symbol, returning the mission to a breadth
                # cycle to gather MORE evidence symbols to rotate through.
                next_symbol = next_robustness_evidence_symbol(updated_candidate, exclude=symbol)
                if next_symbol is not None:
                    updated_mission = record_focus_symbol(updated_mission, symbol=next_symbol, now=request.received_at)
                else:
                    updated_mission = clear_focus_symbol(updated_mission, now=request.received_at)
        updated_mission = update_candidate(updated_mission, updated_candidate, now=request.received_at)
        next_action, next_reason = next_blocker_driven_research_action(updated_candidate)

        if is_stagnant(updated_candidate):
            return self._rotate_stagnant_candidate(request, updated_mission, updated_candidate, warnings, references, tool_calls=("autonomous_learning_research",), extra_warnings=result.warnings)

        self._remember_mission(request, updated_mission)
        next_action, next_reason = next_blocker_driven_research_action(updated_candidate)
        candidate_text = render_candidate_block(updated_candidate)
        if updated_mission.status is MissionStatus.AWAITING_HUMAN_APPROVAL:
            text = f"{candidate_text}\n\n{mission_awaiting_approval_message(updated_mission)}"
        elif updated_candidate.status is StrategyCandidateStatus.REJECTED:
            # Independent-review fix: this generic branch used to render a
            # fixed Korean sentence with no reason at all - a candidate
            # rejected HERE specifically for failing economic viability
            # (see the request_human_promotion_review branch above) lost
            # that specific reason from the user-facing response even
            # though it was correctly persisted in rejected_reason, unlike
            # the parallel _rotate_stagnant_candidate path which already
            # explains an economic rejection explicitly. Surfacing the real
            # persisted reason and the cumulative evidence block here keeps
            # both rejection paths equally informative.
            reason_line = (
                f"사유: {updated_candidate.rejected_reason}\n\n" if updated_candidate.rejected_reason else ""
            )
            text = (
                f"{candidate_text}\n\n"
                f"영하님, {updated_candidate.candidate_id} 전략은 검증 결과 기각되어 다음 사이클에서 다른 전략 후보로 전환합니다.\n\n"
                f"{reason_line}"
                f"{render_candidate_cumulative_evidence_block(updated_candidate)}\n\n"
                f"{mission_status_block(updated_mission)}"
            )
        else:
            # ULTRAREVIEW High #2 fix (Patch 8.6: superseded by the
            # candidate-centric structured response below, which never
            # names the symbol as the strategy's own identity either - the
            # candidate block already carries that identity, the symbol is
            # reported only as an evidence sample). Deliberately does NOT
            # append the full raw tool_text diagnostic dump: every field a
            # user actually asked about (per-stage status, cumulative
            # evidence, promotion-ready count) is already in this
            # structured block, and appending the much longer raw dump
            # pushed real responses past Telegram's message-length split
            # threshold, splitting one logical answer across two Telegram
            # messages.
            text = render_robustness_cycle_response(updated_candidate, updated_mission, symbol=symbol)
            text = f"{text}\n\n{render_candidate_cumulative_evidence_block(updated_candidate)}"
            text = (
                f"{text}\n\n[실행된 연구 action]\n"
                f"- action_executed={planned_action}\n"
                f"- reason={planned_reason}\n"
                f"- validation_dimension={planned_stage_key or 'not_applicable'}\n"
                f"- action_progress={'true' if planned_action_progress else 'false'}\n"
                f"- next_action={next_action}\n"
                f"- next_reason={next_reason}"
            )
            if identity_unverified:
                # Patch 8.6 independent-review fix: the symbol above is
                # genuinely the one this cycle evaluated, but its evidence
                # was withheld from the candidate's recorded state (see
                # identity_verified above) - say so explicitly instead of
                # letting the user believe it silently counted.
                text = f"{text}\n\n[참고] 이번 검증은 후보의 등록된 규칙과 일치가 확인되지 않아 강건성 증거로 반영하지 않았습니다."
        result_warnings = (
            *warnings,
            *result.warnings,
            f"planned_action_consumed={planned_action}",
            f"action_executed={planned_action}",
            f"planned_action_reason={planned_reason}",
            f"planned_action_stage={planned_stage_key or 'none'}",
            f"planned_action_stage_executed={str(planned_stage_executed).lower()}",
            f"planned_action_progress={str(planned_action_progress).lower()}",
            f"identical_action_replay={str(identical_action_replay).lower()}",
            f"next_research_action={next_action}",
            f"next_research_reason={next_reason}",
            f"research_director_action={action}",
        )
        if identity_unverified:
            result_warnings = (*result_warnings, f"candidate_identity_unverified={updated_candidate.candidate_id}")
        return (
            text,
            "conversation_mission_driven_promotion_cycle",
            _dedupe(result_warnings),
            _dedupe((*references, "tool:autonomous_learning_research")),
            "deterministic",
            ("autonomous_learning_research",),
        )

    def _rotate_stagnant_candidate(
        self,
        request: LLMConversationRequest,
        mission: ResearchMission,
        candidate,
        warnings: tuple[str, ...],
        references: tuple[str, ...],
        *,
        tool_calls: tuple[str, ...],
        extra_warnings: tuple[str, ...] = (),
        reason: str | None = None,
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]]:
        """A candidate that made no measurable progress across
        ``STRATEGY_CANDIDATE_STAGNATION_THRESHOLD`` bounded cycles (never
        counting provider/data-acquisition-blocked cycles - see
        ``record_breadth_progress``) is marked stagnant and released as the
        active candidate, so the NEXT continuation generates a genuinely
        different strategy hypothesis instead of endlessly re-researching
        one candidate (or, as production showed, one symbol).

        ``reason`` (root cause fix) is the specific
        ``next_blocker_driven_research_action`` reason that produced this
        ROTATE_CANDIDATE decision (e.g. "economic_viability_failed:..."), so
        WHY this candidate was rotated out is persisted on the record
        (``rejected_reason``) rather than only ever appearing as a
        transient warning string. An economic-viability failure is recorded
        as REJECTED (a deliberate, evidence-based verdict), never as the
        generic STAGNANT ("no measurable progress") status, since this
        candidate progressed plenty - it just decisively lost money.
        """
        is_economic_rejection = bool(reason and reason.startswith("economic_viability_failed"))
        if is_economic_rejection:
            rotated = mark_rejected(candidate, reason=reason, now=request.received_at)
            status_line = (
                f"영하님, {rotated.candidate_id} 전략은 충분한 누적 증거(경계 이상) 하에서 "
                "경제적 타당성(누적 수익률/수익 종목 비율)이 기준에 미달하여 기각되었습니다. "
                "다음 연구 사이클에서는 다른 전략 후보로 전환하겠습니다."
            )
            response_route = "conversation_mission_candidate_economic_rejection"
        else:
            # Independent-review fix: pass reason through only when the
            # caller actually supplied one, rather than duplicating
            # mark_stagnant's own default text as a second inline literal
            # that could silently drift out of sync with it.
            rotated = mark_stagnant(candidate, now=request.received_at, **({"reason": reason} if reason else {}))
            status_line = (
                f"영하님, {rotated.candidate_id} 전략은 여러 사이클 동안 뚜렷한 진전이 없어 "
                "다음 연구 사이클에서는 다른 전략 후보로 전환하겠습니다."
            )
            response_route = "conversation_mission_candidate_stagnant"
        updated_mission = update_candidate(mission, rotated, now=request.received_at)
        updated_mission = set_active_candidate(updated_mission, None, now=request.received_at)
        updated_mission = clear_focus_symbol(updated_mission, now=request.received_at)
        self._remember_mission(request, updated_mission)
        text = (
            f"{render_candidate_block(rotated)}\n\n"
            f"{status_line}\n\n"
            f"{mission_status_block(updated_mission)}"
        )
        return (
            text,
            response_route,
            _dedupe((*warnings, *extra_warnings, f"candidate_rotated={rotated.candidate_id}", f"candidate_rotation_reason={reason or 'stagnation'}")),
            references,
            "deterministic",
            tool_calls,
        )

    def _mission_aware_continuation_fail_safe(
        self,
        request: LLMConversationRequest,
        route,
        warnings: tuple[str, ...],
        references: tuple[str, ...],
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        """Item 7 fail-safe: a market-wide/selected-symbol mission with a
        real active candidate must never silently fall through into the
        LEGACY single-symbol autonomous-research path and resolve its
        target symbol from STALE per-session conversational context - the
        exact mechanism behind the KR-ST-008 production defect. Called at
        every point in ``_try_autonomous_research_conversation`` that is
        about to do that (i.e. some legacy mode/learning_mode was
        detected and ``route.symbols`` is empty, so symbol resolution
        would fall back to ``context.last_symbols``).

        Returns the canonical mission continuation cycle instead - the
        legacy classifier already detected SOME continuation/research-
        shaped signal to reach this point, so redirecting to the real
        mission-driven cycle (rather than guessing with a stale symbol,
        or refusing outright) is the correct behavior. Returns ``None``
        when this fail-safe does not apply (no active mission/candidate,
        or the message explicitly names a different symbol), so the
        caller proceeds with its own logic unchanged.
        """
        if route.symbols:
            return None
        mission = self._mission_for(request.session_id)
        if mission is None or mission.universe_scope is MissionUniverseScope.SINGLE_SYMBOL:
            return None
        active_candidate = get_active_candidate(mission)
        if active_candidate is None:
            return None
        return self._try_mission_driven_research_cycle(request, mission, warnings, references)

    def _try_autonomous_research_conversation(self, request: LLMConversationRequest, route, warnings: tuple[str, ...], references: tuple[str, ...]) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        if self._tool_executor is None:
            return None
        context = self._mvp_context_for(request.session_id)
        if (
            context is not None
            and context.last_result_kind == "autonomous_learning_v2"
            and _should_use_promotion_candidate_presentation(request.text)
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
                fail_safe = self._mission_aware_continuation_fail_safe(request, route, warnings, references)
                if fail_safe is not None:
                    return fail_safe
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
        fail_safe = self._mission_aware_continuation_fail_safe(request, route, warnings, references)
        if fail_safe is not None:
            return fail_safe
        if not route.symbols:
            omitted_subject = self._omitted_subject_clarification(request, warnings, references)
            if omitted_subject is not None:
                return omitted_subject
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
        # Checked before the generic "no context at all" branch below: a
        # bare backward-reference pronoun ("그거") gets its own, more
        # specific clarification regardless of whether some (possibly
        # stale/unrelated) context happens to exist - see
        # ``_omitted_subject_clarification``'s module note.
        if not route.symbols:
            omitted_subject = self._omitted_subject_clarification(request, warnings, references)
            if omitted_subject is not None:
                return omitted_subject
        if context is None and not route.symbols:
            return "영하님, 직전 연구나 전략 맥락이 없습니다. 이어서 자율 연구할 종목을 먼저 삼성전자처럼 말씀해 주세요.", "conversation_autonomous_learning_missing_target", _dedupe((*warnings, "autonomous learning requires target")), references, "deterministic", ()
        symbol = _resolve_autonomous_symbol(route, context)
        if (
            mode == "continue"
            and context is not None
            and context.last_result_kind == "autonomous_learning_v2"
            and not route.symbols
            and _is_symbol_generalization_request(request.text)
        ):
            generalization = self._try_autonomous_learning_generalization(request, context, symbol, warnings, references)
            if generalization is not None:
                return generalization
        previous_text = previous_request_text(context, request.text) if context is not None else None
        execution_text = _autonomous_learning_execution_text(
            request.text,
            previous_text=previous_text,
            mode=mode,
        )
        steps_used = _autonomous_learning_v2_steps_used(context, mode)
        result = self._tool_executor.execute(
            ToolRequest(
                "autonomous_learning_research",
                {"request_text": execution_text, "symbol": symbol, "mode": mode, "steps_used": steps_used},
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

    def _try_autonomous_learning_generalization(
        self,
        request: LLMConversationRequest,
        context: ConversationalMVPContext,
        symbol: str,
        warnings: tuple[str, ...],
        references: tuple[str, ...],
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        """Route "다른 종목에도 일반화되는지 확인해봐" through the Research
        Director's own expand_symbols judgment instead of blindly re-running
        the single-symbol pipeline or requiring the user to name peers.

        Returns None (falls through to the normal continuation path) unless
        the Director, looking at the stored candidate's actual state, agrees
        expand_symbols is the right next step - this never overrides a
        Director decision, it only acts on one that already says so.
        """
        from gaon.knowledge.research_director_bridge import decide_next_research_action

        payload = dict(context.last_detail_payload)
        decision = decide_next_research_action(payload)
        if decision.action.value != "expand_symbols":
            return None
        candidate_context = _as_dict(_as_dict(payload.get("autonomous_learning_v2")).get("promotion_candidate_context"))
        candidate_id = str(candidate_context.get("candidate_id") or "unknown")
        candidate_fingerprint = str(candidate_context.get("fingerprint") or candidate_context.get("candidate_fingerprint") or "")
        peers = tuple(code for code in _KNOWN_KRX_GENERALIZATION_PEERS if code != symbol)[:2]
        result = self._execute_mvp_multi_symbol_research(request, (symbol, *peers), request.text, None, None)
        self._record_tool_result(request.session_id, result, request.received_at)
        if result.status != "success":
            failure = classify_tool_failure(str(result.output.get("error_type", "ToolError")), str(result.output.get("message", "")))
            return failure.user_message, f"research_failure_{failure.stage}", _dedupe((*warnings, *result.warnings, warning_for_failure(failure))), references, "deterministic", ("multi_symbol_research",)
        text = _format_tool_response("multi_symbol_research", result.output, request.text)
        lineage_note = f"\n\n(기존 candidate_id={candidate_id} 계보를 유지한 채 다른 종목으로 일반화를 확인했습니다.)" if candidate_id != "unknown" else ""
        self._remember_mvp_context(request, ConversationalMVPIntent.COMPARE_SYMBOLS, self._payloads_from_multi_symbol_result(result.output), text + lineage_note)
        audit_warnings = (
            "research_director_action=expand_symbols",
            f"candidate_lineage_id={candidate_id}",
            f"candidate_lineage_fingerprint={candidate_fingerprint or 'unknown'}",
        )
        return (
            text + lineage_note,
            "conversation_autonomous_learning_generalization",
            _dedupe((*warnings, *result.warnings, *audit_warnings)),
            _dedupe((*references, "tool:multi_symbol_research")),
            "deterministic",
            ("multi_symbol_research",),
        )

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

    def _execute_mvp_multi_symbol_research(self, request: LLMConversationRequest, symbols: tuple[str, ...], request_text: str, start_date: str | None, end_date: str | None, *, candidate_spec: Mapping[str, object] | None = None, avoid_symbols: tuple[str, ...] = ()):
        arguments: dict[str, object] = {"request_text": request_text, "symbols": symbols, "universe_type": "explicit"}
        if start_date is not None:
            arguments["start_date"] = start_date
        if end_date is not None:
            arguments["end_date"] = end_date
        if candidate_spec is not None:
            arguments["candidate_spec"] = dict(candidate_spec)
        if avoid_symbols:
            arguments["avoid_symbols"] = list(avoid_symbols)
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

    def _render_resource_needs(self, mission: ResearchMission | None) -> str:
        """Answers "어떤 자원이 필요한가요" from real mission/blocker state
        only - never a provider-invented claim about compute or data
        access. See ``gaon.knowledge.strategy_candidate.
        candidate_remaining_blockers``/``next_blocker_driven_research_
        action`` (the same read models the mission-driven research cycle
        itself already consults) and ``mission_blocked_message`` (the
        existing honest BLOCKED-mission explanation)."""
        if mission is None:
            return "영하님, 현재 활성 Research Mission이 없어 특별히 필요한 자원이 없습니다. 연구를 시작하시려면 원하시는 종목이나 전략을 말씀해 주세요."
        if mission.status is MissionStatus.BLOCKED:
            return mission_blocked_message(mission)
        if mission.status is MissionStatus.AWAITING_HUMAN_APPROVAL:
            return mission_awaiting_approval_message(mission)
        active = get_active_candidate(mission)
        if active is None:
            return "영하님, 현재 Research Mission은 진행 중이며 아직 특별한 blocker는 없습니다. 다음 연구 사이클에서 첫 전략 후보를 생성합니다."
        blockers = candidate_remaining_blockers(active)
        action, reason = next_blocker_driven_research_action(active)
        if not blockers:
            return f"영하님, 현재 활성 후보 {active.candidate_id}에 남은 blocker는 없습니다. 다음 단계: {action} ({reason})."
        return (
            f"영하님, 현재 활성 후보 {active.candidate_id}에 필요한 것은 다음 검증 단계를 위한 real 데이터/평가입니다.\n"
            f"- 남은 검증 항목: {', '.join(blockers)}\n"
            f"- 다음 연구 action: {action} ({reason})\n"
            "이 외에 추가로 부족한 계산/데이터 자원은 현재 확인된 바 없습니다."
        )

    def _mission_for(self, session_id: str) -> ResearchMission | None:
        try:
            session = self._repository.get_session(session_id)
        except KeyError:
            return None
        root = session.metadata.get("conversation_mvp")
        if not isinstance(root, dict):
            return None
        raw = root.get("research_mission")
        if not isinstance(raw, dict):
            return None
        try:
            return ResearchMission.from_json(raw)
        except (KeyError, ValueError, TypeError):
            return None

    def _remember_mission(self, request: LLMConversationRequest, mission: ResearchMission) -> None:
        try:
            session = self._repository.get_session(request.session_id)
        except KeyError:
            return
        metadata = dict(session.metadata)
        payload = _mvp_metadata_root(metadata)
        payload["research_mission"] = mission.to_json()
        metadata["conversation_mvp"] = payload
        self._repository.upsert_session(LLMConversationSession(session.session_id, session.user_ref, session.source, session.status, session.created_at, request.received_at, metadata))

    # hotfix/conversation-layer-subject-intent-continuity: a mission-aware
    # READ answer (the candidate-portfolio overview, or a specific
    # candidate's own status/explain read) and the older, unrelated
    # ConversationalMVPContext (a single-slot cache of the last real TOOL
    # result, populated only by single-symbol/autonomous research turns)
    # are two separate, unsynchronized stores. Real production showed a
    # subsequent explanation follow-up ("왜 그게 좋은데?") reading
    # exclusively from the stale ConversationalMVPContext - which could
    # describe an entirely different, much older candidate/symbol than the
    # one the last TWO turns were actually discussing - and rendering it in
    # a way that read like Gaon had just re-run research on that unrelated
    # subject. This lightweight, session-metadata-persisted pointer (same
    # ``conversation_mvp`` JSON root ConversationalMVPContext/ResearchMission
    # already use - no new database table) records WHICH mission/candidate
    # subject a read-only answer was actually about, so a later explanation
    # follow-up can ground itself in the CORRECT, most recently discussed
    # subject instead of whichever store happens to be non-None. Writing
    # this is always paired with an existing read-only response path (never
    # with any tool execution), so it never grants or implies execution
    # authority - resolving to it can only ever route into read-only
    # rendering; the safe executor boundary and
    # ``has_explicit_research_execution_intent`` remain the only gates that
    # can ever approve a REAL research tool call.
    def _remember_read_subject(
        self,
        request: LLMConversationRequest,
        mission: ResearchMission,
        *,
        kind: str,
        candidate_id: str | None = None,
    ) -> None:
        try:
            session = self._repository.get_session(request.session_id)
        except KeyError:
            return
        metadata = dict(session.metadata)
        payload = _mvp_metadata_root(metadata)
        payload["last_read_subject"] = {
            "kind": kind,
            "mission_id": mission.mission_id,
            "candidate_id": candidate_id,
            "text": _bounded_context_text(request.text),
            "updated_at": request.received_at,
        }
        metadata["conversation_mvp"] = payload
        self._repository.upsert_session(LLMConversationSession(session.session_id, session.user_ref, session.source, session.status, session.created_at, request.received_at, metadata))

    def _omitted_subject_clarification(
        self,
        request: LLMConversationRequest,
        warnings: tuple[str, ...],
        references: tuple[str, ...],
    ) -> tuple[str, str, tuple[str, ...], tuple[str, ...], str, tuple[str, ...]] | None:
        """hotfix/conversation-layer-subject-intent-continuity: "그거 다시
        연구해줘" - an execution request naming no concrete subject, only a
        bare backward-reference pronoun - must never silently resolve to
        whatever a stale ``ConversationalMVPContext`` happens to hold
        (``_resolve_autonomous_symbol`` falls back to
        ``context.last_symbols[0]``, then to a hardcoded "005930"
        placeholder) when nothing actually establishes what "그거" refers
        to. This is the exact class of production defect
        ``render_robustness_cycle_response``'s own module note already
        names (a report reading "<UNRELATED SYMBOL> 전략을 다시
        연구했습니다").

        Returns the fail-closed clarification response (zero research tool
        calls) when ``request.text`` is an omitted-subject reference
        (``_is_omitted_subject_execution_reference``) AND there is no
        resolvable subject to ground it - no ResearchMission, or a mission
        with no active candidate. Returns None otherwise (the caller
        should proceed with its own normal resolution): when a non-single-
        symbol mission DOES have a real active candidate, the mission-
        driven candidate-continuation precedence hook in
        ``_try_conversational_mvp`` (checked BEFORE any of this method's
        callers ever run) already resolves and continues that candidate
        correctly, so this is never reached for that case."""
        if not _is_omitted_subject_execution_reference(request.text):
            return None
        mission = self._mission_for(request.session_id)
        if mission is not None and get_active_candidate(mission) is not None:
            return None
        return (
            "영하님, '그거'/'그것'이 어떤 종목이나 전략 후보를 가리키는지 명확하지 않아 "
            "임의의 대상으로 연구를 실행하지 않았습니다. 다시 연구할 종목명, 후보 id, 또는 "
            "전략을 말씀해 주시면 바로 진행하겠습니다.",
            "conversation_research_subject_unresolved",
            _dedupe((*warnings, "omitted-subject reference with no resolvable research target; zero research tool calls")),
            references,
            "deterministic",
            (),
        )

    def _read_subject_for(self, session_id: str) -> dict[str, object] | None:
        try:
            session = self._repository.get_session(session_id)
        except KeyError:
            return None
        root = session.metadata.get("conversation_mvp")
        if not isinstance(root, dict):
            return None
        subject = root.get("last_read_subject")
        if not isinstance(subject, dict) or not subject.get("mission_id"):
            return None
        return subject

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
        # Same conversation-layer safety boundary as
        # _try_authoritative_research_tool - this fallback path is also
        # reached with a real (non-"deterministic") assistant_provider on a
        # provider timeout/error (see _generate's ProviderError handler), so
        # it must not let a status/read-shaped message that merely mentions
        # a strict real-research tool's topic execute that tool.
        if is_strict_real_research_tool(tool_name) and not has_explicit_research_execution_intent(request.text):
            return None
        # Same omitted-subject safeguard as _try_authoritative_research_tool
        # - see ``_omitted_subject_clarification``'s module note.
        if is_strict_real_research_tool(tool_name):
            omitted_subject = self._omitted_subject_clarification(request, warnings, references)
            if omitted_subject is not None:
                return omitted_subject
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


# hotfix/conversation-layer-safe-web-parity: see the GENERAL_CONVERSATION
# branch of _try_conversational_mvp above.
_AMBIGUOUS_RESEARCH_TOPIC_TOKENS: tuple[str, ...] = ("연구", "전략", "후보", "검증", "단타", "스윙", "중장기")


def _is_autonomous_learning_boundary_request(text: str) -> bool:
    normalized = text.casefold()
    if any(token in normalized for token in ("매수", "매도", "주문", "buy", "sell", "order", "broker", "kis", "shell", "powershell", "cmd", "sql", "secret")):
        return False
    return _autonomous_learning_request_mode(text) is not None


def _safe_boundary_negation(value: str) -> bool:
    safety_terms = ("자동주문", "champion자동승격", "승인없는config변경", "승인없는", "nolivetrading", "noapprovalbypass", "nobroker", "nokis")
    negation_terms = ("하지마", "하지말", "하지말고", "하지않", "금지", "없는", "no", "not", "without")
    return any(term in value for term in safety_terms) and any(term in value for term in negation_terms)


_WEB_READ_ONLY_PROBE_MARKER_SUFFIX = " readonly"


def _is_conversational_mvp_source(request: LLMConversationRequest) -> bool:
    # hotfix/conversation-layer-safe-web-parity: a real Web Dashboard human
    # message (GaonWebChatAdapter.handle always stamps source="web" and a
    # "web:"-prefixed message_id, mirroring Telegram's own "telegram:"
    # prefix) is now admitted to the same conversational-MVP pipeline
    # Telegram uses, so Web gets the same mission-aware STATUS/READ,
    # availability, and multi-turn ConversationalMVPContext follow-up
    # handling Telegram already has - transport should only change how a
    # message arrives, not which conversation brain answers it. This is
    # deliberately NOT done in isolation: _try_authoritative_research_tool,
    # _try_deterministic_tool, and assistant_tool_definitions were first
    # gated behind has_explicit_research_execution_intent so that widening
    # this predicate cannot, by itself, let a Web status/read question reach
    # a real research-execution tool it could not reach before.
    #
    # A web read_only=True diagnostic probe (GaonWebChatAdapter.handle
    # appends its own _READ_ONLY_TEXT_MARKER, "readonly", as a text suffix -
    # never sent by real dashboard chat traffic, which always defaults
    # read_only=False) is deliberately excluded here: that literal suffix is
    # ALSO one of research_mission._READ_ONLY_INTENT_TOKENS
    # (is_explicit_read_only_query), a marker designed for Telegram natural
    # language ("실행하지 말고 read-only로 알려주세요"), not for a bare
    # runtime-status probe. Admitting it would let an unrelated status ping
    # get reinterpreted as a research-mission read-only question. A
    # read_only probe is meant to stay a side-effect-free diagnostic ping
    # through the pre-existing deterministic-tool path, not gain
    # ConversationalMVPContext state.
    if request.source == "web" and request.text.casefold().endswith(_WEB_READ_ONLY_PROBE_MARKER_SUFFIX):
        return False
    return (
        (request.source == "telegram" and str(request.message_id or "").startswith("telegram:"))
        or (request.source == "web" and str(request.message_id or "").startswith("web:"))
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


# hotfix/conversation-layer-subject-intent-continuity: "그거 다시 연구해줘"
# (an execution request naming no concrete subject, only a bare backward-
# reference pronoun) must never let _try_authoritative_research_tool /
# _try_deterministic_tool silently resolve "그거" to
# _default_tool_arguments' hardcoded "005930" placeholder - see those
# methods' module notes. False whenever the message ALSO names an
# explicit symbol/company alias (extract_symbol_entities) or an explicit
# candidate id (extract_candidate_id) - those already carry their own
# real subject and need no clarification.
_OMITTED_SUBJECT_REFERENCE_TOKENS: tuple[str, ...] = ("그거", "그것", "이거", "이것", "저거", "저것")


def _is_omitted_subject_execution_reference(text: str) -> bool:
    normalized = text.casefold()
    if not any(token in normalized for token in _OMITTED_SUBJECT_REFERENCE_TOKENS):
        return False
    if extract_symbol_entities(text):
        return False
    if extract_candidate_id(text) is not None:
        return False
    return True


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
        scope = resolve_market_scope(text)

        # Explicit symbols always have precedence over generic whole-market
        # language elsewhere in the request. Example: a five-symbol request
        # may later say "apply the same strategy to all symbols".
        if scope is not None:
            explicit_symbols = extract_market_symbols(
                text,
                scope,
            )

            if explicit_symbols:
                return {
                    "request_text": text,
                    "symbols": explicit_symbols,
                    "universe_type": "explicit",
                    "start_date": start_date,
                    "end_date": end_date,
                }

            if scope.universe_requested:
                return {
                    "request_text": text,
                    "symbols": (),
                    "universe_type": "curated",
                    "start_date": start_date,
                    "end_date": end_date,
                }

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


def _extract_krx_market_scope(text: str) -> str | None:
    scope=resolve_market_scope(text)
    if scope is None or scope.market!="KR": return None
    if set(scope.exchanges)=={"KOSPI","KOSDAQ"}: return "ALL"
    return scope.exchanges[0] if len(scope.exchanges)==1 else "ALL"

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
    if is_stop_or_negation_request(text):
        # Independent-review fix: this classifier's own "continue_terms"
        # below includes bare "연구계속"/"계속해" - substrings that a STOP
        # message like "연구 계속하지 마세요" ALSO contains (as a prefix),
        # so this function used to independently misclassify a stop
        # request as mode="continue" even after
        # is_generic_continuation_request correctly rejected it - a
        # second, separate path into research execution for the exact
        # defect this module's read-only/continuation fix closes. The
        # top-level STOP gate in
        # LLMConversationBrain._try_conversational_mvp already intercepts
        # this before this function is ever called; this guard is
        # defense-in-depth for any other caller.
        return None
    if _has_fresh_research_execution_markers(text):
        return "validate"
    learning = ("지금까지무엇을배웠", "지금까지뭘배웠", "무엇을배웠", "뭘배웠", "학습기록", "learningmemory", "whatlearned")
    critique = ("문제점을찾아", "문제점을찾아줘", "약점을분석", "약점", "취약", "개선해", "보완", "critic", "critique")
    compare = ("어느종목", "어떤종목", "더잘맞", "비교", "compare", "whichsymbol")
    continue_terms = (
        "계속연구", "더연구", "다음검증", "계속검증", "continue",
        "다음연구", "연구진행", "연구계속", "이어서연구", "이어가",
        "계속해", "계속진행", "다음단계연구",
        "증거가충분할때까지", "증거가충분해질때까지",
        "근거가충분할때까지", "근거가충분해질때까지",
        "부족하지않을때까지", "결론을내릴수있을때까지",
    )
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
    if is_stop_or_negation_request(text):
        # See the matching guard in _autonomous_request_mode above - this
        # classifier's "continuation" tuple also contains bare "연구계속"/
        # "계속해", which a STOP message like "연구 계속하지 마세요" also
        # contains as a prefix.
        return None
    if any(token in normalized for token in (
        "다중종목", "여러종목", "복수종목", "모든종목",
        "한국주식전체", "국내주식전체", "한국주식전종목", "국내주식전종목",
        "코스피코스닥", "코스피와코스닥", "코스피및코스닥", "krx전체", "krx전종목",
        "crosssymbol", "multisymbol", "multi-symbol",
    )):
        return None
    if any(token in normalized for token in ("품질점수", "연구품질점수", "퀄리티", "quality", "score", "점수")):
        return None
    explicit_v2 = _has_explicit_autonomous_learning_v2_intent(text)
    memory_only = any(token in normalized for token in ("비슷한", "유사", "지난연구", "이전연구", "연구했", "기억", "메모리", "저장된", "memory"))
    if memory_only and not explicit_v2:
        return None
    approval = ("승인요청", "승격승인", "좋은전략후보", "가장좋은후보", "좋으면알아서적용", "좋으면적용", "알아서적용", "bestcandidate", "promotioncandidate")
    continuation = (
        "계속연구", "더연구", "추가연구", "자료를더", "근거를더",
        "continueresearch", "continuelearning",
        "다음연구", "연구진행", "연구계속", "이어서연구", "이어가",
        "계속해", "계속진행", "다음단계연구",
        "증거가충분할때까지", "증거가충분해질때까지",
        "근거가충분할때까지", "근거가충분해질때까지",
        "부족하지않을때까지", "결론을내릴수있을때까지",
        *_GENERALIZATION_REQUEST_TOKENS,
    )
    external = ("자료를찾아", "자료찾아", "연구자료", "연구자료를찾아", "외부연구자료", "외부자료", "근거자료", "evidence", "externalresearch", "findevidence")
    improvement = ("문제점을찾", "약점을찾", "후보를만", "다시연구", "처음부터다시연구", "처음부터다시연구해")
    learning = ("지금까지배운", "배운내용", "학습내용", "learningmemory")
    robustness = ("oos", "outofsample", "워크포워드", "walkforward", "walk-forward", "시장국면", "레짐", "regime", "파라미터민감도", "거래비용", "transactioncost", "몬테카를로", "montecarlo", "monte-carlo", "robustness")
    plain_start = ("전략연구", "전략을연구", "전략연구해", "autonomousresearch", "autonomouslearning")
    subject = ("삼성전자", "005930", "전략", "연구", "검증", "백테스트", "실제", "시장데이터", "strategy", "research", "validate")
    fresh_execution_override = _has_fresh_research_execution_markers(text)
    if fresh_execution_override:
        return "research"
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


def _has_fresh_research_execution_markers(text: str) -> bool:
    normalized = re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
    restart_tokens = (
        "처음부터다시연구",
        "다시처음부터연구",
        "처음부터연구",
        "새로연구",
    )
    execution_tokens = (
        "provider",
        "fingerprint",
        "oos",
        "walkforward",
        "거래비용",
        "재검증",
        "새후보",
    )
    return (
        any(token in normalized for token in restart_tokens)
        and any(token in normalized for token in execution_tokens)
    )


def _is_fresh_autonomous_learning_execution_request(text: str) -> bool:
    mode = _autonomous_learning_request_mode(text)
    return (
        mode in {"research", "external_research"}
        and _has_explicit_autonomous_learning_v2_intent(text)
        and _has_fresh_research_execution_markers(text)
    )


def _should_use_promotion_candidate_presentation(text: str) -> bool:
    return (
        _is_promotion_candidate_presentation_request(text)
        and not _is_fresh_autonomous_learning_execution_request(text)
    )


_GENERALIZATION_REQUEST_TOKENS = ("다른종목", "다른종목에도", "다른주식", "다른주식에도", "일반화")
# Same known-symbol universe _extract_krx_symbols() already falls back to;
# reused here as the default peer pool when the user asks for
# generalization without naming any peer symbols themselves.
_KNOWN_KRX_GENERALIZATION_PEERS = ("005930", "000660", "005380", "035420", "051910")


def _is_symbol_generalization_request(text: str) -> bool:
    """"다른 종목에도 일반화되는지 확인해봐" style requests: no explicit symbol
    is named, so this cannot be handled as an ordinary COMPARE_SYMBOLS
    request (which requires >= 2 named symbols) - it asks the Research
    Director's own expand_symbols judgment to pick peers for the candidate
    already under research."""
    normalized = re.sub(r"[\s\W_]+", "", text.casefold(), flags=re.UNICODE)
    if not normalized:
        return False
    return any(token in normalized for token in _GENERALIZATION_REQUEST_TOKENS)


def _autonomous_learning_v2_steps_used(context: "ConversationalMVPContext | None", mode: str) -> int:
    """Read the Research Director's step counter forward from stored V2 context.

    A fresh research request (anything other than an explicit continuation
    of an existing autonomous_learning_v2 candidate) starts a new budget at
    0. A continuation increments the count the previous turn round-tripped
    through the payload (research_director_steps_used), so the Director's
    budget check in gaon.knowledge.research_director_bridge actually spans
    the whole conversation instead of resetting every call.
    """
    if context is None or context.last_result_kind != "autonomous_learning_v2" or mode != "continue":
        return 0
    payload = _as_dict(context.last_detail_payload.get("autonomous_learning_v2"))
    previous = int(payload.get("research_director_steps_used", 0) or 0)
    return previous + 1


_PLANNED_ACTION_STAGE_KEYS: Mapping[str, str] = {
    "RUN_OOS": "out_of_sample",
    "RUN_WALK_FORWARD": "walk_forward",
    "RUN_REGIME": "regime_validation",
    "RUN_COST_STRESS": "transaction_cost_stress",
    "RUN_SENSITIVITY": "parameter_sensitivity",
    "RUN_MONTE_CARLO": "monte_carlo",
}


def _validation_stage_key_for_planned_action(action: str) -> str | None:
    return _PLANNED_ACTION_STAGE_KEYS.get(action)


def _planned_action_evidence_reference(
    action: str,
    *,
    symbol: str,
    stage_key: str | None,
    stage_status: str,
) -> str:
    return "|".join((f"action={action}", f"symbol={symbol}", f"stage={stage_key or 'none'}", f"status={stage_status}"))


def _autonomous_learning_execution_text(
    current_text: str,
    *,
    previous_text: str | None,
    mode: str,
) -> str:
    if (
        mode in {"research", "external_research"}
        and _has_explicit_autonomous_learning_v2_intent(current_text)
        and _has_fresh_research_execution_markers(current_text)
    ):
        return current_text
    return previous_text or current_text


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


_OPAQUE_TOOL_SAFETY_FALLBACK_TEXT = "요청하신 도구 호출은 안전 검증을 통과하지 못했습니다, 영하님."


def _format_multi_tool_response(results: tuple[AssistantToolResult, ...]) -> str:
    grounded = [_format_tool_result_response(result) for result in results if result.result.get("status") == "success"]
    grounded = [item for item in grounded if item]
    if grounded:
        return "\n\n".join(grounded)
    successful = [result.name for result in results if result.result.get("status") == "success"]
    if successful:
        return f"요청하신 읽기 전용 도구 결과를 확인했습니다, 영하님.\n실행 도구: {', '.join(successful)}"
    return _OPAQUE_TOOL_SAFETY_FALLBACK_TEXT


_UNCLEAR_TOOL_FAILURE_TEXT = (
    "영하님, 이번 연구 사이클을 더 진행하지 못했습니다.\n"
    "연구 목표는 유지됩니다.\n"
    "상세 원인은 현재 실행 결과만으로 확정할 수 없습니다."
)

_POLICY_DENIAL_TEXT = "영하님, 이번 요청의 도구 호출은 안전 정책에 의해 제한되었습니다. 연구 목표는 유지됩니다."
_TIMEOUT_TEXT = "영하님, 도구 응답이 지연되어 이번 연구 사이클을 완료하지 못했습니다. 연구 목표는 유지됩니다."


def _classify_multi_tool_failure(results: tuple[AssistantToolResult, ...]) -> str:
    """Classifies why every tool call in a turn failed, from the structured
    failure evidence each result actually carries, and returns a safe,
    truthful explanation - never a specific cause the evidence does not
    support.

    Reuses the existing research-failure classifier (``classify_tool_failure``)
    rather than inventing new causes, and never interpolates raw exception
    messages/paths/tokens into the returned text - only pre-written, vetted
    Korean sentences. Falls back to an honest "cause unclear" message when
    the failed results disagree on cause or carry no specific signal (e.g.
    a generic internal/tool error).
    """
    explanations: set[str] = set()
    for result in results:
        output = result.result.get("output")
        output = output if isinstance(output, dict) else {}
        error_type = str(output.get("error_type", ""))
        message = str(output.get("message", ""))
        normalized = f"{error_type} {message}".casefold()
        if error_type == "ToolSecurityError":
            explanations.add(_POLICY_DENIAL_TEXT)
        elif "timeout" in normalized:
            explanations.add(_TIMEOUT_TEXT)
        else:
            failure = classify_tool_failure(error_type, message)
            if failure.stage in {"market_data", "quality"}:
                explanations.add(failure.user_message)
            else:
                explanations.add(_UNCLEAR_TOOL_FAILURE_TEXT)
    if len(explanations) == 1:
        return explanations.pop()
    return _UNCLEAR_TOOL_FAILURE_TEXT


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
