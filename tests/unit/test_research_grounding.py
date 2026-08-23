import sqlite3
import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse, AssistantToolCall
from gaon.runtime.config import GaonRuntimeConfig
from gaon.runtime.llm_conversation import LLMConversationBrain, LLMConversationRequest, SQLiteConversationRepository
from gaon.runtime.llm_tool_routing import route_read_only_tool
from gaon.runtime.llm_tools import SafeToolExecutor, ToolResult, default_tool_registry
from gaon.runtime.migrations import migrate
from gaon.runtime.research_grounding import (
    ResearchFact,
    contains_ungrounded_real_research_claim,
    contains_fixture_leakage,
    contains_unverified_fixture_metrics,
    contains_wrapper_tags,
    format_grounded_tool_response,
    normalize_final_response,
    sanitize_research_tool_output,
    strict_real_research_grounding_violations,
)


NOW = "2026-07-24T00:00:00Z"
USER_STRATEGY = "\uc0ac\uc6a9\uc790 \uc804\ub7b5: 20\uc77c \uace0\uac00 \ub3cc\ud30c, \uc885\uac00 > MA20 > MA60, \uac70\ub798\ub7c9 >= 20\uc77c \ud3c9\uade0, \uc190\uc808 -5%, 10\uc77c \uc800\uc810 \uc774\ud0c8 \uccad\uc0b0. \uc774 \uc804\ub7b5 \uc57d\uc810\uacfc \ub9ac\uc2a4\ud06c \ubd84\uc11d\ud574\uc918"


class ResearchGroundingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
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

    def test_strict_real_research_formatter_uses_backtest_result_only(self) -> None:
        payload = _strict_real_payload()
        text = format_grounded_tool_response("krx_real_research", payload, USER_STRATEGY)

        self.assertIsNotNone(text)
        assert text is not None
        self.assertEqual(strict_real_research_grounding_violations(text, payload), ())
        self.assertIn("trade_count=3", text)
        self.assertIn("wins=2", text)
        self.assertIn("losses=1", text)
        self.assertIn("provider=real:yahoo-chart", text)
        self.assertIn("fixture_backed=false", text)
        self.assertIn("2025-09-19", text)
        self.assertIn("TESTED", text)
        self.assertIn("HYPOTHESIS", text)
        self.assertIn("protective_stop_pct=-5.0 provenance=user_provided", text)
        self.assertIn("commission=0.00015 provenance=default", text)
        self.assertNotIn("trade_count=4", text)
        self.assertNotIn("RSI 20", text)
        self.assertNotIn("volume 1.5", text)

    def test_provider_real_research_tool_result_falls_back_to_structured_report(self) -> None:
        payload = _strict_real_payload()
        brain = LLMConversationBrain(
            GaonRuntimeConfig(assistant_enabled=True, assistant_provider="openai-compatible"),
            SQLiteConversationRepository(self.connection),
            tool_executor=_StrictExecutor(payload),
            assistant_provider=_StrictFabricatingProvider(),
        )

        response = brain.respond(_request("provider tool-result roundtrip strict grounding regression check", "strict-real"))

        self.assertEqual(response.tool_calls, ("krx_real_research",))
        self.assertIn("provider strict real research grounding fallback", response.warnings)
        self.assertIn("trade_count=3", response.text)
        self.assertNotIn("trade_count=4", response.text)
        self.assertNotIn("MDD=8", response.text)
        self.assertNotIn("RSI 20", response.text)
        self.assertTrue(contains_ungrounded_real_research_claim("trade_count=4 MDD=8 RSI 20", payload))

    def test_production_real_research_phrase_routes_to_strict_tool(self) -> None:
        text = (
            "가온아 삼성전자 실제 데이터로 아래 전략을 백테스트하고 약점을 분석한 뒤 개선 후보까지 비교해줘.\n\n"
            "20일 고가 돌파\n종가 > MA20 > MA60\n거래량 20일 평균 이상\n손절 -5%\n10일 저점 이탈 청산"
        )

        self.assertEqual(route_read_only_tool(text), "krx_real_research")

    def test_strict_real_research_validator_detects_provider_fabricated_metrics(self) -> None:
        payload = _strict_real_payload()
        provider_text = (
            "총 수익률 5.32%, 10일 기간, 평균 거래 수익률 1.77%, MDD 8%, PF 1.42, 거래 횟수 4회입니다. "
            "-3% 손절, 5% 익절, RSI(14) 30, MA15/MA90, 거래량 평균 * 1.5를 추천합니다."
        )

        violations = strict_real_research_grounding_violations(provider_text, payload)

        self.assertTrue(any(item.startswith("trade_count_mismatch:4!=") for item in violations))
        self.assertTrue(any(item.startswith("total_return_mismatch:5.32!=") for item in violations))
        self.assertTrue(any("RSI(14) 30" in item for item in violations))

    def test_authoritative_metric_aliases_are_structurally_grounded(self) -> None:
        payload = _strict_real_payload()

        allowed = "wins=2 win=2 승리 2회 loss=1 losses=1 trades=3 trade_count=3 MDD 5.2% return 4.7% PF 1.42 거래 횟수 3회"
        blocked = "win=4 loss=4 trade_count=4 MDD=8% 평균 거래 수익률 1.77% 총 수익률 5.32% RSI(14) 30 MA15/MA90 volume 1.5x -3% stop 5% 익절"

        self.assertEqual(strict_real_research_grounding_violations(allowed, payload), ())
        violations = strict_real_research_grounding_violations(blocked, payload)
        self.assertTrue(any(item.startswith("wins_mismatch:4!=") for item in violations))
        self.assertTrue(any(item.startswith("losses_mismatch:4!=") for item in violations))
        self.assertTrue(any(item.startswith("trade_count_mismatch:4!=") for item in violations))
        self.assertTrue(any(item.startswith("mdd_mismatch:8!=") for item in violations))
        self.assertTrue(any(item.startswith("average_trade_missing_authoritative_evidence:1.77") for item in violations))
        self.assertTrue(any(item.startswith("total_return_mismatch:5.32!=") for item in violations))
        self.assertTrue(any("RSI(14) 30" in item for item in violations))

    def test_metric_numbers_are_not_allowed_by_unrelated_output_numbers(self) -> None:
        payload = _strict_real_payload()
        payload["metadata_with_unrelated_number"] = {"unrelated": 4, "notes": "PF is intentionally absent here"}
        payload["backtest"]["metrics"].pop("profit_factor", None)

        violations = strict_real_research_grounding_violations("trade_count=4 PF 1.42", payload)

        self.assertTrue(any(item.startswith("trade_count_mismatch:4!=") for item in violations))
        self.assertTrue(any(item.startswith("profit_factor_missing_authoritative_evidence") for item in violations))

    def test_authoritative_renderer_grounding_invariant_varied_metrics(self) -> None:
        for index, (wins, losses, trades, mdd, total_return) in enumerate(((0, 0, 0, 0.0, 0.0), (1, 2, 3, 0.073, -0.012), (5, 1, 6, 0.181, 0.245))):
            payload = _strict_real_payload()
            payload["backtest"]["metrics"].update({"wins": wins, "losses": losses, "trade_count": trades, "mdd": mdd, "total_return": total_return})
            payload["comparison"]["rows"][0].update({"trade_count": trades, "mdd": mdd, "total_return": total_return})
            text = format_grounded_tool_response("krx_real_research", payload, f"variant {index}")

            self.assertIsNotNone(text)
            assert text is not None
            self.assertEqual(strict_real_research_grounding_violations(text, payload), ())
            self.assertEqual(strict_real_research_grounding_violations(f"wins={wins} losses={losses} trade_count={trades}", payload), ())


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


