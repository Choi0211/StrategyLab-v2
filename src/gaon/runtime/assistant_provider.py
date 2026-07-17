"""Assistant provider boundary for future LLM integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from gaon.runtime.intents import Intent


@dataclass(frozen=True)
class AssistantRequest:
    text: str
    intent: Intent
    user_id: str
    conversation_id: str
    received_at: str
    locale: str = "ko-KR"


@dataclass(frozen=True)
class AssistantProviderResponse:
    text: str
    route: str = "provider"
    references: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class AssistantProvider(Protocol):
    def respond(self, request: AssistantRequest) -> AssistantProviderResponse: ...
