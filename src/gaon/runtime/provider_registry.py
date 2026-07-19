"""Assistant provider registry and routing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from gaon.runtime.assistant_provider import (
    AssistantProvider,
    AssistantProviderResponse,
    AssistantRequest,
    ProviderCapabilities,
    ProviderError,
    ProviderHealth,
)
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import ConfigurationError, redact_mapping
from gaon.runtime.providers import DeterministicAssistantProvider, OpenAICompatibleAssistantProvider


class AssistantProviderFactory(Protocol):
    def __call__(self, config: GaonRuntimeConfig) -> AssistantProvider: ...


@dataclass(frozen=True)
class ProviderRegistration:
    name: str
    factory: AssistantProviderFactory
    supports_network: bool
    deterministic: bool


@dataclass(frozen=True)
class ProviderRouteResult:
    provider: AssistantProvider
    selected_name: str
    fallback_used: bool
    fallback_reason: str | None
    health: ProviderHealth


class AssistantProviderRegistry:
    def __init__(self, fallback: AssistantProvider | None = None) -> None:
        self._registrations: dict[str, ProviderRegistration] = {}
        self._fallback = fallback or DeterministicAssistantProvider()

    def register(self, registration: ProviderRegistration) -> None:
        if not registration.name or registration.name.strip() != registration.name:
            raise ConfigurationError("provider name must be stable and trimmed")
        if registration.name in self._registrations:
            raise ConfigurationError(f"duplicate provider registration: {registration.name}")
        self._registrations[registration.name] = registration

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._registrations))

    def create(self, name: str, config: GaonRuntimeConfig) -> AssistantProvider:
        try:
            registration = self._registrations[name]
        except KeyError as exc:
            raise ConfigurationError(f"unknown assistant provider: {name}") from exc
        return registration.factory(config)

    def route(self, config: GaonRuntimeConfig) -> ProviderRouteResult:
        provider = self.create(config.assistant_provider, config)
        health = provider.health()
        if health.available:
            return ProviderRouteResult(provider, config.assistant_provider, False, None, health)
        fallback_health = self._fallback.health()
        return ProviderRouteResult(self._fallback, "deterministic", True, f"provider unhealthy: {health.error or health.name}", fallback_health)

    def audit_event(self, result: ProviderRouteResult) -> dict[str, object]:
        return redact_mapping(
            {
                "provider": result.selected_name,
                "fallback_used": result.fallback_used,
                "fallback_reason": result.fallback_reason or "",
                "health": result.health.name,
            }
        )


class RoutingAssistantProvider:
    def __init__(self, registry: AssistantProviderRegistry, config: GaonRuntimeConfig) -> None:
        self._registry = registry
        self._config = config
        self.last_fallback_reason: str | None = None

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._registry.route(self._config).provider.capabilities

    def health(self) -> ProviderHealth:
        return self._registry.route(self._config).health

    def respond(self, request: AssistantRequest) -> AssistantProviderResponse:
        result = self._registry.route(self._config)
        self.last_fallback_reason = result.fallback_reason
        try:
            response = result.provider.respond(request)
        except ProviderError as exc:
            self.last_fallback_reason = f"provider error: {exc.__class__.__name__}"
            response = self._registry.route(_deterministic_config(self._config)).provider.respond(request)
            return AssistantProviderResponse(
                text=response.text,
                route="fallback",
                references=response.references,
                warnings=(*response.warnings, self.last_fallback_reason),
                provider_name="deterministic",
                model=response.model,
            )
        if result.fallback_used:
            return AssistantProviderResponse(
                text=response.text,
                route="fallback",
                references=response.references,
                warnings=(*response.warnings, result.fallback_reason or "provider fallback"),
                provider_name=response.provider_name,
                model=response.model,
            )
        return response


def default_provider_registry(opener: Callable[..., object] | None = None) -> AssistantProviderRegistry:
    registry = AssistantProviderRegistry()
    registry.register(ProviderRegistration("deterministic", lambda _: DeterministicAssistantProvider(), supports_network=False, deterministic=True))
    registry.register(
        ProviderRegistration(
            "openai-compatible",
            lambda config: OpenAICompatibleAssistantProvider(
                api_key=config.assistant_api_key or "",
                base_url=config.assistant_base_url or "https://api.openai.com/v1",
                model=config.assistant_model or "unset",
                timeout_seconds=config.assistant_timeout_seconds,
                max_output_tokens=config.assistant_max_output_tokens,
                enabled=config.assistant_enabled,
                **({"opener": opener} if opener is not None else {}),
            ),
            supports_network=True,
            deterministic=False,
        )
    )
    return registry


def build_assistant_provider(config: GaonRuntimeConfig, *, opener: Callable[..., object] | None = None) -> AssistantProvider:
    registry = default_provider_registry(opener=opener)
    if config.assistant_provider == "deterministic":
        return registry.create("deterministic", config)
    return RoutingAssistantProvider(registry, config)


def _deterministic_config(config: GaonRuntimeConfig) -> GaonRuntimeConfig:
    return GaonRuntimeConfig(
        mode=config.mode,
        telegram_enabled=config.telegram_enabled,
        telegram_bot_token=config.telegram_bot_token,
        telegram_allowed_chat_ids=config.telegram_allowed_chat_ids,
        notion_enabled=config.notion_enabled,
        notion_token=config.notion_token,
        timezone=config.timezone,
        dry_run=config.dry_run,
        approval_signing_secret=config.approval_signing_secret,
        assistant_provider="deterministic",
    )
