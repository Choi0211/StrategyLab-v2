import unittest

from gaon.runtime.conversational_mvp import ConversationalMVPContext
from gaon.runtime.conversational_research_execution import (
    build_conversational_research_execution_request,
    previous_request_text,
    render_conversational_research_execution_result,
    ConversationalResearchExecutionResult,
)


def _context(symbols=("005930",), result_kind="single_symbol_research") -> ConversationalMVPContext:
    payloads = tuple(
        {
            "request_text": "20일 고가 돌파 전략",
            "dataset": {
                "symbols": [{"symbol": symbol}],
                "metadata": {
                    "source": "real:yahoo-chart",
                    "fixture_backed": False,
                    "start_date": "2026-01-02",
                    "end_date": "2026-07-10",
                },
            },
            "quality": {"status": "pass", "findings": []},
            "backtest": {
                "metrics": {
                    "trade_count": 1,
                    "total_return": 0.0123,
                    "mdd": 0.044,
                    "win_rate": 1.0,
                    "profit_factor": "inf",
                }
            },
        }
        for symbol in symbols
    )
    return ConversationalMVPContext(
        last_intent="single_symbol_analysis",
        last_symbols=tuple(symbols),
        last_result_kind=result_kind,
        last_research_result_ids=(),
        last_rendered_result="summary",
        last_payloads=payloads,
        last_structured_results=payloads,
        last_summary="summary",
        last_detail_payload={},
        last_source="real:yahoo-chart",
        last_fixture_backed=False,
        last_quality_status="pass",
        detail_level="summary",
        created_at="2026-07-10T00:00:00Z",
        updated_at="2026-07-10T00:00:00Z",
    )


class ConversationalResearchExecutionTests(unittest.TestCase):
    def test_resolves_five_year_period_from_previous_context(self) -> None:
        request = build_conversational_research_execution_request("5년으로 다시 해봐", _context(), received_at="2026-07-30T00:00:00Z")

        self.assertFalse(request.requires_confirmation)
        self.assertEqual(request.symbols, ("005930",))
        self.assertEqual(request.start_date, "2021-07-11")
        self.assertEqual(request.end_date, "2026-07-10")
        self.assertTrue(request.reuse_previous_strategy)
        self.assertEqual(request.inferred_fields["symbols"], ("005930",))

    def test_ambiguous_longer_period_requires_confirmation(self) -> None:
        request = build_conversational_research_execution_request("더 긴 기간으로 다시 분석해봐", _context(), received_at="2026-07-30T00:00:00Z")

        self.assertTrue(request.requires_confirmation)
        self.assertIsNone(request.start_date)

    def test_explicit_user_symbol_overrides_context_symbol(self) -> None:
        request = build_conversational_research_execution_request("SK하이닉스 3년으로 다시 분석해줘", _context(), received_at="2026-07-30T00:00:00Z")

        self.assertEqual(request.symbols, ("000660",))
        self.assertEqual(request.start_date, "2023-07-11")
        self.assertEqual(request.user_provided_fields["symbols"], ("000660",))

    def test_multi_symbol_context_marks_comparison(self) -> None:
        request = build_conversational_research_execution_request("3년으로 다시 비교해줘", _context(("005930", "000660"), "symbol_comparison"), received_at="2026-07-30T00:00:00Z")

        self.assertTrue(request.comparison_requested)
        self.assertEqual(request.symbols, ("005930", "000660"))

    def test_previous_request_text_uses_structured_context_not_rendered_text(self) -> None:
        self.assertEqual(previous_request_text(_context(), "fallback"), "20일 고가 돌파 전략")

    def test_renderer_uses_only_structured_metrics(self) -> None:
        payload = _context().last_payloads[0]
        rendered = render_conversational_research_execution_result(
            ConversationalResearchExecutionResult(
                "success",
                ("005930",),
                "2021-07-11",
                "2026-07-10",
                (payload,),
                (payload,),
                {},
                ({"status": "pass"},),
                (),
                ("safe_tool_execution",),
            )
        )

        self.assertIn("거래 수: 1회", rendered)
        self.assertIn("Yahoo Chart 공개 데이터", rendered)
        self.assertNotIn("run_id", rendered)
        self.assertNotIn("strategy_fingerprint", rendered)


if __name__ == "__main__":
    unittest.main()
