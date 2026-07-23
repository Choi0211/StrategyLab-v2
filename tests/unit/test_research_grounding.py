import sqlite3
import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantToolCall
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, default_tool_registry
from gaon.runtime.migrations import migrate
from gaon.runtime.research_grounding import contains_unverified_fixture_metrics


NOW = "2026-07-24T00:00:00Z"


class ResearchGroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"),
            self.connection_store_conversations(),
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection)),
        )

    def tearDown(self) -> None:
        self.connection.close()

    def connection_store_conversations(self):
        from gaon.runtime.llm_conversation import SQLiteConversationRepository

        return SQLiteConversationRepository(self.connection)

    def test_routing_prioritizes_research_tools(self) -> None:
        self.assertEqual(route_read_only_tool("이 전략 개선해줘"), "strategy_critique")
        self.assertEqual(route_read_only_tool("이 전략 약점과 리스크 분석해줘"), "strategy_critique")
        self.assertEqual(route_read_only_tool("비슷한 전략 연구했어?"), "research_memory_search")
        self.assertEqual(route_read_only_tool("전략 품질 점수 설명해줘"), "strategy_quality_score")

    def test_strategy_weakness_does_not_invent_fixture_metrics(self) -> None:
        response = self.brain.respond(_request("이 전략 약점과 리스크 분석해줘", "weakness"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("검증된 데이터", response.text)
        self.assertIn("정성 분석", response.text)
        self.assertIn("가설/개선 제안", response.text)
        self.assertFalse(contains_unverified_fixture_metrics(response.text))
        self.assertNotIn("Sharpe", response.text)
        self.assertNotIn("MDD 14", response.text)
        self.assertNotIn("거래 수=64", response.text)

    def test_empty_memory_returns_no_stored_match_without_access_error(self) -> None:
        response = self.brain.respond(_request("비슷한 전략 연구했어?", "memory"))

        self.assertEqual(response.tool_calls, ("research_memory_search",))
        self.assertIn("찾지 못했습니다", response.text)
        self.assertNotIn("접근 권한", response.text)
        self.assertNotIn("access", response.text.casefold())

    def test_empty_memory_does_not_block_improvement(self) -> None:
        response = self.brain.respond(_request("이 전략 개선해줘", "improve"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("가설/개선 제안", response.text)

    def test_quality_score_uses_only_quality_fields(self) -> None:
        response = self.brain.respond(_request("전략 품질 점수 설명해줘", "quality"))

        self.assertEqual(response.tool_calls, ("strategy_quality_score",))
        self.assertIn("total=", response.text)
        self.assertNotIn("Sharpe", response.text)
        self.assertNotIn("MDD", response.text)
        self.assertFalse(contains_unverified_fixture_metrics(response.text))

    def test_backtest_provenance_survives_response(self) -> None:
        response = self.brain.respond(_request("백테스트 결과 보여줘", "backtest"))

        self.assertEqual(response.tool_calls, ("backtest_strategy",))
        self.assertIn("validation_backend=fixture", response.text)
        self.assertIn("fixture_backed=true", response.text)

    def test_tool_returned_metrics_are_allowed(self) -> None:
        response = self.brain.respond(_request("백테스트 결과 보여줘", "allowed"))

        self.assertIn("trade_count=", response.text)
        self.assertIn("mdd=", response.text)

    def test_user_provided_numeric_values_are_not_marked_fabricated_when_listed_as_facts(self) -> None:
        from gaon.runtime.research_grounding import ResearchFact

        facts = (ResearchFact("user_sharpe", "1.35", "user_input", "message:test"),)
        self.assertFalse(contains_unverified_fixture_metrics("사용자 입력 Sharpe 1.35", facts))

    def test_provider_research_tool_falls_back_when_synthesis_fabricates_metrics(self) -> None:
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            self.connection_store_conversations(),
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection)),
            assistant_provider=_FabricatingToolProvider(),
        )

        response = brain.respond(_request("이 전략 약점과 리스크 분석해줘", "provider"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("provider research grounding fallback", response.warnings)
        self.assertFalse(contains_unverified_fixture_metrics(response.text))


class _FabricatingToolProvider:
    def respond(self, request):
        if not request.tool_results:
            return AssistantProviderResponse(
                text="",
                provider_name="openai-compatible",
                tool_calls=(AssistantToolCall("call-critique", "strategy_critique", {"scenario": "overfit"}),),
            )
        return AssistantProviderResponse(text="샤프 1.35, MDD 14%, 거래 수 64회입니다.", provider_name="openai-compatible")


def _request(text: str, suffix: str) -> LLMConversationRequest:
    return LLMConversationRequest(
        session_id=f"research-grounding:{suffix}",
        user_ref="user:youngha",
        source="telegram",
        text=text,
        received_at=NOW,
        message_id=f"message:{suffix}",
    )


if __name__ == "__main__":
    unittest.main()
