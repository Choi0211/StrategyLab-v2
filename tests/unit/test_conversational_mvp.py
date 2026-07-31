import unittest

from gaon.runtime.conversational_mvp import (
    ConversationalMVPContext,
    ConversationalMVPIntent,
    classify_conversational_route,
    extract_symbol_entities,
    render_follow_up,
    render_missing_context,
    render_single_symbol_summary,
)


class ConversationalMVPTests(unittest.TestCase):
    def test_extracts_korean_and_numeric_symbols(self) -> None:
        symbols = extract_symbol_entities("삼성전자와 SK하이닉스 그리고 005380 비교해줘")

        self.assertEqual(tuple(item.symbol for item in symbols), ("005380", "005930", "000660"))

    def test_comparison_intent_requires_two_symbols(self) -> None:
        route = classify_conversational_route("삼성전자와 SK하이닉스 비교해줘")

        self.assertEqual(route.intent, ConversationalMVPIntent.COMPARE_SYMBOLS)
        self.assertEqual(tuple(item.symbol for item in route.symbols), ("005930", "000660"))

    def test_single_symbol_analysis_intent(self) -> None:
        route = classify_conversational_route("삼성전자 분석해줘")

        self.assertEqual(route.intent, ConversationalMVPIntent.SINGLE_SYMBOL_ANALYSIS)
        self.assertEqual(route.symbols[0].symbol, "005930")

    def test_greeting_does_not_become_status_dump(self) -> None:
        route = classify_conversational_route("안녕하세요")

        self.assertEqual(route.intent, ConversationalMVPIntent.GREETING)
        self.assertEqual(route.symbols, ())

    def test_followup_typo_is_narrowly_classified_as_explanation(self) -> None:
        route = classify_conversational_route("왜 그절? 판간했어?")

        self.assertEqual(route.intent, ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT)
        self.assertEqual(route.symbols, ())

    def test_followup_simplify_and_detail_phrases_are_classified(self) -> None:
        simple = classify_conversational_route("쉽게 설명해줘")
        detail = classify_conversational_route("자세히 보여줘")

        self.assertEqual(simple.intent, ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT)
        self.assertEqual(detail.intent, ConversationalMVPIntent.SHOW_DETAILS)

    def test_single_renderer_hides_internal_fields_and_warns_for_one_trade(self) -> None:
        text = render_single_symbol_summary(_payload("005930", trade_count=1, profit_factor="inf"), user_text="삼성전자 분석해줘")

        self.assertIn("영하님", text)
        self.assertIn("삼성전자", text)
        self.assertIn("주의: 거래 표본이 1건뿐이므로", text)
        self.assertIn("손실 거래 없음으로 해석 제한", text)
        for forbidden in ("validation_id", "fixture_backed", "None", " inf", "<output>", "유니"):
            self.assertNotIn(forbidden, text)

    def test_followup_context_preserves_real_source_without_fixture_warning(self) -> None:
        payload = _payload("005930", trade_count=1, profit_factor="inf")
        payload["dataset"]["metadata"]["source"] = "real:yahoo-chart"
        payload["dataset"]["metadata"]["fixture_backed"] = False
        context = ConversationalMVPContext(
            last_intent=ConversationalMVPIntent.SINGLE_SYMBOL_ANALYSIS.value,
            last_symbols=("005930",),
            last_result_kind="single_symbol_research",
            last_research_result_ids=("backtest:005930",),
            last_rendered_result="summary",
            last_payloads=(payload,),
            last_structured_results=(payload,),
            last_summary="summary",
            last_detail_payload=payload,
            last_source="real:yahoo-chart",
            last_fixture_backed=False,
            last_quality_status="pass",
            detail_level="summary",
            created_at="2026-07-30T00:00:00Z",
            updated_at="2026-07-30T00:00:00Z",
        )

        text = render_follow_up(context, ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT)

        self.assertIn("real:yahoo-chart", text)
        self.assertIn("quality_status=pass", text)
        self.assertIn("전략 성과가 검증됐다는 뜻은 아닙니다", text)
        self.assertNotIn("fixture 데이터 기반", text)

    def test_missing_context_response_is_deterministic(self) -> None:
        self.assertEqual(render_missing_context(), "직전에 설명할 분석 결과가 없습니다. 먼저 종목 분석이나 비교를 요청해 주세요.")


def _payload(symbol: str, *, trade_count: int = 3, profit_factor=1.2) -> dict[str, object]:
    return {
        "dataset": {
            "symbols": [{"symbol": symbol, "name": symbol}],
            "metadata": {
                "source": "fixture:test",
                "start_date": "2026-01-02",
                "end_date": "2026-07-10",
                "fixture_backed": True,
            },
        },
        "quality": {"status": "pass"},
        "strategy": {"fingerprint": "strategy:test"},
        "backtest": {
            "result_id": f"backtest:{symbol}",
            "metrics": {
                "total_return": 0.05,
                "mdd": 0.08,
                "trade_count": trade_count,
                "profit_factor": profit_factor,
                "win_rate": 1.0 if trade_count == 1 else 0.5,
                "cagr": 0.04,
                "sharpe": 0.7,
                "expectancy": 0.01,
                "exposure": 0.2,
            },
        },
    }


if __name__ == "__main__":
    unittest.main()
