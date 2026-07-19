import json
import socket
import sqlite3
import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantRequest, AssistantToolCall, AssistantToolResult, ProviderTimeoutError, ProviderUnavailableError
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.intents import Intent
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.migrations import migrate
from gaon.runtime.providers import OpenAICompatibleAssistantProvider


NOW = "2026-07-19T00:00:00Z"


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self, size: int = -1) -> bytes:
        return self._payload


class SequenceOpener:
    def __init__(self, payloads: list[dict | Exception]) -> None:
        self.payloads = payloads
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        payload = self.payloads.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)


class OllamaOpenAICompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repository = SQLiteConversationRepository(self.connection)
        self.audit = SQLiteToolAuditRepository(self.connection)

    def tearDown(self) -> None:
        self.connection.close()

    def test_ollama_content_with_reasoning_ignores_reasoning(self) -> None:
        opener = SequenceOpener([
            {"choices": [{"message": {"role": "assistant", "content": "안녕하세요, 영하님.", "reasoning": "hidden chain"}}], "usage": {"total_tokens": 7}}
        ])
        provider = _provider(opener)

        response = provider.respond(_assistant_request("안녕하세요"))

        self.assertEqual(response.text, "안녕하세요, 영하님.")
        self.assertNotIn("hidden chain", response.text)
        self.assertEqual(response.tool_calls, ())

    def test_ollama_tool_call_with_empty_content_is_valid(self) -> None:
        opener = SequenceOpener([
            {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "",
                            "reasoning": "hidden",
                            "tool_calls": [
                                {
                                    "id": "call-runtime",
                                    "type": "function",
                                    "function": {"name": "runtime_status", "arguments": "{}"},
                                }
                            ],
                        }
                    }
                ]
            }
        ])
        provider = _provider(opener)

        response = provider.respond(_assistant_request("가온 상태 알려줘", tools=SafeToolExecutor(default_tool_registry(self.connection)).assistant_tool_definitions()))

        self.assertEqual(response.text, "")
        self.assertEqual(response.tool_calls, (AssistantToolCall("call-runtime", "runtime_status", {}),))

    def test_native_tool_roundtrip_executes_tools_and_returns_final_content(self) -> None:
        provider = _FakeToolProvider()
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self.repository,
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection), self.audit),
            assistant_provider=provider,
        )

        response = brain.respond(_conversation_request("현재 챔피언 상태와 가온 상태를 같이 알려줘"))

        self.assertEqual(response.route, "provider_tool_call")
        self.assertEqual(response.tool_calls, ("champion_status", "runtime_status"))
        self.assertEqual(response.text, "챔피언과 런타임 상태를 확인했습니다, 영하님.")
        self.assertEqual(len(self.audit.list()), 2)
        self.assertEqual(provider.calls, 2)

    def test_provider_timeout_safe_tool_fallback_returns_response(self) -> None:
        provider = _TimeoutProvider()
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self.repository,
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection), self.audit),
            assistant_provider=provider,
        )

        response = brain.respond(_conversation_request("가온 상태 알려줘"))

        self.assertEqual(response.route, "tool_read_only")
        self.assertEqual(response.tool_calls, ("runtime_status",))
        self.assertTrue(response.text.strip())

    def test_malformed_provider_free_form_returns_visible_fallback(self) -> None:
        provider = _MalformedProvider()
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self.repository,
            assistant_provider=provider,
        )

        response = brain.respond(_conversation_request("안녕하세요 가온"))

        self.assertEqual(response.route, "fallback")
        self.assertIn("영하님", response.text)
        self.assertTrue(response.text.strip())

    def test_openai_timeout_uses_configured_per_request_timeout(self) -> None:
        opener = SequenceOpener([socket.timeout("slow")])
        provider = _provider(opener, timeout=120)

        with self.assertRaises(ProviderTimeoutError):
            provider.respond(_assistant_request("안녕하세요"))

        self.assertEqual(opener.requests[0][1], 120)

    def test_network_initialization_failure_becomes_provider_unavailable(self) -> None:
        opener = SequenceOpener([RuntimeError("network opener is not configured")])
        provider = _provider(opener)

        with self.assertRaises(ProviderUnavailableError):
            provider.respond(_assistant_request("안녕하세요"))

    def test_tool_result_request_uses_openai_tool_messages(self) -> None:
        opener = SequenceOpener([
            {"choices": [{"message": {"role": "assistant", "content": "도구 결과를 반영했습니다.", "reasoning": "hidden"}}]}
        ])
        provider = _provider(opener)

        response = provider.respond(
            _assistant_request(
                "가온 상태 알려줘",
                tools=SafeToolExecutor(default_tool_registry(self.connection)).assistant_tool_definitions(),
                tool_results=(AssistantToolResult("call-runtime", "runtime_status", {"status": "success", "output": {"ready": True}}),),
            )
        )

        body = json.loads(opener.requests[0][0].data.decode("utf-8"))
        self.assertEqual(response.text, "도구 결과를 반영했습니다.")
        self.assertEqual(body["messages"][2]["role"], "assistant")
        self.assertEqual(body["messages"][2]["tool_calls"][0]["id"], "call-runtime")
        self.assertEqual(body["messages"][3]["role"], "tool")
        self.assertEqual(body["messages"][3]["tool_call_id"], "call-runtime")


class _FakeToolProvider:
    def __init__(self) -> None:
        self.calls = 0

    def respond(self, request):
        self.calls += 1
        if not request.tool_results:
            return AssistantProviderResponse(
                text="",
                provider_name="openai-compatible",
                tool_calls=(
                    AssistantToolCall("call-champion", "champion_status", {"slot": "default"}),
                    AssistantToolCall("call-runtime", "runtime_status", {}),
                ),
            )
        self.last_tool_results = request.tool_results
        return AssistantProviderResponse(text="챔피언과 런타임 상태를 확인했습니다, 영하님.", provider_name="openai-compatible")


class _TimeoutProvider:
    def respond(self, request):
        raise ProviderTimeoutError("slow provider")


class _MalformedProvider:
    def respond(self, request):
        return AssistantProviderResponse(text="")


def _provider(opener: SequenceOpener, *, timeout: int = 10) -> OpenAICompatibleAssistantProvider:
    return OpenAICompatibleAssistantProvider(
        api_key="ollama-dummy-key",
        base_url="http://ollama.invalid/v1",
        model="qwen3:8b",
        timeout_seconds=timeout,
        enabled=True,
        opener=opener,
    )


def _assistant_request(text: str, *, tools=(), tool_results=()) -> AssistantRequest:
    return AssistantRequest(text, Intent.UNKNOWN, "user:youngha", "conversation:1", NOW, prompt=text, tools=tuple(tools), tool_results=tuple(tool_results))


def _conversation_request(text: str) -> LLMConversationRequest:
    return LLMConversationRequest("telegram:1", "user:youngha", "telegram", text, NOW, f"message:{text}")


if __name__ == "__main__":
    unittest.main()
