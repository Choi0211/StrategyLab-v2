import json
import os
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from gaon.runtime.assistant_provider import AssistantRequest, AssistantToolDefinition
from gaon.runtime.cli import main as cli_main
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.intents import Intent
from gaon.runtime.provider_registry import build_assistant_provider
from gaon.runtime.providers import OpenAICompatibleAssistantProvider


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self, size: int = -1) -> bytes:
        return self.payload


class FakeOpener:
    def __init__(self, payload: dict | Exception) -> None:
        self.payload = payload
        self.requests = []

    def __call__(self, request, timeout: float):
        self.requests.append((request, timeout, json.loads(request.data.decode("utf-8"))))
        if isinstance(self.payload, Exception):
            raise self.payload
        return FakeHttpResponse(self.payload)


class LLMProviderIntegrationTests(unittest.TestCase):
    def test_openai_compatible_provider_content_response(self) -> None:
        opener = FakeOpener({"choices": [{"message": {"content": "안녕하세요, 영하님."}}], "usage": {"prompt_tokens": 1}})
        provider = OpenAICompatibleAssistantProvider(api_key="synthetic", base_url="https://llm.example/v1", model="gaon-test", enabled=True, opener=opener)

        response = provider.respond(_request("안녕"))

        self.assertEqual(response.text, "안녕하세요, 영하님.")
        self.assertEqual(response.provider_name, "openai-compatible")
        self.assertEqual(opener.requests[0][2]["model"], "gaon-test")
        self.assertNotIn("synthetic", repr(provider))

    def test_openai_compatible_provider_exports_tool_schema_and_parses_tool_call(self) -> None:
        opener = FakeOpener(
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"id": "call-1", "type": "function", "function": {"name": "runtime_status", "arguments": "{}"}}
                            ],
                        }
                    }
                ]
            }
        )
        provider = OpenAICompatibleAssistantProvider(api_key="synthetic", base_url="https://llm.example/v1", model="gaon-test", enabled=True, opener=opener)

        response = provider.respond(
            _request(
                "상태",
                tools=(AssistantToolDefinition("runtime_status", "Read runtime status", {"type": "object", "properties": {}}),),
            )
        )

        self.assertEqual(response.tool_calls[0].name, "runtime_status")
        self.assertEqual(opener.requests[0][2]["tools"][0]["function"]["name"], "runtime_status")

    def test_provider_registry_falls_back_to_deterministic_when_missing_key(self) -> None:
        config = GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible", assistant_base_url="https://llm.example/v1", assistant_model="gaon-test")
        provider = build_assistant_provider(config)

        response = provider.respond(_request("안녕"))

        self.assertEqual(response.provider_name, "deterministic")
        self.assertIn("missing api key", response.warnings[0])

    def test_assistant_provider_status_sanitizes_configuration(self) -> None:
        env = {
            "GAON_ASSISTANT_ENABLED": "true",
            "GAON_ASSISTANT_PROVIDER": "openai-compatible",
            "GAON_ASSISTANT_BASE_URL": "https://secret.example/v1/path",
            "GAON_ASSISTANT_MODEL": "gaon-test",
            "GAON_ASSISTANT_API_KEY": "do-not-print",
        }
        output = StringIO()
        with patch.dict(os.environ, env, clear=False), redirect_stdout(output):
            self.assertEqual(cli_main(["assistant-provider-status"]), 0)

        text = output.getvalue()
        self.assertIn("base_url=https://secret.example", text)
        self.assertNotIn("do-not-print", text)


def _request(text: str, *, tools: tuple[AssistantToolDefinition, ...] = ()) -> AssistantRequest:
    return AssistantRequest(text=text, intent=Intent.UNKNOWN, user_id="user", conversation_id="conversation", received_at="2026-07-19T00:00:00Z", tools=tools)


if __name__ == "__main__":
    unittest.main()
