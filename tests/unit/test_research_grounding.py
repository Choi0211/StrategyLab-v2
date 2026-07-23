import sqlite3
import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantToolCall
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, default_tool_registry
from gaon.runtime.migrations import migrate
from gaon.runtime.research_grounding import (
    ResearchFact,
    contains_fixture_leakage,
    contains_unverified_fixture_metrics,
    sanitize_research_tool_output,
)


NOW = "2026-07-24T00:00:00Z"
USER_STRATEGY = "사용자 전략: 20일 고가 돌파, 종가 > MA20 > MA60, 거래량 >= 20일 평균, 손절 -5%, 10일 저점 이탈 청산. 이 전략 약점과 리스크 분석해줘"


class ResearchGroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        migrate(self.connection)
        self.brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="deterministic"),
            SQLiteConversationRepository(self.connection),
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection)),
        )

    def tearDown(self) -> None:
        self.connection.close()

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

    def test_user_strategy_context_isolated_from_fixture_candidate_fields(self) -> None:
        response = self.brain.respond(_request(USER_STRATEGY, "context-isolation"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("20일 고가 돌파", response.text)
        self.assertIn("종가 > MA20 > MA60", response.text)
        self.assertIn("거래량 >= 20일 평균", response.text)
        self.assertIn("손절 -5%", response.text)
        self.assertIn("10일 저점 이탈 청산", response.text)
        self.assertFalse(contains_fixture_leakage(response.text))
        self.assertFalse(contains_unverified_fixture_metrics(response.text))

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

    def test_quality_score_missing_data_uses_korean_fallback(self) -> None:
        response = self.brain.respond(_request("이 전략 연구 품질 점수 알려줘", "quality-missing"))

        self.assertEqual(response.tool_calls, ("strategy_quality_score",))
        self.assertIn("실제 백테스트 기반 연구 품질 점수는 저장되어 있지 않습니다", response.text)
        self.assertNotIn("total=", response.text)
        self.assertFalse(contains_fixture_leakage(response.text))

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
        facts = (ResearchFact("user_sharpe", "1.35", "user_input", "message:test"),)
        self.assertFalse(contains_unverified_fixture_metrics("사용자 입력 Sharpe 1.35", facts))

    def test_provider_research_tool_falls_back_when_synthesis_fabricates_metrics(self) -> None:
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            SQLiteConversationRepository(self.connection),
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection)),
            assistant_provider=_FabricatingToolProvider(),
        )

        response = brain.respond(_request("이 전략 약점과 리스크 분석해줘", "provider"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("provider research grounding fallback", response.warnings)
        self.assertFalse(contains_unverified_fixture_metrics(response.text))

    def test_provider_tool_result_sanitizes_fixture_candidate_metadata(self) -> None:
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            SQLiteConversationRepository(self.connection),
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection)),
            assistant_provider=_InspectingToolProvider(),
        )

        response = brain.respond(_request(USER_STRATEGY, "provider-sanitize"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("field_provenance", response.text)
        self.assertFalse(contains_fixture_leakage(response.text))

    def test_sanitized_payload_excludes_fixture_parameters_metrics_and_regime_tags(self) -> None:
        raw = default_tool_registry(self.connection).handler("strategy_critique")({"scenario": "overfit"})
        sanitized = sanitize_research_tool_output("strategy_critique", raw, "20일 고가 돌파 전략")
        as_text = str(sanitized)

        self.assertNotIn("volume_multiplier", as_text)
        self.assertNotIn("max_risk_pct", as_text)
        self.assertNotIn("regime_tags", as_text)
        self.assertNotIn("metrics", as_text)
        self.assertIn("user_strategy_context", sanitized)


class _FabricatingToolProvider:
    def respond(self, request):
        if not request.tool_results:
            return AssistantProviderResponse(
                text="",
                provider_name="openai-compatible",
                tool_calls=(AssistantToolCall("call-critique", "strategy_critique", {"scenario": "overfit"}),),
            )
        return AssistantProviderResponse(text="샤프 1.35, MDD 14%, 거래 수 64회입니다.", provider_name="openai-compatible")


class _InspectingToolProvider:
    def respond(self, request):
        if not request.tool_results:
            return AssistantProviderResponse(
                text="",
                provider_name="openai-compatible",
                tool_calls=(AssistantToolCall("call-critique", "strategy_critique", {"scenario": "overfit"}),),
            )
        payload = request.tool_results[0].result["output"]
        if contains_fixture_leakage(str(payload)):
            return AssistantProviderResponse(text="volume_multiplier=1.5x max_risk_pct=1.0 regime_tags", provider_name="openai-compatible")
        return AssistantProviderResponse(text="field_provenance=user_provided conditions only", provider_name="openai-compatible")


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
