"""Guarded assistant provider boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from gaon.runtime.intents import Intent


class ProviderError(Exception):
    """Base provider error."""


class ProviderUnavailableError(ProviderError):
    """Provider is disabled or unavailable."""


class ProviderTimeoutError(ProviderError):
    """Provider request timed out."""


class ProviderSafetyError(ProviderError):
    """Provider output violated safety policy."""


@dataclass(frozen=True)
class ProviderCapabilities:
    name: str
    model: str
    supports_network: bool
    deterministic: bool
    max_output_tokens: int


@dataclass(frozen=True)
class ProviderHealth:
    name: str
    available: bool
    latency_ms: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class AssistantToolDefinition:
    name: str
    description: str
    parameters: dict[str, object]


@dataclass(frozen=True)
class AssistantToolCall:
    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class AssistantToolResult:
    call_id: str
    name: str
    result: dict[str, object]


@dataclass(frozen=True)
class AssistantRequest:
    text: str
    intent: Intent
    user_id: str
    conversation_id: str
    received_at: str
    prompt: str | None = None
    references: tuple[str, ...] = ()
    locale: str = "ko-KR"
    tools: tuple[AssistantToolDefinition, ...] = ()
    tool_results: tuple[AssistantToolResult, ...] = ()


@dataclass(frozen=True)
class AssistantProviderResponse:
    text: str
    route: str = "provider"
    references: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    provider_name: str = "unknown"
    model: str | None = None
    latency_ms: int | None = None
    usage: dict[str, int] | None = None
    tool_calls: tuple[AssistantToolCall, ...] = ()


AssistantResponse = AssistantProviderResponse


class AssistantProvider(Protocol):
    @property
    def capabilities(self) -> ProviderCapabilities: ...
    def health(self) -> ProviderHealth: ...
    def respond(self, request: AssistantRequest) -> AssistantProviderResponse: ...


def validate_provider_response(response: AssistantProviderResponse, *, max_chars: int = 2000) -> AssistantProviderResponse:
    if not response.text.strip() and not response.tool_calls:
        raise ProviderSafetyError("provider returned empty response")
    if len(response.text) > max_chars:
        raise ProviderSafetyError("provider response exceeded maximum length")
    unsafe = ("주문을 실행했습니다", "매수했습니다", "매도했습니다", "승인했습니다", "정책을 적용했습니다")
    if any(token in response.text for token in unsafe):
        raise ProviderSafetyError("provider claimed a forbidden action")
    return response
