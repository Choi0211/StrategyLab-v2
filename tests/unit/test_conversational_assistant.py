import unittest

from gaon.runtime.assistant_provider import AssistantProviderResponse
from gaon.runtime.conversation import ConversationInput, ConversationRuntime
from gaon.runtime.intents import Intent, parse_intent


class FakeProvider:
    def respond(self, request):
        return AssistantProviderResponse("provider response", route="provider", references=("ref-1",), warnings=("provider warning",))


class ConversationalAssistantTest(unittest.TestCase):
    def message(self, text: str) -> ConversationInput:
        return ConversationInput("telegram", "u1", "c1", f"m-{abs(hash(text))}", text, "2026-07-17T00:00:00Z")

    def test_greeting_mentions_youngha(self) -> None:
        response = ConversationRuntime().handle(self.message("안녕"))
        self.assertEqual(response.intent, Intent.GREETING)
        self.assertIn("영하님", response.text)
        self.assertEqual(response.route, "rule_based")

    def test_call_gaon_response(self) -> None:
        response = ConversationRuntime().handle(self.message("가온"))
        self.assertEqual(response.intent, Intent.CALL_GAON)
        self.assertIn("네, 영하님", response.text)

    def test_natural_language_intents(self) -> None:
        cases = {
            "오늘 시장 어때?": Intent.MARKET_STATUS,
            "삼성전자 분석해줘": Intent.STOCK_ANALYSIS,
            "오늘 일정 알려줘": Intent.SCHEDULE,
            "백테스트 돌려줘": Intent.BACKTEST,
            "도움말": Intent.HELP,
            "지난 연구 알려줘": Intent.RECENT_RESEARCH,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_intent(text), expected)

    def test_today_word_alone_is_unknown(self) -> None:
        self.assertEqual(parse_intent("오늘"), Intent.UNKNOWN)

    def test_unknown_and_empty_fallback(self) -> None:
        runtime = ConversationRuntime()
        for text in ("", "이상한 요청"):
            with self.subTest(text=text):
                response = runtime.handle(self.message(text))
                self.assertEqual(response.intent, Intent.UNKNOWN)
                self.assertIn("영하님", response.text)
                self.assertIn("unknown intent", response.warnings)

    def test_slash_command_regression(self) -> None:
        self.assertEqual(parse_intent("/help"), Intent.HELP)
        self.assertEqual(parse_intent("/status"), Intent.STATUS)
        self.assertEqual(parse_intent("/today"), Intent.TODAY_PLAN)
        self.assertEqual(parse_intent("/research"), Intent.RESEARCH_STATUS)
        self.assertEqual(parse_intent("/memory ORB"), Intent.SEARCH_MEMORY)
        self.assertEqual(parse_intent("/approvals"), Intent.APPROVAL_STATUS)

    def test_provider_is_optional_and_provider_route_is_recorded(self) -> None:
        rule_based = ConversationRuntime().handle(self.message("안녕"))
        provider = ConversationRuntime(assistant_provider=FakeProvider()).handle(self.message("안녕"))

        self.assertEqual(rule_based.route, "rule_based")
        self.assertEqual(provider.route, "provider")
        self.assertEqual(provider.references, ("ref-1",))
        self.assertEqual(provider.warnings, ("provider warning",))

    def test_market_stock_schedule_and_backtest_do_not_claim_execution(self) -> None:
        runtime = ConversationRuntime()
        for text in ("오늘 시장 어때?", "삼성전자 분석해줘", "오늘 일정 알려줘", "백테스트 돌려줘"):
            with self.subTest(text=text):
                response = runtime.handle(self.message(text))
                self.assertIn("아직", response.text)
                self.assertFalse(response.approval_required)

    def test_order_and_approval_safety_regression(self) -> None:
        response = ConversationRuntime().handle(self.message("삼성전자 매수 주문 실행해줘"))

        self.assertTrue(response.approval_required)
        self.assertTrue(any("투자 주문" in warning for warning in response.warnings))


if __name__ == "__main__":
    unittest.main()
