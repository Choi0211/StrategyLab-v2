import unittest

from gaon.runtime.conversational_mvp import (
    ConversationalMVPIntent,
    classify_conversational_route,
    extract_symbol_entities,
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

    def test_single_renderer_hides_internal_fields_and_warns_for_one_trade(self) -> None:
        text = render_single_symbol_summary(_payload("005930", trade_count=1, profit_factor="inf"), user_text="삼성전자 분석해줘")

        self.assertIn("영하님", text)
        self.assertIn("삼성전자", text)
        self.assertIn("주의: 거래 표본이 1건뿐이므로", text)
        self.assertIn("손실 거래 없음으로 해석 제한", text)
        for forbidden in ("validation_id", "fixture_backed", "None", " inf", "<output>", "유니"):
            self.assertNotIn(forbidden, text)


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
