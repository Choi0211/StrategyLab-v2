"""Assistant provider implementations with no mandatory external SDK."""

from __future__ import annotations

from collections.abc import Callable
import json
import socket
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from gaon.runtime.assistant_provider import (
    AssistantProviderResponse,
    AssistantRequest,
    ProviderCapabilities,
    ProviderHealth,
    ProviderTimeoutError,
    ProviderUnavailableError,
    validate_provider_response,
)
from gaon.runtime.errors import mask_secret
from gaon.runtime.persona import persona_text


class DeterministicAssistantProvider:
    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("deterministic", "rule-based", False, True, 500)

    def health(self) -> ProviderHealth:
        return ProviderHealth("deterministic", True, 0)

    def respond(self, request: AssistantRequest) -> AssistantProviderResponse:
        return AssistantProviderResponse(
            text=persona_text(request.intent),
            route="rule_based",
            references=request.references,
            provider_name="deterministic",
            model="rule-based",
        )


class OpenAICompatibleAssistantProvider:
    """Minimal OpenAI-compatible chat completions provider using urllib."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 10.0,
        max_output_tokens: int = 500,
        enabled: bool = False,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._enabled = enabled
        self._opener = opener

    def __repr__(self) -> str:
        return f"OpenAICompatibleAssistantProvider(api_key={mask_secret(self._api_key)!r}, model={self._model!r}, enabled={self._enabled!r})"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities("openai-compatible", self._model, True, False, self._max_output_tokens)

    def health(self) -> ProviderHealth:
        if not self._enabled:
            return ProviderHealth("openai-compatible", False, error="disabled")
        if not self._api_key:
            return ProviderHealth("openai-compatible", False, error="missing api key")
        return ProviderHealth("openai-compatible", True)

    def respond(self, request: AssistantRequest) -> AssistantProviderResponse:
        if not self._enabled:
            raise ProviderUnavailableError("assistant provider is disabled")
        if not self._api_key:
            raise ProviderUnavailableError("assistant provider api key is missing")
        started = time.perf_counter()
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": "Follow the system instruction section in the user payload."},
                {"role": "user", "content": request.prompt or request.text},
            ],
            "max_tokens": self._max_output_tokens,
        }
        request_obj = Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            response = self._opener(request_obj, timeout=self._timeout_seconds)
            payload = json.loads(response.read(1_000_000).decode("utf-8"))
        except (TimeoutError, socket.timeout) as exc:
            raise ProviderTimeoutError("assistant provider timed out") from exc
        except (HTTPError, URLError, OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderUnavailableError("assistant provider request failed") from exc
        text = _extract_text(payload)
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        return validate_provider_response(
            AssistantProviderResponse(
                text=text,
                route="provider",
                references=request.references,
                provider_name="openai-compatible",
                model=self._model,
                latency_ms=latency_ms,
                usage={key: int(value) for key, value in usage.items() if isinstance(value, int)} if usage else None,
            ),
            max_chars=self._max_output_tokens * 8,
        )


def _extract_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderUnavailableError("assistant provider returned no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ProviderUnavailableError("assistant provider returned malformed content")
    return content
