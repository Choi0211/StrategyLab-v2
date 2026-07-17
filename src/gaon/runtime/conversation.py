"""Deterministic conversation runtime with guarded provider fallback."""

from __future__ import annotations

from dataclasses import dataclass

from gaon.runtime.assistant_provider import AssistantProvider, AssistantRequest, ProviderError, validate_provider_response
from gaon.runtime.events import EventType, RuntimeEvent
from gaon.runtime.event_bus import InMemoryEventBus
from gaon.runtime.intents import Intent, parse_intent
from gaon.runtime.memory_context import summarize_context
from gaon.runtime.persona import RULE_BASED_ROUTE, persona_text, safety_warning
from gaon.runtime.prompt_builder import PromptBuildInput, build_assistant_prompt
from gaon.runtime.responses import ResponseAction


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
    route: str = RULE_BASED_ROUTE
    provider_metadata: dict[str, str] | None = None


class ConversationRuntime:
    """Runtime that can use a provider but always falls back safely."""

    def __init__(self, event_bus: InMemoryEventBus | None = None, assistant_provider: AssistantProvider | None = None, context_builder=None) -> None:
        self._event_bus = event_bus or InMemoryEventBus()
        self._assistant_provider = assistant_provider
        self._context_builder = context_builder

    def handle(self, message: ConversationInput) -> ConversationResponse:
        intent = parse_intent(message.text)
        warnings: tuple[str, ...] = ()
        approval_required = _requires_approval_boundary(message.text)
        context_result = None
        references: tuple[str, ...] = ()
        if self._context_builder is not None and self._context_builder.should_build(intent):
            context_result = self._context_builder.build(message, intent)
            references = tuple(reference.reference_id for reference in context_result.context.references)
            warnings = (*warnings, *context_result.context.warnings)

        prompt = build_assistant_prompt(PromptBuildInput(message.text, intent, context_result.context if context_result else None))
        text, route, provider_metadata, provider_warnings, response_references = self._respond(message, intent, prompt, references, approval_required)
        references = response_references
        warnings = (*warnings, *provider_warnings)
        if context_result is not None and route.startswith(RULE_BASED_ROUTE):
            text = f"{text}\n\n{summarize_context(context_result.context)}"
        if context_result is not None:
            route = f"{route}+{context_result.route_suffix}"
        if intent is Intent.UNKNOWN:
            warnings = (*warnings, "unknown intent")
        warning = safety_warning(message.text)
        if warning is not None:
            approval_required = True
            warnings = (*warnings, warning)
        response = ConversationResponse(
            response_id=f"response:{message.message_id}",
            conversation_id=message.conversation_id,
            text=text,
            intent=intent,
            references=references,
            warnings=_dedupe(warnings),
            actions=(ResponseAction(intent.value),),
            approval_required=approval_required,
            generated_at=message.received_at,
            route=route,
            provider_metadata=provider_metadata,
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
                payload={"intent": intent.value, "approval_required": approval_required, "route": route},
            )
        )
        return response

    def _respond(self, message: ConversationInput, intent: Intent, prompt: str, references: tuple[str, ...], approval_required: bool) -> tuple[str, str, dict[str, str] | None, tuple[str, ...], tuple[str, ...]]:
        if self._assistant_provider is None or approval_required:
            warnings = ("provider bypassed for safety boundary",) if approval_required and self._assistant_provider is not None else ()
            return persona_text(intent), RULE_BASED_ROUTE, None, warnings, references
        try:
            provider_response = validate_provider_response(
                self._assistant_provider.respond(
                    AssistantRequest(
                        text=message.text,
                        intent=intent,
                        user_id=message.user_id,
                        conversation_id=message.conversation_id,
                        received_at=message.received_at,
                        prompt=prompt,
                        references=references,
                    )
                )
            )
            metadata = {
                "provider": provider_response.provider_name,
                "model": provider_response.model or "",
                "latency_ms": str(provider_response.latency_ms) if provider_response.latency_ms is not None else "",
            }
            return provider_response.text, provider_response.route, metadata, provider_response.warnings, provider_response.references
        except ProviderError as exc:
            return persona_text(intent), "fallback", None, (f"provider fallback: {exc}",), references


def _requires_approval_boundary(text: str) -> bool:
    normalized = text.casefold()
    return any(token in normalized for token in ("approve", "승인", "매수", "매도", "주문", "실거래", "자동 승인", "buy", "sell", "order"))


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))
