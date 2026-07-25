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
    contains_wrapper_tags,
    normalize_final_response,
    sanitize_research_tool_output,
)


NOW = "2026-07-24T00:00:00Z"
USER_STRATEGY = "\uc0ac\uc6a9\uc790 \uc804\ub7b5: 20\uc77c \uace0\uac00 \ub3cc\ud30c, \uc885\uac00 > MA20 > MA60, \uac70\ub798\ub7c9 >= 20\uc77c \ud3c9\uade0, \uc190\uc808 -5%, 10\uc77c \uc800\uc810 \uc774\ud0c8 \uccad\uc0b0. \uc774 \uc804\ub7b5 \uc57d\uc810\uacfc \ub9ac\uc2a4\ud06c \ubd84\uc11d\ud574\uc918"


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
        self.assertEqual(route_read_only_tool("\uc774 \uc804\ub7b5 \uac1c\uc120\ud574\uc918"), "strategy_critique")
        self.assertEqual(route_read_only_tool("\uc774 \uc804\ub7b5 \uc57d\uc810\uacfc \ub9ac\uc2a4\ud06c \ubd84\uc11d\ud574\uc918"), "strategy_critique")
        self.assertEqual(route_read_only_tool("\ube44\uc2b7\ud55c \uc804\ub7b5 \uc5f0\uad6c\ud588\uc5b4?"), "research_memory_search")
        self.assertEqual(route_read_only_tool("\uc804\ub7b5 \ud488\uc9c8 \uc810\uc218 \uc124\uba85\ud574\uc918"), "strategy_quality_score")

    def test_strategy_weakness_does_not_invent_fixture_metrics(self) -> None:
        response = self.brain.respond(_request("\uc774 \uc804\ub7b5 \uc57d\uc810\uacfc \ub9ac\uc2a4\ud06c \ubd84\uc11d\ud574\uc918", "weakness"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("\uac80\uc99d\ub41c \ub370\uc774\ud130", response.text)
        self.assertIn("\uc815\uc131 \ubd84\uc11d", response.text)
        self.assertIn("\uac00\uc124/\uac1c\uc120 \uc81c\uc548", response.text)
        self.assertFalse(contains_unverified_fixture_metrics(response.text))
        self.assertNotIn("Sharpe", response.text)
        self.assertNotIn("MDD 14", response.text)
        self.assertNotIn("\uac70\ub798 \uc218=64", response.text)

    def test_user_strategy_context_isolated_from_fixture_candidate_fields(self) -> None:
        response = self.brain.respond(_request(USER_STRATEGY, "context-isolation"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("20\uc77c \uace0\uac00 \ub3cc\ud30c", response.text)
        self.assertIn("\uc885\uac00 > MA20 > MA60", response.text)
        self.assertIn("\uac70\ub798\ub7c9 >= 20\uc77c \ud3c9\uade0", response.text)
        self.assertIn("\uc190\uc808 -5%", response.text)
        self.assertIn("10\uc77c \uc800\uc810 \uc774\ud0c8 \uccad\uc0b0", response.text)
        self.assertFalse(contains_fixture_leakage(response.text))
        self.assertFalse(contains_unverified_fixture_metrics(response.text))

    def test_empty_memory_returns_no_stored_match_without_access_error(self) -> None:
        response = self.brain.respond(_request("\ube44\uc2b7\ud55c \uc804\ub7b5 \uc5f0\uad6c\ud588\uc5b4?", "memory"))

        self.assertEqual(response.tool_calls, ("research_memory_search",))
        self.assertIn("\ucc3e\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4", response.text)
        self.assertNotIn("\uc811\uadfc \uad8c\ud55c", response.text)
        self.assertNotIn("access", response.text.casefold())

    def test_empty_memory_does_not_block_improvement(self) -> None:
        response = self.brain.respond(_request("\uc774 \uc804\ub7b5 \uac1c\uc120\ud574\uc918", "improve"))

        self.assertEqual(response.tool_calls, ("strategy_critique",))
        self.assertIn("\uac00\uc124/\uac1c\uc120 \uc81c\uc548", response.text)

    def test_quality_score_missing_data_uses_korean_fallback(self) -> None:
        response = self.brain.respond(_request("\uc774 \uc804\ub7b5\uc758 \uc5f0\uad6c \ud488\uc9c8 \uc810\uc218\ub97c \ubcf4\uc5ec\uc918.", "quality-missing"))

        self.assertEqual(response.tool_calls, ("strategy_quality_score",))
        self.assertIn("\uc2e4\uc81c \ubc31\ud14c\uc2a4\ud2b8\ub97c \uae30\ubc18\uc73c\ub85c \uacc4\uc0b0\ub41c \uc5f0\uad6c \ud488\uc9c8 \uc810\uc218\ub294 \uc800\uc7a5\ub418\uc5b4 \uc788\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4", response.text)
        self.assertNotIn("total=", response.text)
        self.assertFalse(contains_fixture_leakage(response.text))

    def test_korean_critic_messages_are_translated(self) -> None:
        response = self.brain.respond(_request("\uc774 \uc804\ub7b5\uc758 \uc57d\uc810\uc744 \ubd84\uc11d\ud574\uc918.", "korean-critic"))

        self.assertIn("\ud45c\ubcf8 \ub0b4 \uc131\uacfc\uac00 \ud45c\ubcf8 \uc678 \uc131\uacfc\ubcf4\ub2e4 \ud06c\uac8c \ub192\uc2b5\ub2c8\ub2e4", response.text)
        self.assertIn("\ud30c\ub77c\ubbf8\ud130 \ubbfc\uac10\ub3c4\uac00 \ub192\uc2b5\ub2c8\ub2e4", response.text)
        self.assertNotIn("In-sample performance", response.text)
        self.assertNotIn("Parameter sensitivity", response.text)
        self.assertNotIn("Feature complexity", response.text)

    def test_backtest_provenance_survives_response(self) -> None:
        response = self.brain.respond(_request("\ubc31\ud14c\uc2a4\ud2b8 \uacb0\uacfc \ubcf4\uc5ec\uc918", "backtest"))

        self.assertEqual(response.tool_calls, ("backtest_strategy",))
        self.assertIn("validation_backend=fixture", response.text)
        self.assertIn("fixture_backed=true", response.text)

    def test_tool_returned_metrics_are_allowed(self) -> None:
        response = self.brain.respond(_request("\ubc31\ud14c\uc2a4\ud2b8 \uacb0\uacfc \ubcf4\uc5ec\uc918", "allowed"))

        self.assertIn("trade_count=", response.text)
        self.assertIn("mdd=", response.text)

    def test_user_provided_numeric_values_are_not_marked_fabricated_when_listed_as_facts(self) -> None:
        facts = (ResearchFact("user_sharpe", "1.35", "user_input", "message:test"),)
        self.assertFalse(contains_unverified_fixture_metrics("\uc0ac\uc6a9\uc790 \uc785\ub825 Sharpe 1.35", facts))

    def test_provider_research_tool_falls_back_when_synthesis_fabricates_metrics(self) -> None:
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            SQLiteConversationRepository(self.connection),
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection)),
            assistant_provider=_FabricatingToolProvider(),
        )

        response = brain.respond(_request("\uc774 \uc804\ub7b5 \uc57d\uc810\uacfc \ub9ac\uc2a4\ud06c \ubd84\uc11d\ud574\uc918", "provider"))

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

    def test_provider_english_research_answer_uses_korean_grounded_fallback(self) -> None:
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            SQLiteConversationRepository(self.connection),
            tool_executor=SafeToolExecutor(default_tool_registry(self.connection)),
            assistant_provider=_EnglishToolProvider(),
        )

        response = brain.respond(_request("\uc774 \uc804\ub7b5\uc758 \uc57d\uc810\uc744 \ubd84\uc11d\ud574\uc918.", "english-provider"))

        self.assertIn("provider research grounding fallback", response.warnings)
        self.assertIn("\uc815\uc131 \ubd84\uc11d", response.text)
        self.assertNotIn("This strategy has", response.text)

    def test_output_response_tags_are_removed(self) -> None:
        text = normalize_final_response("<output>\uc548\ub155\ud558\uc138\uc694, \uc601\ud558\ub2d8.</output>", "\uc548\ub155")

        self.assertEqual(text, "\uc548\ub155\ud558\uc138\uc694, \uc601\ud558\ub2d8.")
        self.assertFalse(contains_wrapper_tags(text))

    def test_english_user_may_receive_english_response(self) -> None:
        text = normalize_final_response("This is an English response for an English user.", "Show me the strategy status.")

        self.assertEqual(text, "This is an English response for an English user.")

    def test_sanitized_payload_excludes_fixture_parameters_metrics_and_regime_tags(self) -> None:
        raw = default_tool_registry(self.connection).handler("strategy_critique")({"scenario": "overfit"})
        sanitized = sanitize_research_tool_output("strategy_critique", raw, "20\uc77c \uace0\uac00 \ub3cc\ud30c \uc804\ub7b5")
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
        return AssistantProviderResponse(text="\uc0e4\ud504 1.35, MDD 14%, \uac70\ub798 \uc218 64\ud68c\uc785\ub2c8\ub2e4.", provider_name="openai-compatible")


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


class _EnglishToolProvider:
    def respond(self, request):
        if not request.tool_results:
            return AssistantProviderResponse(
                text="",
                provider_name="openai-compatible",
                tool_calls=(AssistantToolCall("call-critique", "strategy_critique", {"scenario": "overfit"}),),
            )
        return AssistantProviderResponse(text="<output>This strategy has weakness and requires validation.</output>", provider_name="openai-compatible")


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
