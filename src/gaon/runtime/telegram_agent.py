"""Telegram-facing conversational agent for Gaon's LLM brain."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import sqlite3

from gaon.runtime.assistant_provider import AssistantProvider
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.conversation import ConversationInput, ConversationResponse
from gaon.runtime.conversation_context import ConversationContextOrchestrator
from gaon.runtime.event_store import SQLiteEventStore
from gaon.runtime.llm_conversation import (
    LLMConversationBrain,
    LLMConversationRequest,
    LLMConversationResponse,
    SQLiteConversationRepository,
    SQLiteConversationToolResultRepository,
    _extract_krx_symbols,
)
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.metrics import MetricsCollector
from gaon.runtime.research_failures import classify_exception, warning_for_failure
from gaon.runtime.responses import ResponseAction
from gaon.runtime.intents import Intent, parse_intent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TelegramConversationLink:
    chat_id: str
    session_id: str
    created_at: str
    updated_at: str


class SQLiteTelegramConversationLinkRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def resolve(self, chat_id: str, *, now: str) -> TelegramConversationLink:
        row = self._connection.execute(
            "SELECT chat_id, session_id, created_at, updated_at FROM telegram_conversation_links WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        if row is not None:
            link = TelegramConversationLink(str(row[0]), str(row[1]), str(row[2]), now)
            with self._connection:
                self._connection.execute("UPDATE telegram_conversation_links SET updated_at = ? WHERE chat_id = ?", (now, chat_id))
            return link
        link = TelegramConversationLink(chat_id, f"telegram:{chat_id}", now, now)
        with self._connection:
            self._connection.execute(
                "INSERT INTO telegram_conversation_links(chat_id, session_id, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (link.chat_id, link.session_id, link.created_at, link.updated_at),
            )
        return link


class TelegramConversationAgent:
    """Adapter that lets TelegramRuntime reuse the LLM conversation brain."""

    def __init__(
        self,
        config: GaonRuntimeConfig,
        connection: sqlite3.Connection,
        *,
        metrics: MetricsCollector | None = None,
        assistant_provider: AssistantProvider | None = None,
        tool_executor: SafeToolExecutor | None = None,
    ) -> None:
        repository = SQLiteConversationRepository(connection)
        context = ConversationContextOrchestrator(connection, repository)
        self._brain = LLMConversationBrain(
            config,
            repository,
            context_orchestrator=context,
            tool_executor=tool_executor or SafeToolExecutor(default_tool_registry(connection), SQLiteToolAuditRepository(connection)),
            tool_result_repository=SQLiteConversationToolResultRepository(connection),
            assistant_provider=assistant_provider,
            event_store=SQLiteEventStore(connection),
            metrics=metrics,
        )
        self._links = SQLiteTelegramConversationLinkRepository(connection)
        self._metrics = metrics or MetricsCollector()

    def handle(self, message: ConversationInput) -> ConversationResponse:
        session_id = f"telegram:{message.conversation_id}"
        try:
            response = self._brain.respond(
                LLMConversationRequest(
                    session_id=session_id,
                    user_ref=f"telegram-user:{message.user_id}",
                    source="telegram",
                    text=message.text,
                    received_at=message.received_at,
                    message_id=f"telegram:{message.conversation_id}:{message.message_id}",
                )
            )
        except Exception as exc:  # noqa: BLE001 - Telegram must return a visible fallback.
            failure = classify_exception(exc)
            self._metrics.increment("gaon_telegram_conversation_failures_total", error_type=failure.error_type, failure_stage=failure.stage)
            logger.exception(
                "telegram conversation failed",
                extra={"error_type": failure.error_type, "failure_stage": failure.stage, "route": "telegram_conversation"},
            )
            return ConversationResponse(
                response_id=f"telegram-fallback:{message.message_id}",
                conversation_id=message.conversation_id,
                text=failure.user_message,
                intent=parse_intent(message.text) if message.text else Intent.UNKNOWN,
                references=(),
                warnings=(warning_for_failure(failure),),
                actions=(ResponseAction("fallback"),),
                approval_required=False,
                generated_at=message.received_at,
                route=f"failure_{failure.stage}",
                provider_metadata={"provider": "deterministic", "path": "telegram_conversation_failure", "failure_stage": failure.stage, "error_type": failure.error_type},
            )
        self._links.resolve(message.conversation_id, now=message.received_at)
        symbol_count = len(_extract_krx_symbols(message.text)) if "multi_symbol_research" in response.tool_calls else 0
        logger.info(
            "telegram route selected",
            extra={
                "message_id": message.message_id,
                "intent": response.intent.value,
                "route": response.route,
                "tool": response.tool_calls[0] if response.tool_calls else None,
                "tool_count": len(response.tool_calls),
                "symbol_count": symbol_count,
            },
        )
        return _to_conversation_response(response, message)


def _to_conversation_response(response: LLMConversationResponse, message: ConversationInput) -> ConversationResponse:
    return ConversationResponse(
        response_id=response.response_id,
        conversation_id=message.conversation_id,
        text=response.text,
        intent=response.intent,
        references=response.references,
        warnings=response.warnings,
        actions=(ResponseAction(response.intent.value),),
        approval_required=response.approval_required,
        generated_at=response.generated_at,
        route=response.route,
        provider_metadata={"provider": response.provider, "path": "llm_conversation_brain"},
    )
