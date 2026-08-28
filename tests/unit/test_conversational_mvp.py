import unittest

from gaon.runtime.conversational_mvp import (
    ConversationalMVPContext,
    ConversationalMVPIntent,
    ExplanationLevel,
    ConversationStyle,
    ExplanationDepth,
    PresentationPreference,
    PresentationFormat,
    ResponseLength,
    build_reasoning_result,
    presentation_preference_for_text,
    render_presentation_from_payloads,
    classify_conversational_route,
    explanation_level_for_text,
    extract_symbol_entities,
    render_reasoning_from_payloads,
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

    def test_comparison_typo_and_symbol_typo_are_tolerated(self) -> None:
        route = classify_conversational_route("삼성전자와 sk하이닏스 비겨해줘")

        self.assertEqual(route.intent, ConversationalMVPIntent.COMPARE_SYMBOLS)
        self.assertEqual(tuple(item.symbol for item in route.symbols), ("005930", "000660"))

    def test_period_rerun_comparison_typo_is_timeframe_change(self) -> None:
        route = classify_conversational_route("3년으로 다시 비겨해줘")

        self.assertEqual(route.intent, ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST)

    def test_single_symbol_analysis_intent(self) -> None:
        route = classify_conversational_route("삼성전자 분석해줘")

        self.assertEqual(route.intent, ConversationalMVPIntent.SINGLE_SYMBOL_ANALYSIS)
        self.assertEqual(route.symbols[0].symbol, "005930")

    def test_greeting_does_not_become_status_dump(self) -> None:
        route = classify_conversational_route("안녕하세요")

        self.assertEqual(route.intent, ConversationalMVPIntent.GREETING)
        self.assertEqual(route.symbols, ())

    def test_production_capability_availability_and_feedback_are_not_unknown(self) -> None:
        self.assertEqual(classify_conversational_route("뭘 할 수 있나요?").intent, ConversationalMVPIntent.HELP)
        for text in ("현재 동작을 하고 있나요?", "대화가 가능한가요?", "지금은 대화가 가능한가요"):
            with self.subTest(text=text):
                self.assertEqual(classify_conversational_route(text).intent, ConversationalMVPIntent.STATUS_QUERY)
        for text in ("맨날 없네요", "제가 업데이트를 잘못했나봐요 이상해졌넹"):
            with self.subTest(text=text):
                self.assertEqual(classify_conversational_route(text).intent, ConversationalMVPIntent.GENERAL_CONVERSATION)

    def test_contextual_backtest_request_is_not_unrelated_tool_fallback(self) -> None:
        self.assertEqual(classify_conversational_route("백테스트해주세요").intent, ConversationalMVPIntent.RERUN_REQUEST)

    def test_followup_typo_is_narrowly_classified_as_explanation(self) -> None:
        route = classify_conversational_route("왜 그절? 판간했어?")

        self.assertEqual(route.intent, ConversationalMVPIntent.EXPLAIN_PREVIOUS_RESULT)
        self.assertEqual(route.symbols, ())

    def test_followup_simplify_and_detail_phrases_are_classified(self) -> None:
        simple = classify_conversational_route("쉽게 설명해줘")
        detail = classify_conversational_route("자세히 보여줘")

        self.assertEqual(simple.intent, ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT)
        self.assertEqual(detail.intent, ConversationalMVPIntent.SHOW_DETAILS)


    def test_sprint154_presentation_style_length_and_depth_model(self) -> None:
        self.assertEqual(presentation_preference_for_text("한 줄로 말해줘").length, ResponseLength.ONE_LINE)
        self.assertEqual(presentation_preference_for_text("가르쳐주듯 설명해줘").style, ConversationStyle.TEACHING)
        self.assertEqual(presentation_preference_for_text("전문적으로 설명해줘").depth, ExplanationDepth.PROFESSIONAL)
        self.assertEqual(presentation_preference_for_text("보고서로 정리해줘").style, ConversationStyle.REPORT)

    def test_hotfix1541_explicit_detail_overrides_previous_short_preference(self) -> None:
        short = presentation_preference_for_text("한 줄로 말해줘")
        detail = presentation_preference_for_text("자세히 보여줘", short)

        self.assertEqual(detail.style, ConversationStyle.REPORT)
        self.assertEqual(detail.depth, ExplanationDepth.DETAILED)
        self.assertEqual(detail.length, ResponseLength.LONG)
        self.assertEqual(detail.format, PresentationFormat.BULLETS)

    def test_hotfix1541_explicit_short_preserves_grounded_source(self) -> None:
        payload = _payload(trade_count=1, fixture_backed=False)
        text = render_presentation_from_payloads((payload,), intent=ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, user_text="조금 더 짧게", preference=PresentationPreference(style=ConversationStyle.EXPLANATORY, depth=ExplanationDepth.SIMPLE))

        self.assertNotIn("[결론]", text)
        self.assertEqual(text.count("Yahoo Chart 공개 데이터"), 1)
        self.assertNotIn("명시되지", text)
        self.assertNotIn("알 수 없음", text)

    def test_sprint154_direct_answer_first_and_conversational_rendering(self) -> None:
        payload = _payload(trade_count=1, fixture_backed=False)
        text = render_presentation_from_payloads((payload,), intent=ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, user_text="삼성전자 지금 사도 돼?", preference=PresentationPreference())

        self.assertTrue(text.startswith("현재 결과만으로는 매수를 추천하기 어렵습니다."))
        self.assertIn("거래 표본", text)
        self.assertNotIn("[결론]", text)
        self.assertNotIn("strategy_fingerprint", text)
        self.assertNotIn("fixture_backed", text)

    def test_sprint154_one_line_keeps_context_but_shortens(self) -> None:
        payload = _payload(trade_count=1, fixture_backed=False)
        text = render_presentation_from_payloads((payload,), intent=ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, user_text="한 줄로 말해줘", preference=PresentationPreference())

        self.assertLessEqual(len([line for line in text.splitlines() if line.strip()]), 1)
        self.assertIn("거래", text)

    def test_sprint154_teaching_analogy_does_not_create_new_metrics(self) -> None:
        payload = _payload(trade_count=1, fixture_backed=False)
        text = render_presentation_from_payloads((payload,), intent=ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, user_text="비유해서 설명해줘", preference=PresentationPreference())

        self.assertIn("시험 문제", text)
        self.assertNotIn("RSI", text)
        self.assertNotIn("MA90", text)
        self.assertNotIn("매수하세요", text)

    def test_sprint154_numeric_example_uses_initial_capital_and_mdd(self) -> None:
        payload = _payload(trade_count=3, fixture_backed=False)
        text = render_presentation_from_payloads((payload,), intent=ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, user_text="예를 들어 설명해줘", preference=PresentationPreference(style=ConversationStyle.TEACHING))

        self.assertIn("1,000,000원", text)
        self.assertIn("44,000원", text)
        self.assertIn("956,000원", text)

    def test_hotfix1541_numeric_example_states_mdd_is_illustrative(self) -> None:
        payload = _payload(trade_count=3, fixture_backed=False, mdd=0.192288)
        text = render_presentation_from_payloads((payload,), intent=ConversationalMVPIntent.CONTEXTUAL_FOLLOWUP, user_text="예를 들어 설명해줘", preference=PresentationPreference(style=ConversationStyle.TEACHING))

        self.assertIn("192,288원", text)
        self.assertIn("807,712원", text)
        self.assertIn("단순 적용", text)
        self.assertIn("설명용 예시", text)
        self.assertIn("직접 발생했다는 뜻은 아닙니다", text)

    def test_sprint153_reasoning_intents_are_classified(self) -> None:
        self.assertEqual(classify_conversational_route("삼성전자 지금 사도 돼?").intent, ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION)
        self.assertEqual(classify_conversational_route("위험은 어느 정도야?").intent, ConversationalMVPIntent.RISK_QUESTION)
        self.assertEqual(classify_conversational_route("전문적으로 설명해줘").intent, ConversationalMVPIntent.PROFESSIONAL_EXPLANATION)
        self.assertEqual(classify_conversational_route("3년 기간으로 다시 해줘").intent, ConversationalMVPIntent.TIMEFRAME_CHANGE_REQUEST)

    def test_sprint153_explanation_level_model(self) -> None:
        self.assertEqual(explanation_level_for_text("쉽게 설명해줘", ConversationalMVPIntent.SIMPLIFY_PREVIOUS_RESULT), ExplanationLevel.SIMPLE)
        self.assertEqual(explanation_level_for_text("전문적으로 설명해줘", ConversationalMVPIntent.PROFESSIONAL_EXPLANATION), ExplanationLevel.PROFESSIONAL)
        self.assertEqual(explanation_level_for_text("자세히 보여줘", ConversationalMVPIntent.SHOW_DETAILS), ExplanationLevel.DETAILED)

    def test_single_renderer_hides_internal_fields_and_warns_for_one_trade(self) -> None:
        text = render_single_symbol_summary(_payload("005930", trade_count=1, profit_factor="inf"), user_text="삼성전자 분석해줘")

        self.assertIn("영하님", text)
        self.assertIn("삼성전자", text)
        self.assertIn("거래 표본이 1건뿐이므로", text)
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

        self.assertIn("Yahoo Chart 공개 데이터", text)
        self.assertIn("데이터 무결성 검토 통과", text)
        self.assertIn("전략 성과가 검증됐다는 뜻은 아닙니다", text)
        self.assertNotIn("fixture 데이터 기반", text)

    def test_missing_context_response_is_deterministic(self) -> None:
        self.assertEqual(render_missing_context(), "직전에 설명할 분석 결과가 없습니다. 먼저 종목 분석이나 비교를 요청해 주세요.")

    def test_detail_renderer_preserves_currency_expectancy_units(self) -> None:
        payload = _payload("005930", trade_count=3, profit_factor=1.42)
        payload["dataset"]["metadata"]["source"] = "real:yahoo-chart"
        payload["dataset"]["metadata"]["fixture_backed"] = False
        payload["assumptions"] = {"initial_capital": {"value": 1000000.0, "provenance": "default"}}
        payload["backtest"]["metrics"]["expectancy"] = 297134.3
        payload["backtest"]["metrics"]["average_trade"] = 297134.3
        payload["backtest"]["metrics"]["ending_equity"] = 1047000.0

        text = render_single_symbol_summary(payload, user_text="삼성전자 자세히 보여줘", detail_level="detail")

        self.assertIn("297,134.30", text)
        self.assertIn("29.71%", text)
        self.assertNotIn("29713430.00%", text)
        self.assertNotIn("strategy_fingerprint", text)
        self.assertNotIn("quality_status=", text)
        self.assertNotIn("source=", text)

    def test_detail_renderer_handles_none_and_zero_trade_without_false_safety(self) -> None:
        payload = _payload("000660", trade_count=0, profit_factor=None)
        payload["backtest"]["metrics"]["expectancy"] = None
        payload["backtest"]["metrics"]["mdd"] = 0.0

        text = render_single_symbol_summary(payload, user_text="SK하이닉스 자세히 보여줘", detail_level="detail")

        self.assertIn("계산 불가", text)
        self.assertIn("거래가 없어", text)
        self.assertNotIn("위험 없음", text)
        self.assertNotIn("주의: 주의:", text)

    def test_sprint153_investment_question_is_evidence_bound_and_guarded(self) -> None:
        payload = _payload("005930", trade_count=1, profit_factor="inf")
        text = render_reasoning_from_payloads((payload,), intent=ConversationalMVPIntent.INVESTMENT_DECISION_QUESTION, level=ExplanationLevel.STANDARD, user_text="삼성전자 지금 사도 돼?")

        self.assertIn("[결론]", text)
        self.assertIn("매수", text)
        self.assertIn("거래 표본", text)
        self.assertIn("데이터 무결성", text)
        self.assertIn("재검증", text)
        self.assertNotIn("지금 사세요", text)
        self.assertNotIn("quality_status=", text)
        self.assertNotIn("strategy_fingerprint", text)

    def test_sprint153_zero_trade_risk_is_not_described_as_safe(self) -> None:
        payload = _payload("000660", trade_count=0, profit_factor=None)
        payload["backtest"]["metrics"]["mdd"] = 0.0
        text = render_reasoning_from_payloads((payload,), intent=ConversationalMVPIntent.RISK_QUESTION, level=ExplanationLevel.PROFESSIONAL, user_text="위험은 어느 정도야?")

        self.assertIn("MDD", text)
        self.assertIn("Sharpe", text)
        self.assertIn("Profit Factor", text)
        self.assertIn("Exposure", text)
        self.assertIn("거래가 없", text)
        self.assertIn("위험 없음", text)
        self.assertNotIn("안정적", text)

    def test_sprint153_reasoning_result_is_typed(self) -> None:
        payload = _payload("005930", trade_count=3, profit_factor=1.2)
        result = build_reasoning_result((payload,), intent=ConversationalMVPIntent.RISK_QUESTION, level=ExplanationLevel.STANDARD, user_text="위험은?")

        self.assertEqual(result.intent, ConversationalMVPIntent.RISK_QUESTION)
        self.assertEqual(result.symbols, ("005930",))
        self.assertTrue(result.evidence_points)
        self.assertTrue(result.limitations)
        self.assertIn("매수 또는 매도 추천", result.unsupported_claims_blocked)


def _payload(symbol: str = "005930", *, trade_count: int = 3, profit_factor=1.2, fixture_backed: bool = True, mdd: float = 0.044) -> dict[str, object]:
    return {
        "dataset": {
            "symbols": [{"symbol": symbol, "name": symbol}],
            "metadata": {
                "source": "fixture:test" if fixture_backed else "real:yahoo-chart",
                "start_date": "2026-01-02",
                "end_date": "2026-07-10",
                "fixture_backed": fixture_backed,
            },
        },
        "quality": {"status": "pass"},
        "strategy": {"fingerprint": "strategy:test"},
        "assumptions": {"initial_capital": {"value": 1000000.0, "provenance": "test"}},
        "backtest": {
            "result_id": f"backtest:{symbol}",
            "metrics": {
                "total_return": 0.05,
                "mdd": mdd,
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
