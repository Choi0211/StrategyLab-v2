"""Deterministic conversation runtime."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.runtime.events import EventType, RuntimeEvent
from gaon.runtime.event_bus import InMemoryEventBus
from gaon.runtime.intents import Intent, parse_intent
from gaon.runtime.responses import ResponseAction, fallback_text, help_text, intent_text


@dataclass(frozen=True)
class ConversationInput:
    source: str
    user_id: str
    conversation_id: str
    message_id: str
    text: str
    received_at: str
    reply_to: str | None = None
    metadata: dict[str, str] | None = None


@dataclass(frozen=True)
class ConversationResponse:
    response_id: str
    conversation_id: str
    text: str
    intent: Intent
    references: tuple[str, ...]
    warnings: tuple[str, ...]
    actions: tuple[ResponseAction, ...]
    approval_required: bool
    generated_at: str


class ConversationRuntime:
    """Rule-based runtime that never performs destructive actions."""

    def __init__(self, event_bus: InMemoryEventBus | None = None) -> None:
        self._event_bus = event_bus or InMemoryEventBus()

    def handle(self, message: ConversationInput) -> ConversationResponse:
        intent = parse_intent(message.text)
        warnings: tuple[str, ...] = ()
        approval_required = False
        if intent is Intent.HELP:
            text = help_text()
        elif intent is Intent.UNKNOWN:
            text = fallback_text()
            warnings = ("unknown intent",)
        else:
            text = intent_text(intent)
        if "approve" in message.text.casefold() or "승인" in message.text:
            approval_required = True
            warnings = (*warnings, "approval commands require a separate approval runtime")
        response = ConversationResponse(
            response_id=f"response:{message.message_id}",
            conversation_id=message.conversation_id,
            text=text,
            intent=intent,
            references=(),
            warnings=warnings,
            actions=(ResponseAction(intent.value),),
            approval_required=approval_required,
            generated_at=message.received_at,
        )
        self._event_bus.publish(
            RuntimeEvent(
                event_id=f"event:conversation:{message.message_id}",
                event_type=EventType.TELEGRAM_RESPONSE_PREPARED,
                occurred_at=message.received_at,
                actor="gaon-runtime",
                correlation_id=message.conversation_id,
                causation_id=message.message_id,
                scope="runtime",
                project="StrategyLab",
                strategy="N/A",
                market="N/A",
                payload={"intent": intent.value, "approval_required": approval_required},
            )
        )
        return response
