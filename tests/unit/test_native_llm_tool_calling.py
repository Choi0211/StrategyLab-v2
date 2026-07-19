from __future__ import annotations

import sqlite3
import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantToolCall, ProviderCapabilities, ProviderHealth
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository
from gaon.runtime.llm_tools import SafeToolExecutor, SQLiteToolAuditRepository, default_tool_registry
from gaon.runtime.migrations import migrate


NOW = "2026-07-19T00:00:00Z"


class NativeLLMToolCallingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.repository = SQLiteConversationRepository(self.connection)
        self.audit = SQLiteToolAuditRepository(self.connection)
        self.executor = SafeToolExecutor(default_tool_registry(self.connection), self.audit)

    def tearDown(self) -> None:
        self.connection.close()

    def _brain(self, provider: FakeToolProvider) -> LLMConversationBrain:
        return LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self.repository,
            tool_executor=self.executor,
            assistant_provider=provider,
        )

    def test_provider_single_tool_call_executes_and_synthesizes(self) -> None:
        provider = FakeToolProvider(((AssistantToolCall("call-1", "runtime_status", {}),),), "런타임 상태 확인 완료입니다, 영하님.")
        response = self._brain(provider).respond(_request("런타임 상태 알려줘"))

        self.assertEqual(response.route, "provider_tool_call")
        self.assertEqual(response.tool_calls, ("runtime_status",))
        self.assertIn("런타임 상태", response.text)
        self.assertEqual(self.audit.list()[0].tool_name, "runtime_status")
        self.assertTrue(provider.received_tools)
        self.assertTrue(provider.received_tool_results)

    def test_provider_multi_tool_call_executes_registered_read_only_tools(self) -> None:
        provider = FakeToolProvider(((AssistantToolCall("call-1", "runtime_status", {}), AssistantToolCall("call-2", "v5_pipeline_history", {"limit": 5})),), "두 결과를 함께 확인했습니다.")

        response = self._brain(provider).respond(_request("가온 상태와 v5 이력 알려줘"))

        self.assertEqual(response.tool_calls, ("runtime_status", "v5_pipeline_history"))
        self.assertEqual(set(record.tool_name for record in self.audit.list()), {"runtime_status", "v5_pipeline_history"})

    def test_unknown_tool_is_denied_and_not_counted_as_executed(self) -> None:
        provider = FakeToolProvider(((AssistantToolCall("call-1", "shell_exec", {"command": "whoami"}),),), "거부된 도구 요청입니다.")

        response = self._brain(provider).respond(_request("상태 알려줘"))

        self.assertEqual(response.tool_calls, ())
        self.assertEqual(self.audit.list()[0].status, "denied")

    def test_tool_call_limit_is_bounded(self) -> None:
        calls = tuple(AssistantToolCall(f"call-{index}", "runtime_status", {}) for index in range(5))
        provider = FakeToolProvider((calls,), "상한 내에서만 처리했습니다.")

        response = self._brain(provider).respond(_request("상태 여러 번 알려줘"))

        self.assertEqual(len(response.tool_calls), 3)
        self.assertIn("tool call limit reached", response.warnings)

    def test_deterministic_provider_uses_fallback_router(self) -> None:
        response = LLMConversationBrain(GaonRuntimeConfig(assistant_enabled=True), self.repository, tool_executor=self.executor).respond(_request("가온 상태 알려줘"))

        self.assertEqual(response.route, "tool_read_only")
        self.assertEqual(response.tool_calls, ("runtime_status",))


class FakeToolProvider:
    def __init__(self, scripted_tool_calls: tuple[tuple[AssistantToolCall, ...], ...], final_text: str) -> None:
        self.scripted_tool_calls = list(scripted_tool_calls)
        self.final_text = final_text
        self.received_tools = False
        self.received_tool_results = False

    @property
    def capabilities(self):
        return ProviderCapabilities("fake", "fake-tool", False, False, 500)

    def health(self):
        return ProviderHealth("fake", True)

    def respond(self, request):
        self.received_tools = self.received_tools or bool(request.tools)
        self.received_tool_results = self.received_tool_results or bool(request.tool_results)
        if request.tool_results:
            return AssistantProviderResponse(text=self.final_text, provider_name="fake", route="provider")
        if self.scripted_tool_calls:
            return AssistantProviderResponse(text="", provider_name="fake", route="provider", tool_calls=self.scripted_tool_calls.pop(0))
        return AssistantProviderResponse(text=self.final_text, provider_name="fake", route="provider")


def _request(text: str) -> LLMConversationRequest:
    return LLMConversationRequest("session:native-tools", "user:youngha", "test", text, NOW, f"message:{text}")


if __name__ == "__main__":
    unittest.main()
