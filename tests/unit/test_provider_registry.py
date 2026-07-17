import json
import unittest

from gaon.runtime.assistant_provider import AssistantRequest
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.errors import ConfigurationError
from gaon.runtime.intents import Intent
from gaon.runtime.provider_registry import AssistantProviderRegistry, ProviderRegistration, RoutingAssistantProvider, build_assistant_provider, default_provider_registry
from gaon.runtime.providers import DeterministicAssistantProvider


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self, _: int) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


class ProviderRegistryTest(unittest.TestCase):
    def request(self) -> AssistantRequest:
        return AssistantRequest("안녕", Intent.GREETING, "user", "conv", "2026-07-18T00:00:00Z")

    def test_deterministic_selection(self) -> None:
        provider = build_assistant_provider(GaonRuntimeConfig())

        response = provider.respond(self.request())

        self.assertEqual(response.provider_name, "deterministic")
        self.assertEqual(response.route, "rule_based")

    def test_openai_compatible_selection_with_fake_opener(self) -> None:
        def opener(*_: object, **__: object) -> FakeResponse:
            return FakeResponse({"choices": [{"message": {"content": "영하님, fake provider입니다."}}], "usage": {"total_tokens": 3}})

        config = GaonRuntimeConfig(
            assistant_provider="openai-compatible",
            assistant_enabled=True,
            assistant_api_key="secret-key",
            assistant_base_url="https://example.invalid/v1",
            assistant_model="fake-model",
        )
        provider = build_assistant_provider(config, opener=opener)

        response = provider.respond(self.request())

        self.assertEqual(response.provider_name, "openai-compatible")
        self.assertEqual(response.model, "fake-model")
        self.assertIn("fake provider", response.text)

    def test_unknown_provider_and_duplicate_registration_fail_fast(self) -> None:
        registry = AssistantProviderRegistry()
        registry.register(ProviderRegistration("deterministic", lambda _: DeterministicAssistantProvider(), False, True))

        with self.assertRaises(ConfigurationError):
            registry.create("unknown", GaonRuntimeConfig())
        with self.assertRaises(ConfigurationError):
            registry.register(ProviderRegistration("deterministic", lambda _: DeterministicAssistantProvider(), False, True))

    def test_unhealthy_disabled_provider_falls_back(self) -> None:
        config = GaonRuntimeConfig(assistant_provider="openai-compatible", assistant_enabled=False)
        provider = build_assistant_provider(config)

        response = provider.respond(self.request())

        self.assertEqual(response.route, "fallback")
        self.assertEqual(response.provider_name, "deterministic")
        self.assertTrue(response.warnings)

    def test_timeout_provider_falls_back(self) -> None:
        def opener(*_: object, **__: object) -> object:
            raise TimeoutError("synthetic timeout")

        config = GaonRuntimeConfig(
            assistant_provider="openai-compatible",
            assistant_enabled=True,
            assistant_api_key="secret-key",
            assistant_base_url="https://example.invalid/v1",
            assistant_model="fake-model",
        )
        provider = build_assistant_provider(config, opener=opener)

        response = provider.respond(self.request())

        self.assertEqual(response.route, "fallback")
        self.assertIn("provider error", response.warnings[0])

    def test_no_secret_leakage_in_repr_or_audit_event(self) -> None:
        config = GaonRuntimeConfig(assistant_provider="openai-compatible", assistant_enabled=True, assistant_api_key="secret-key")
        registry = default_provider_registry()
        result = registry.route(config)
        event = registry.audit_event(result)
        provider = registry.create("openai-compatible", config)

        self.assertNotIn("secret-key", repr(provider))
        self.assertNotIn("secret-key", str(event))


if __name__ == "__main__":
    unittest.main()