class _StrictExecutor:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def assistant_tool_definitions(self, request_text: str = "") -> tuple[object, ...]:
        return ()

    def execute(self, request) -> ToolResult:
        return ToolResult(request.tool_name, "success", self._payload)


class _StrictFabricatingProvider:
    def respond(self, request):
        if not request.tool_results:
            return AssistantProviderResponse(
                text="",
                provider_name="openai-compatible",
                tool_calls=(AssistantToolCall("call-krx", "krx_real_research", {"request_text": request.text, "symbol": "005930"}),),
            )
        return AssistantProviderResponse(text="trade_count=4, MDD=8%, RSI 20 filter, volume 1.5x", provider_name="openai-compatible")


def _strict_real_payload() -> dict[str, object]:
    return {
        "dataset": {
            "dataset_id": "dataset:real:yahoo:005930",
            "symbols": [{"symbol": "005930", "name": "Samsung Electronics", "market": "KOSPI"}],
            "bars": [{"timestamp": f"2025-01-{index + 2:02d}", "symbol": "005930"} for index in range(3)],
            "metadata": {"source": "real:yahoo-chart", "start_date": "2025-01-02", "end_date": "2026-07-24", "fixture_backed": False},
        },
        "quality": {"status": "pass_with_warnings", "findings": [{"code": "provider_gap", "message": "real:yahoo-chart missing bar on open KRX date 2025-09-19"}]},
        "strategy": {
            "entry": {"breakout_lookback": {"value": 20, "provenance": "user_provided"}},
            "exit": {"protective_stop_pct": {"value": -5.0, "provenance": "user_provided"}},
            "filters": {"volume_gte_ma20": {"value": True, "provenance": "user_provided"}},
        },
        "assumptions": {"commission": {"value": 0.00015, "provenance": "default"}, "position_sizing": {"value": "single_position_all_cash", "provenance": "default"}},
        "backtest": {"source": "real", "metrics": {"trade_count": 3, "wins": 2, "losses": 1, "total_return": 0.047, "mdd": 0.052, "sharpe": 0.74, "profit_factor": 1.42}},
        "validation": {"validation_id": "validation:strict", "passed": True, "findings": []},
        "critic_findings": [{"severity": "warning", "message_ko": "provider gap을 명시해야 합니다."}],
        "candidates": [{"candidate_id": "candidate:tested", "backtest_result": {"metrics": {"trade_count": 2, "total_return": 0.038, "mdd": 0.044}}}],
        "comparison": {"rows": [{"candidate_id": "original", "trade_count": 3, "total_return": 0.047, "mdd": 0.052}]},
    }


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
